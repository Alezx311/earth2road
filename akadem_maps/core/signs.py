#!/usr/bin/env python3
"""Road signs derived from the SUMO network and the OSM snapshot.

Kyiv OSM has almost no traffic_sign nodes (7 in Академмістечко, 9 in Західний Київ for
80 km²), so none of this is an observed sign inventory. Every record says where it came
from:

    provenance = osm        the tag that decides the sign is in OSM (maxspeed, oneway,
                            highway=stop / give_way on the node)
    provenance = derived    it follows from the network topology netconvert built
                            (minor/major approach, junction type)

Speed-limit plates are emitted only where OSM carries maxspeed: ~84 % of the speeds in
the network are SUMO type defaults, and a 100 km/h plate on a residential street would be
a lie about Kyiv. Derived limits are still exported (value + provenance) for the HUD.

Runs inside the world build. The legacy standalone rebuild of an existing game/data
map (`tools/signs.py --map <id>`) lives in the tools wrapper, outside the package.
"""
import json
import math
import xml.etree.ElementTree as ET

import sumolib


SETBACK_STOP_LINE = 2.5   # m before the stop line
SETBACK_ENTRY = 12.0      # m after the junction, where an entry plate stands
LATERAL = 0.7             # m from the lane edge to the pole
PLATE_HEIGHT = 2.3        # m, plate centre above the road
MIN_EDGE_LENGTH = 15.0    # m; shorter approaches are junction stubs, not streets
MATCH_RADIUS = 20.0       # m, OSM node -> approach end

KINDS = ('speed_limit', 'give_way', 'stop', 'priority_road', 'oneway')
MINOR_STATES = ('m', 's', 'w')


def _norm(dx, dz):
    length = math.hypot(dx, dz) or 1.0
    return dx / length, dz / length


class LaneShapes:
    """The exported lane polylines (Godot space, final heights), keyed by lane id.

    Placing signs from these instead of from the SUMO shape means the plate sits on the
    same surface the player drives on, with no second height pipeline to keep in sync."""

    def __init__(self, lanes):
        self.shapes = {}
        for lane in lanes:
            points = lane['points']
            if len(points) < 2:
                continue
            offsets = [0.0]
            for a, b in zip(points, points[1:]):
                offsets.append(offsets[-1] + math.dist((a[0], a[2]), (b[0], b[2])))
            self.shapes[lane['id']] = (points, offsets, float(lane['width']))

    def at(self, lane_id, offset):
        """-> (point, forward direction, width) at an offset along the lane."""
        points, offsets, width = self.shapes[lane_id]
        offset = min(max(0.0, offset), offsets[-1])
        i = 0
        while i < len(offsets) - 2 and offsets[i + 1] < offset:
            i += 1
        a, b = points[i], points[i + 1]
        span = max(1e-6, offsets[i + 1] - offsets[i])
        t = min(1.0, max(0.0, (offset - offsets[i]) / span))
        point = [a[j] + (b[j] - a[j]) * t for j in range(3)]
        return point, _norm(b[0] - a[0], b[2] - a[2]), width

    def length(self, lane_id):
        return self.shapes[lane_id][1][-1]


def place(shapes, lane_id, offset, kind, value, provenance, source, edge_id):
    """A sign at the right-hand kerb, facing the driver who is approaching it."""
    point, (fx, fz), width = shapes.at(lane_id, offset)
    rx, rz = -fz, fx                                   # right of travel in Godot space
    side = width / 2 + LATERAL
    return {'kind': kind, 'value': value, 'lane': lane_id, 'edge': edge_id,
            'position': [round(point[0] + rx * side, 3), round(point[1] + PLATE_HEIGHT, 3),
                         round(point[2] + rz * side, 3)],
            'yaw': round(math.atan2(-fx, -fz), 4),
            'provenance': provenance, 'source': source}


def osm_facts(osm_path, net, offset):
    """What the OSM snapshot knows: which ways carry maxspeed or oneway, and where the
    stop / give-way nodes are (in Godot coordinates, so they can be matched to a lane)."""
    facts = {'maxspeed': set(), 'oneway': set(), 'nodes': []}
    ox, oy = offset
    for event, element in ET.iterparse(str(osm_path), events=('end',)):
        if element.tag == 'way':
            tags = {t.get('k'): t.get('v') for t in element.findall('tag')}
            if 'maxspeed' in tags:
                facts['maxspeed'].add(element.get('id'))
            if tags.get('oneway') in ('yes', '-1', 'true', '1'):
                facts['oneway'].add(element.get('id'))
        elif element.tag == 'node':
            tags = {t.get('k'): t.get('v') for t in element.findall('tag')}
            if tags.get('highway') in ('stop', 'give_way'):
                x, y = net.convertLonLat2XY(float(element.get('lon')), float(element.get('lat')))
                facts['nodes'].append((tags['highway'], x - ox, -(y - oy)))
        if element.tag in ('way', 'node', 'relation'):
            element.clear()
    return facts


def _origs(edge):
    return set(edge.getLanes()[0].getParam('origId', '').split())


def _approach_lanes(edge):
    return [l for l in edge.getLanes() if l.allows('passenger')]


def _is_minor(lane):
    conns = lane.getOutgoing()
    return bool(conns) and all(c.getState() in MINOR_STATES for c in conns)


def derive(net, lanes, osm, counts=None):
    """-> sign records for the whole map."""
    shapes = LaneShapes(lanes)
    service = {lane['id'] for lane in lanes if lane.get('service')}
    records = []

    def keep(edge):
        if edge.getFunction() != '' or edge.getLength() < MIN_EDGE_LENGTH:
            return None
        approach = _approach_lanes(edge)
        if not approach:
            return None
        lane = approach[0]                              # rightmost lane that allows cars
        lid = lane.getID()
        if lid not in shapes.shapes or lid in service:
            return None
        return lane

    for edge in net.getEdges():
        lane = keep(edge)
        if lane is None:
            continue
        lid = lane.getID()
        length = shapes.length(lid)
        origs = _origs(edge)
        eid = edge.getID()

        # --- speed limit, where a driver can arrive from a different limit ------
        incoming = [e for e in edge.getFromNode().getIncoming() if e.getFunction() == '']
        if not incoming or any(abs(e.getSpeed() - edge.getSpeed()) > 0.6 for e in incoming):
            value = int(round(edge.getSpeed() * 3.6 / 5.0) * 5)
            backed = bool(origs & osm['maxspeed'])
            if backed and 5 <= value <= 130:
                records.append(place(shapes, lid, min(SETBACK_ENTRY, length / 2), 'speed_limit',
                                     value, 'osm', 'osm:maxspeed', eid))

        # --- one-way, at the entry ------------------------------------------
        if origs & osm['oneway'] and length > 30:
            records.append(place(shapes, lid, min(SETBACK_ENTRY + 4, length / 2), 'oneway',
                                 None, 'osm', 'osm:oneway', eid))

        # --- priority at the far junction ------------------------------------
        node = edge.getToNode()
        if node.getType() != 'priority':
            continue
        approaches = [e for e in node.getIncoming() if e.getFunction() == '']
        minors = [e for e in approaches if any(_is_minor(l) for l in _approach_lanes(e))]
        if not minors or len(approaches) < 2:
            continue
        # A priority plate belongs where a real street gives way, not at every yard exit:
        # otherwise the district ends up with a thousand of them.
        street_minor = [e for e in minors
                        if any(l.getID() not in service for l in _approach_lanes(e))]
        offset = max(1.0, length - SETBACK_STOP_LINE)
        if any(_is_minor(l) for l in _approach_lanes(edge)):
            records.append(place(shapes, lid, offset, 'give_way', None, 'derived',
                                 'net:minor_link', eid))
        elif street_minor and len(minors) < len(approaches):
            records.append(place(shapes, lid, offset, 'priority_road', None, 'derived',
                                 'net:major_link', eid))

    _upgrade_from_osm_nodes(records, osm['nodes'])
    if counts is not None:
        counts['signs_total'] = len(records)
        for kind in KINDS:
            counts[f'signs_{kind}'] = sum(1 for r in records if r['kind'] == kind)
        for source in ('osm', 'derived'):
            counts[f'signs_{source}'] = sum(1 for r in records if r['provenance'] == source)
    return records


def _upgrade_from_osm_nodes(records, nodes):
    """An OSM highway=stop / give_way node near a derived give-way sign means the sign is
    observed, not guessed: a stop node also turns it into a stop sign."""
    yields = [r for r in records if r['kind'] in ('give_way', 'priority_road')]
    for tag, x, z in nodes:
        near = [r for r in yields
                if math.dist((x, z), (r['position'][0], r['position'][2])) < MATCH_RADIUS]
        if not near:
            continue
        closest = min(near, key=lambda r: math.dist((x, z), (r['position'][0], r['position'][2])))
        closest['kind'] = 'stop' if tag == 'stop' else 'give_way'
        closest['provenance'] = 'osm'
        closest['source'] = f'osm:highway={tag}'


def traffic_lights(net, point_of):
    """Traffic-light programs for the control panel. netconvert wrote these phases from
    its defaults; nobody measured them in Kyiv, hence provenance 'derived'."""
    out = []
    for tls in net.getTrafficLights():
        programs = {}
        for pid, logic in tls.getPrograms().items():
            programs[pid] = [[float(p.duration), p.state] for p in logic.getPhases()]
        heads = []
        for incoming, outgoing, index in tls.getConnections():
            if incoming.allows('passenger'):
                heads.append(incoming.getShape()[-1])
        if not heads:
            continue
        x = sum(h[0] for h in heads) / len(heads)
        y = sum(h[1] for h in heads) / len(heads)
        out.append({'id': tls.getID(), 'position': point_of(x, y), 'programs': programs,
                    'default_program': next(iter(programs), '0'), 'heads': len(heads),
                    'provenance': 'derived', 'source': 'netconvert --tls.guess-signals defaults'})
    return out
