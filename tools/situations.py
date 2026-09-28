#!/usr/bin/env python3
"""Live road situations: accidents, stalled cars, closed lanes, roadworks, jams, speed
limits, and traffic-light overrides.

Commands come from the game (a click on a road) or from a scenario file. They are parsed
here, queued by the bridge, and applied between SUMO steps: libsumo runs in-process and is
not re-entrant, so nothing may touch it while a step is running.

Every change records how to undo it, captured from the static network *before* the change,
so cancelling restores what was really there instead of a guessed default.

None of this is measured Kyiv data. An incident exists because someone clicked the map or
wrote it into a scenario; traffic-light programs stay the netconvert defaults they were.
"""
import itertools
import math

KINDS = ('accident', 'stalled', 'lane_closed', 'roadworks', 'jam', 'speed_limit')
TLS_ACTIONS = ('program', 'phase', 'next', 'allred', 'amber', 'off', 'restore')
MAX_SECONDS = 3600.0
ROADWORKS_SPEED = 20 / 3.6
JAM_SPEED = 2.0
# Vehicle type of stalled / crashed cars. vClass 'ignoring' is exempt from lane permissions:
# a 'passenger' car placed on a lane that is (or becomes) closed by another incident made
# SUMO fail at insertion ("Invalid departlane definition", FatalTraCIError) and libsumo
# then crashed the whole bridge with an access violation on the next step.
INCIDENT_TYPE = 'incident_car'
AMBER_PERIOD = 0.6               # s between flashes of the amber-blinking mode

# English labels; the game translates them by kind (game/i18n/strings.csv).
LABELS = {'accident': 'Accident', 'stalled': 'Stalled car', 'lane_closed': 'Lane closed',
          'roadworks': 'Roadworks', 'jam': 'Traffic jam', 'speed_limit': 'Speed limit'}


def _finite(*values):
    return all(isinstance(v, (int, float)) and math.isfinite(v) for v in values)


def parse_command(msg, next_id=None):
    """One inbound control message -> a plain command dict, or None if it is malformed.

    Pure: no SUMO, no network lookup. Ids of edges and traffic lights are checked later,
    where the network is known, so this stays unit-testable without a simulation."""
    if not isinstance(msg, dict):
        return None
    kind = msg.get('type')
    if kind == 'incident':
        action = msg.get('action', 'add')
        if action == 'add':
            what = msg.get('kind')
            if what not in KINDS:
                return None
            cmd = {'type': 'incident', 'action': 'add', 'kind': what,
                   'id': str(msg.get('id') or (next_id() if next_id else 'inc')),
                   'duration': 0.0}
            duration = msg.get('duration', 0)
            if not _finite(duration):
                return None
            cmd['duration'] = max(0.0, min(MAX_SECONDS, float(duration)))
            point = msg.get('p')
            if isinstance(point, list) and len(point) == 3 and _finite(*point):
                cmd['p'] = [float(v) for v in point]
            elif isinstance(msg.get('edge'), str) and msg['edge']:
                cmd['edge'] = msg['edge']
                if _finite(msg.get('pos', 0)):
                    cmd['pos'] = max(0.0, float(msg.get('pos', 0)))
                if isinstance(msg.get('lane_index'), int):
                    cmd['lane_index'] = max(0, msg['lane_index'])
            else:
                return None
            if what in ('speed_limit', 'roadworks'):
                value = msg.get('value_kmh', 20 if what == 'roadworks' else 40)
                if not _finite(value) or not 1 <= float(value) <= 130:
                    return None
                cmd['value_kmh'] = float(value)
            return cmd
        if action == 'remove' and msg.get('id'):
            return {'type': 'incident', 'action': 'remove', 'id': str(msg['id'])}
        if action == 'clear':
            return {'type': 'incident', 'action': 'clear'}
        return None
    if kind == 'tls':
        action = msg.get('action')
        if action not in TLS_ACTIONS or not isinstance(msg.get('id'), str) or not msg['id']:
            return None
        cmd = {'type': 'tls', 'action': action, 'id': msg['id']}
        if action == 'program':
            if not isinstance(msg.get('value'), str):
                return None
            cmd['value'] = msg['value']
        if action == 'phase':
            if not isinstance(msg.get('value'), int) or msg['value'] < 0:
                return None
            cmd['value'] = msg['value']
        return cmd
    if kind == 'pick':
        point = msg.get('p')
        if isinstance(point, list) and len(point) == 3 and _finite(*point):
            return {'type': 'pick', 'p': [float(v) for v in point]}
        return None
    return None


class LaneIndex:
    """World point (Godot space) -> nearest drivable lane, with the offset along it.

    A 50 m grid over the exported lane polylines. sumolib can answer the same question
    with getNeighboringLanes, but without the optional rtree module it walks every lane:
    137 ms on Академмістечко, and far worse on Західний Київ — a whole bridge tick."""
    CELL = 50.0

    def __init__(self, lanes):
        self.cells = {}
        self.lanes = {}
        for lane in lanes:
            lid = lane['id']
            if lid.startswith(':') or lane.get('internal'):
                continue                       # junction-internal lanes are not clickable
            points = lane['points']
            if len(points) < 2:
                continue
            offsets = [0.0]
            for a, b in zip(points, points[1:]):
                offsets.append(offsets[-1] + math.dist((a[0], a[2]), (b[0], b[2])))
            self.lanes[lid] = (points, offsets)
            for i, p in enumerate(points):
                self.cells.setdefault((int(p[0] // self.CELL), int(p[2] // self.CELL)), []).append((lid, i))

    def nearest(self, p, radius=40.0):
        """-> (lane id, offset along the lane in metres, distance) or None."""
        x, z = float(p[0]), float(p[2])
        reach = max(1, int(radius // self.CELL) + 1)
        cx, cz = int(x // self.CELL), int(z // self.CELL)
        best = None
        for dx in range(-reach, reach + 1):
            for dz in range(-reach, reach + 1):
                for lid, i in self.cells.get((cx + dx, cz + dz), ()):
                    points, offsets = self.lanes[lid]
                    d = math.dist((x, z), (points[i][0], points[i][2]))
                    if best is None or d < best[2]:
                        best = (lid, offsets[i], d)
        if best is None or best[2] > radius:
            return None
        return best

    def point_at(self, lid, offset):
        """-> ([x, y, z], heading degrees) at an offset along a lane, for HUD markers."""
        points, offsets = self.lanes[lid]
        i = 0
        while i < len(offsets) - 2 and offsets[i + 1] < offset:
            i += 1
        a, b = points[i], points[i + 1]
        span = max(1e-6, offsets[i + 1] - offsets[i])
        t = min(1.0, max(0.0, (offset - offsets[i]) / span))
        pos = [a[j] + (b[j] - a[j]) * t for j in range(3)]
        return pos, math.degrees(math.atan2(b[0] - a[0], -(b[2] - a[2]))) % 360


class Incident:
    """One live road situation and the exact way to undo it."""

    def __init__(self, iid, kind, edge, lanes, position, heading, ends_at, value=None):
        self.id = iid
        self.kind = kind
        self.edge = edge
        self.lanes = lanes
        self.position = position
        self.heading = heading
        self.ends_at = ends_at
        self.value = value
        self.undo = []
        self.vehicles = []
        self.blocking = False

    def snapshot(self, now):
        return {'id': self.id, 'kind': self.kind, 'label': LABELS.get(self.kind, self.kind),
                'edge': self.edge, 'lanes': self.lanes, 'p': [round(v, 2) for v in self.position],
                'heading': round(self.heading, 1), 'blocking': self.blocking,
                'value': self.value,
                'left': None if self.ends_at is None else max(0, round(self.ends_at - now))}


class Situations:
    """All live incidents and traffic-light overrides for one simulation."""

    def __init__(self, c, net, index, elevation=None):
        self.c = c
        self.net = net
        self.index = index                      # LaneIndex
        self.elevation = elevation
        self.items = {}
        self.tls = {}                           # tls id -> {'mode', 'program', 'n', 'flip'}
        self.rev = 0
        self.serial = itertools.count(1)
        self.serial_car = itertools.count(1)

    # ---- helpers -------------------------------------------------------------
    def next_id(self):
        return f'inc{next(self.serial)}'

    @property
    def protected(self):
        """Vehicles an incident owns: the density controller must not remove them."""
        return {v for item in self.items.values() for v in item.vehicles}

    def passenger_lanes(self, edge_id):
        """Driving lanes of an edge, in SUMO index order. Index 0 is often a sidewalk
        (netconvert --osm.sidewalks), so a lane's position in this list is NOT its SUMO
        lane index: callers must use getIndex()."""
        edge = self.net.getEdge(edge_id)
        return [l for l in edge.getLanes() if l.allows('passenger')]

    def resolve(self, cmd):
        """-> (edge id, offset, lane index) for a command addressed by point or by edge."""
        if 'p' in cmd:
            hit = self.index.nearest(cmd['p'])
            if hit is None:
                raise ValueError('No road nearby')
            lid, offset, _ = hit
            edge_id, _, idx = lid.rpartition('_')
            return edge_id, offset, int(idx)
        edge_id = cmd['edge']
        self.net.getEdge(edge_id)               # raises if unknown
        return edge_id, float(cmd.get('pos', 10.0)), int(cmd.get('lane_index', 0))

    # ---- incidents -----------------------------------------------------------
    def add(self, cmd, now):
        edge_id, offset, lane_index = self.resolve(cmd)
        lanes = self.passenger_lanes(edge_id)
        if not lanes:
            raise ValueError('This road has no lanes for cars')
        indices = [l.getIndex() for l in lanes]
        lane_index = min(indices, key=lambda i: abs(i - lane_index))
        length = lanes[0].getLength()
        offset = min(max(1.0, offset), max(1.0, length - 1.0))
        lid = f'{edge_id}_{lane_index}'
        position, heading = (self.index.point_at(lid, offset) if lid in self.index.lanes
                             else ([0.0, 0.0, 0.0], 0.0))
        kind = cmd['kind']
        ends_at = None if not cmd.get('duration') else now + cmd['duration']
        item = Incident(cmd['id'], kind, edge_id, [l.getID() for l in lanes], position,
                        heading, ends_at, cmd.get('value_kmh'))
        getattr(self, f'_apply_{kind}')(item, lanes, lane_index, offset, cmd)
        self.items[item.id] = item
        self.rev += 1
        return item

    def _slow(self, item, lanes, speed):
        for lane in lanes:
            lid = lane.getID()
            original = lane.getSpeed()          # static network value, not a live override
            self.c.lane.setMaxSpeed(lid, speed)
            item.undo.append(lambda lid=lid, v=original: self.c.lane.setMaxSpeed(lid, v))

    def _close(self, item, lane):
        lid = lane.getID()
        allowed = list(self.c.lane.getAllowed(lid))
        self.c.lane.setDisallowed(lid, ['passenger'])
        item.undo.append(lambda lid=lid, a=allowed: self.c.lane.setAllowed(lid, a))
        # Travel time the rerouting device sees (30% of cars re-route, traffic.py SUMO args),
        # so a closed lane actually pushes traffic onto other streets.
        edge = item.edge
        base = self.c.edge.getTraveltime(edge)
        self.c.edge.adaptTraveltime(edge, base * 8)
        item.undo.append(lambda e=edge, t=base: self.c.edge.adaptTraveltime(e, t))

    def incident_type(self):
        if INCIDENT_TYPE not in self.c.vehicletype.getIDList():
            self.c.vehicletype.copy('car', INCIDENT_TYPE)
            self.c.vehicletype.setVehicleClass(INCIDENT_TYPE, 'ignoring')
        return INCIDENT_TYPE

    def _stop_car(self, item, edge_id, lane_index, offset, colour):
        vid = f'{item.id}_v{next(self.serial_car)}'
        rid = f'{vid}_route'
        self.c.route.add(rid, [edge_id])
        self.c.vehicle.add(vid, rid, typeID=self.incident_type(), departLane=str(lane_index),
                           departPos=str(round(offset, 2)), departSpeed='0')
        self.c.vehicle.setSpeedMode(vid, 0)
        self.c.vehicle.setSpeed(vid, 0)
        self.c.vehicle.setColor(vid, colour)
        item.vehicles.append(vid)
        item.undo.append(lambda v=vid: self._remove_car(v))

    def _remove_car(self, vid):
        try:
            self.c.vehicle.remove(vid)
        except Exception:
            pass

    def _apply_speed_limit(self, item, lanes, lane_index, offset, cmd):
        self._slow(item, lanes, float(cmd.get('value_kmh', 40)) / 3.6)

    def _apply_roadworks(self, item, lanes, lane_index, offset, cmd):
        self._slow(item, lanes, float(cmd.get('value_kmh', 20)) / 3.6)
        if len(lanes) > 1:
            self._close(item, lanes[0])         # index 0 is the rightmost lane in SUMO
        else:
            item.blocking = False

    def _apply_jam(self, item, lanes, lane_index, offset, cmd):
        self._slow(item, lanes, JAM_SPEED)

    def _apply_lane_closed(self, item, lanes, lane_index, offset, cmd):
        self._close(item, next(l for l in lanes if l.getIndex() == lane_index))
        item.blocking = len(lanes) == 1

    def _apply_stalled(self, item, lanes, lane_index, offset, cmd):
        self._stop_car(item, item.edge, lane_index, offset, (240, 170, 40, 255))

    def _apply_accident(self, item, lanes, lane_index, offset, cmd):
        """Two cars across neighbouring lanes: what actually blocks a street."""
        indices = [l.getIndex() for l in lanes]
        others = [i for i in indices if i != lane_index]
        second = min(others, key=lambda i: abs(i - lane_index)) if others else lane_index
        self._stop_car(item, item.edge, lane_index, offset, (230, 60, 40, 255))
        if second != lane_index:
            self._stop_car(item, item.edge, second, max(1.0, offset - 5.0), (230, 60, 40, 255))
        item.blocking = len(indices) <= (2 if second != lane_index else 1)

    def remove(self, iid):
        item = self.items.pop(iid, None)
        if item is None:
            return False
        for undo in reversed(item.undo):
            try:
                undo()
            except Exception:
                pass
        self.rev += 1
        return True

    def clear(self):
        for iid in list(self.items):
            self.remove(iid)

    def expire(self, now):
        for iid, item in list(self.items.items()):
            if item.ends_at is not None and now >= item.ends_at:
                self.remove(iid)

    # ---- traffic lights ------------------------------------------------------
    def tls_apply(self, cmd):
        """Override one junction. An override is installed as a one-phase program logic:
        a bare setRedYellowGreenState is overwritten as soon as the running program
        switches phase."""
        tid = cmd['id']
        action = cmd['action']
        state = self.c.trafficlight.getRedYellowGreenState(tid)   # raises for unknown ids
        saved = self.tls.get(tid, {}).get('program') or self.c.trafficlight.getProgram(tid)
        if action == 'restore':
            self.c.trafficlight.setProgram(tid, saved)
            self.c.trafficlight.setPhase(tid, 0)   # back to the start of the cycle, not mid-red
            self.tls.pop(tid, None)
        elif action == 'program':
            self.c.trafficlight.setProgram(tid, cmd['value'])
            self.tls.pop(tid, None)
        elif action == 'phase':
            self.c.trafficlight.setPhase(tid, cmd['value'])
            self.tls.pop(tid, None)
        elif action == 'next':
            self.c.trafficlight.setPhase(tid, self.c.trafficlight.getPhase(tid) + 1)
            self.tls.pop(tid, None)
        else:
            mode = {'allred': 'r', 'off': 'O', 'amber': 'y'}[action]
            self.tls[tid] = {'mode': action, 'program': saved, 'n': len(state), 'flip': False}
            self._hold(tid, mode * len(state))
        self.rev += 1
        return {'type': 'tls_state', 'id': tid, 'mode': self.tls.get(tid, {}).get('mode', 'program')}

    def _hold(self, tid, state):
        light = self.c.trafficlight
        logic = light.Logic('override', 0, 0, [light.Phase(1e5, state)])
        light.setProgramLogic(tid, logic)

    def tick(self, now):
        """Amber blinking is not a SUMO model: the bridge flips the state itself.
        Blank ('O') links fall back to the junction's priority rules."""
        for tid, over in self.tls.items():
            if over['mode'] != 'amber':
                continue
            flip = int(now / AMBER_PERIOD) % 2 == 1
            if flip != over['flip']:
                over['flip'] = flip
                self._hold(tid, ('O' if flip else 'y') * over['n'])

    def overrides(self):
        return {tid: over['mode'] for tid, over in self.tls.items()}

    # ---- reporting -----------------------------------------------------------
    def snapshot(self, now):
        return [item.snapshot(now) for item in self.items.values()]

    def pick(self, point):
        """A click on the map -> what is there, for the control panel."""
        hit = self.index.nearest(point)
        if hit is None:
            raise ValueError('No road nearby')
        lid, offset, distance = hit
        edge_id, _, idx = lid.rpartition('_')
        edge = self.net.getEdge(edge_id)
        lanes = self.passenger_lanes(edge_id)
        node = edge.getToNode()
        # --tls.join merges junctions, so the programme id is the cluster's, not the node's.
        tid = node.getTLSID() if node.getType() == 'traffic_light' else None
        programs = []
        if tid:
            try:
                programs = [l.programID for l in
                            self.c.trafficlight.getAllProgramLogics(tid)]
            except Exception:
                programs = []
        position, heading = self.index.point_at(lid, offset)
        return {'type': 'picked', 'edge': edge_id, 'lane': lid, 'lane_index': int(idx),
                'lanes': len(lanes), 'pos': round(offset, 1), 'distance': round(distance, 1),
                'length': round(edge.getLength(), 1), 'name': edge.getName() or '',
                'speed_kmh': round(edge.getSpeed() * 3.6), 'p': [round(v, 2) for v in position],
                'heading': round(heading, 1), 'tls': tid, 'programs': programs}
