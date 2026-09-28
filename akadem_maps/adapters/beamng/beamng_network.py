"""Native BeamNG navigation and signals from the cached SUMO topology.

SUMO is a build-time data source only. No simulator bridge runs in BeamNG.

Navigation is expressed as DecalRoad objects, the construct the engine builds its
own navigation graph from. An earlier revision emitted one BeamNGWaypoint per lane
vertex; at 22 494 objects the game aborted level load with a Lua stack overflow in
map.onAddWaypoint, leaving most of the graph and every traffic signal unbound.
One road per OSM way carries the same lane counts, directions and speed limits in
roughly a thousand objects, and lets the engine merge junctions itself.
"""
from collections import defaultdict
import hashlib
import math
import xml.etree.ElementTree as ET

from akadem_maps.adapters.beamng.beamng_geometry import beam_point, normal, sub

# SUMO highway.* type -> AI drivability. Service roads and alleys stay usable but
# unattractive, so traffic prefers the real street grid.
DRIVABILITY = {'highway.trunk': 1.0, 'highway.primary': 1.0, 'highway.secondary': 0.95,
               'highway.secondary_link': 0.9, 'highway.tertiary': 0.9,
               'highway.residential': 0.75, 'highway.unclassified': 0.7,
               'highway.living_street': 0.6, 'highway.service': 0.4}
DEFAULT_DRIVABILITY = 0.5
# A corridor map cuts every side street at its outline. Those dead ends stay in the
# graph (the surface is there) but are made unattractive, so traffic keeps to roads that
# lead somewhere instead of driving to the edge of the map and turning round.
BORDER_STUB_M = 30.0
BORDER_DRIVABILITY = 0.1


def stable_id(prefix, key):
    return prefix + '_' + hashlib.sha256(str(key).encode('utf8')).hexdigest()[:20]


class Elevation:
    """Nearest-point height lookup over the snapshot lane geometry (BeamNG XY).

    Global 2D nearest is only a fallback. Grade-separated roads share XY, so a
    DecalRoad must sample Z from its own SUMO edge (see profile_height).
    """

    CELL = 20.0

    def __init__(self, lanes):
        self.cells = defaultdict(list)
        for lane in lanes.values():
            for point in lane['points']:
                x, y, z = beam_point(point)
                self.cells[(int(x // self.CELL), int(y // self.CELL))].append((x, y, z))
        if not self.cells:
            raise ValueError('No lane geometry to derive road heights from')

    def at(self, x, y):
        cx, cy = int(x // self.CELL), int(y // self.CELL)
        for ring in range(0, 12):
            best, distance = None, None
            for ix in range(cx - ring, cx + ring + 1):
                for iy in range(cy - ring, cy + ring + 1):
                    if ring and max(abs(ix - cx), abs(iy - cy)) != ring:
                        continue
                    for px, py, pz in self.cells.get((ix, iy), ()):
                        d = (px - x) ** 2 + (py - y) ** 2
                        if distance is None or d < distance:
                            best, distance = pz, d
            if best is not None:
                return best
        raise ValueError(f'No height sample near ({x:.1f}, {y:.1f})')


def edge_profile(edge, lanes_by_id):
    """Longest drivable lane of this edge, in BeamNG XYZ. Empty if the snapshot has none."""
    best = []
    for lane in edge['lanes']:
        rec = lanes_by_id.get(lane.get('id'))
        if rec and len(rec['points']) > len(best):
            best = [beam_point(p) for p in rec['points']]
    return best


def profile_height(profile, x, y):
    """Z of the closest XY point on this edge's own 3D polyline.

    Junction centres sit a few metres past the trimmed lane; they still take this
    road's grade. A nearby overpass must not win on 2D distance.
    """
    if not profile:
        return None
    if len(profile) == 1:
        return profile[0][2]
    best_d, best_z = None, None
    for a, b in zip(profile, profile[1:]):
        dx, dy = b[0] - a[0], b[1] - a[1]
        length2 = dx * dx + dy * dy
        if length2 < 1e-12:
            t = 0.0
        else:
            t = max(0.0, min(1.0, ((x - a[0]) * dx + (y - a[1]) * dy) / length2))
        px = a[0] + t * dx
        py = a[1] + t * dy
        d = (px - x) ** 2 + (py - y) ** 2
        z = a[2] + t * (b[2] - a[2])
        if best_d is None or d < best_d:
            best_d, best_z = d, z
    return best_z


def _allowed(lane):
    allow = lane.get('allow')
    disallow = lane.get('disallow', '').split()
    if allow is not None and not {'passenger', 'all'} & set(allow.split()):
        return False
    return 'passenger' not in disallow and 'all' not in disallow


def _shape(text, offset):
    points = []
    for pair in text.split():
        sx, sy = (float(v) for v in pair.split(','))
        points.append((sx - offset[0], sy - offset[1]))
    return points


def _dedupe(points, epsilon=0.05):
    result = []
    for p in points:
        if not result or math.dist(p[:2], result[-1][:2]) > epsilon:
            result.append(p)
    return result


def ai_spacing(points, width):
    """Thin a road polyline so consecutive AI nodes cannot overlap each other.

    BeamNG gives every DecalRoad node a navigation radius of half the road width
    and then runs mergeOverlappingNodes, which welds any two nodes closer than the
    larger radius. A 21 m carriageway described every 5 m therefore collapses into
    a single graph node, and the leftover multi-edges crash map.lua's edgeCompare
    (it compares the merged edge's missing `lanes` against a string). Endpoints are
    kept exactly so neighbouring roads still weld into one junction node.
    """
    if len(points) < 3:
        return points
    step = max(2.0, width * 0.625)
    result = [points[0]]
    for p in points[1:-1]:
        if math.dist(p[:2], result[-1][:2]) >= step:
            result.append(p)
    while len(result) > 1 and math.dist(points[-1][:2], result[-1][:2]) < step:
        result.pop()
    result.append(points[-1])
    return result


def carriageway_pairs(edges):
    """Match each one-way edge with the carriageway running the other way.

    SUMO negates the id of a reversed way, but it also splits ways at junctions and
    numbers the halves independently, so `1074511033#0` and `-1074511033#1` are the
    two sides of one street while neither is the other's negation. Unpaired, they
    become two DecalRoads between the same two junctions, which is the chord that
    kills the engine's navgraph load. Pairing is by junction pair, preferring the
    same OSM way and then the closest length.
    """
    def length(eid):
        shape = edges[eid]['shape']
        return sum(math.dist(a, b) for a, b in zip(shape, shape[1:]))

    pairs = {}
    for eid in sorted(edges):
        reverse = eid[1:] if eid.startswith('-') else '-' + eid
        back = edges.get(reverse)
        if back and back['from'] == edges[eid]['to'] and back['to'] == edges[eid]['from']:
            pairs[eid] = reverse
    facing = defaultdict(list)
    for eid in sorted(edges):
        if eid not in pairs:
            facing[edges[eid]['from'], edges[eid]['to']].append(eid)
    for (start, end), forwards in sorted(facing.items()):
        if start == end:
            continue
        backs = facing.get((end, start))
        if not backs:
            continue
        for eid in forwards:
            if eid in pairs:
                continue
            base = eid.lstrip('-').split('#')[0]
            candidates = [c for c in backs if c not in pairs]
            if not candidates:
                break
            best = min(candidates, key=lambda c: (c.lstrip('-').split('#')[0] != base,
                                                  abs(length(c) - length(eid)), c))
            pairs[eid] = best
            pairs[best] = eid
    return pairs


def _inside(point, ring):
    x, y = point
    inside = False
    for (ax, ay), (bx, by) in zip(ring, ring[1:] + ring[:1]):
        if (ay > y) != (by > y) and x < ax + (y - ay) * (bx - ax) / (by - ay):
            inside = not inside
    return inside


def _ring_distance(point, ring):
    best = math.inf
    for a, b in zip(ring, ring[1:] + ring[:1]):
        dx, dy = b[0] - a[0], b[1] - a[1]
        den = dx * dx + dy * dy
        t = 0.0 if den == 0 else max(0.0, min(1.0, ((point[0] - a[0]) * dx + (point[1] - a[1]) * dy) / den))
        best = min(best, math.hypot(point[0] - a[0] - t * dx, point[1] - a[1] - t * dy))
    return best


def border_stubs(edges, junctions, ring):
    """Dead-end junctions outside the map outline or within BORDER_STUB_M of it."""
    neighbours = defaultdict(set)
    for edge in edges.values():
        neighbours[edge['from']].add(edge['to'])
        neighbours[edge['to']].add(edge['from'])
    return {j for j, near in neighbours.items() if len(near) == 1 and
            (not _inside(junctions[j], ring) or _ring_distance(junctions[j], ring) <= BORDER_STUB_M)}


def road_network(index, network_path):
    """DecalRoads for the engine navigation graph, plus the drivable lane table."""
    root = ET.parse(network_path).getroot()
    offset = index['offset']
    lanes = {v['id']: v for v in index['lanes'] if len(v['points']) > 1}
    junctions = {j.get('id'): (float(j.get('x')) - offset[0], float(j.get('y')) - offset[1])
                 for j in root.findall('junction')}

    edges = {}
    for edge in root.findall('edge'):
        if edge.get('function') is not None:
            continue
        drivable = [lane for lane in edge.findall('lane') if _allowed(lane) and lane.get('id') in lanes]
        if not drivable:
            continue
        edges[edge.get('id')] = {
            'from': edge.get('from'), 'to': edge.get('to'), 'type': edge.get('type'),
            # SUMO omits shape on straight edges. They are still real roads.
            'shape': (_shape(edge.get('shape'), offset) if edge.get('shape') else
                      [junctions[edge.get('from')], junctions[edge.get('to')]]), 'lanes': drivable,
            'width': sum(float(lane.get('width', 3.2)) for lane in drivable),
            'speed': max(float(lane.get('speed', 13.9)) for lane in drivable)}

    drivable_lanes = {lane.get('id'): lanes[lane.get('id')]
                      for edge in edges.values() for lane in edge['lanes']}
    elevation = Elevation(drivable_lanes)

    objects, seen, stats = [], set(), defaultdict(int)
    pairing = carriageway_pairs(edges)
    # Map outline (corridor maps only), Godot [x, y, z] -> the XY frame used here.
    ring = [(p[0], -p[2]) for p in index.get('area', [])][:-1]
    stubs = border_stubs(edges, junctions, ring) if ring else set()
    occupied = set()
    # When two roads still share a junction pair only one can stay in the graph, so
    # the wider and more drivable street is offered the slot before an alley.
    order = sorted(edges, key=lambda e: (-edges[e]['width'],
                                         -DRIVABILITY.get(edges[e]['type'], DEFAULT_DRIVABILITY), e))
    for eid in order:
        if eid in seen:
            continue
        reverse = pairing.get(eid)
        back = edges.get(reverse)
        forward = edges[eid]
        seen.add(eid)
        if back:
            seen.add(reverse)
            if eid.startswith('-'):
                # Draw along the positive way so node order follows the OSM direction.
                forward, back, eid = back, forward, reverse
        # A road that returns to the junction it left closes a cycle of degree-2 nodes;
        # see the duplicate check below for why the engine cannot survive that.
        if forward['from'] == forward['to']:
            stats['roads_self_loop_skipped'] += 1
            continue
        # SUMO trims each edge at the junction boundary; ending on the junction centre
        # lets the engine merge the approaches into one intersection node.
        path = [junctions[forward['from']]] + forward['shape'] + [junctions[forward['to']]]
        path = _dedupe(path)
        if len(path) < 2:
            stats['roads_degenerate'] += 1
            continue
        width = forward['width'] + (back['width'] if back else 0)
        profile = edge_profile(forward, lanes)
        if not profile and back:
            profile = edge_profile(back, lanes)
        path = ai_spacing(path, max(width, 3.0))
        nodes = []
        for x, y in path:
            z = profile_height(profile, x, y)
            if z is None:
                z = elevation.at(x, y)
                stats['heights_fallback'] += 1
            nodes.append([round(x, 3), round(y, 3), round(z, 3), round(max(width, 3.0), 2)])
        # Two roads whose ends weld to the same pair of graph nodes leave map.lua a
        # chord across a chain of degree-2 nodes. optimizeNodes then builds the merged
        # edge with no `lanes` field and edgeCompare dies comparing nil with a string,
        # aborting the navgraph load for the whole level. The engine welds in 3D, so a
        # flyover over the same junctions is a different pair and stays. Only the
        # navigation road is dropped; the visible surface is a separate mesh.
        ends = frozenset((tuple(round(v) for v in nodes[0][:3]), tuple(round(v) for v in nodes[-1][:3])))
        if len(ends) < 2 or ends in occupied:
            stats['roads_duplicate_skipped'] += 1
            continue
        occupied.add(ends)
        name = stable_id('kyiv_road', eid)
        drivability = DRIVABILITY.get(forward['type'], DEFAULT_DRIVABILITY)
        if forward['from'] in stubs or forward['to'] in stubs:
            drivability = min(drivability, BORDER_DRIVABILITY)
            stats['roads_border_stub'] += 1
        objects.append({
            'name': name, 'class': 'DecalRoad', '__parent': 'KyivNavigation',
            'position': nodes[0][:3], 'nodes': nodes,
            'material': 'kyiv_road_invisible', 'renderPriority': 20,
            'drivability': drivability,
            'speedLimit': round(max(forward['speed'], back['speed'] if back else 0), 2),
            'autoLanes': False, 'lanesRight': len(forward['lanes']),
            'lanesLeft': len(back['lanes']) if back else 0,
            # Projected decal subdivisions can jump to an overpass or scenery,
            # inflating radii and collapsing an entire district during nav merging.
            # AI must use the exported, grade-aware nodes and their explicit widths.
            'oneWay': back is None, 'improvedSpline': True, 'useSubdivisions': False,
            'autoJunction': True,
            'breakAngle': 3, 'textureLength': 50, 'distanceFade': [0, 0],
            # Without a TerrainBlock the engine refuses to project a decal road onto
            # nothing and warns it will crash, so the road is projected onto the meshes.
            'overObjects': True})
        stats['roads'] += 1
        stats['roads_two_way' if back else 'roads_one_way'] += 1
        stats['road_nodes'] += len(nodes)
    if not objects:
        raise ValueError('SUMO network produced no drivable roads')
    location = root.find('location').attrib
    return objects, drivable_lanes, location, dict(stats), elevation


def road_height_audit(roads, tiles, cell=20.0):
    """Compare DecalRoad node Z to the nearest visual road-strip sample (BeamNG XY).

    Large deltas mean the driving surface floats above (or sinks below) the asphalt
    mesh. Does not fail the export; counts go into the manifest.
    """
    samples = defaultdict(list)
    for _tileid, tile in tiles:
        for road in tile.get('road_strips', []):
            for point in road.get('points', []):
                x, y, z = beam_point(point)
                samples[(int(x // cell), int(y // cell))].append((x, y, z))
    n = over_5 = over_20 = over_50 = over_2m = 0
    max_abs = 0.0
    worst = None
    if not samples:
        return {'nodes': 0, 'over_5cm': 0, 'over_20cm': 0, 'over_50cm': 0, 'over_2m': 0,
                'max_abs_m': 0.0, 'worst': None, 'unmatched': 0}
    unmatched = 0
    for road in roads:
        for node in road['nodes']:
            x, y, z = node[0], node[1], node[2]
            cx, cy = int(x // cell), int(y // cell)
            best, distance = None, None
            for ring in range(0, 8):
                for ix in range(cx - ring, cx + ring + 1):
                    for iy in range(cy - ring, cy + ring + 1):
                        if ring and max(abs(ix - cx), abs(iy - cy)) != ring:
                            continue
                        for px, py, pz in samples.get((ix, iy), ()):
                            d = (px - x) ** 2 + (py - y) ** 2
                            if distance is None or d < distance:
                                best, distance = pz, d
                if best is not None:
                    break
            n += 1
            if best is None:
                unmatched += 1
                continue
            delta = abs(z - best)
            max_abs = max(max_abs, delta)
            if delta >= 0.05:
                over_5 += 1
            if delta >= 0.20:
                over_20 += 1
            if delta >= 0.50:
                over_50 += 1
            if delta >= 2.0:
                over_2m += 1
            if worst is None or delta > worst['delta']:
                worst = {'delta': round(delta, 3), 'decal': [round(x, 2), round(y, 2), round(z, 3)],
                         'mesh': round(best, 3), 'road': road['name']}
    return {'nodes': n, 'over_5cm': over_5, 'over_20cm': over_20, 'over_50cm': over_50,
            'over_2m': over_2m, 'max_abs_m': round(max_abs, 3), 'worst': worst,
            'unmatched': unmatched}


def signals(index, lanes):
    """All controllers share a full SUMO cycle and start concurrently.

    Multiple turn heads on the same lane become one conservative lane signal:
    green only when all movements on that lane are green. This loses permissive
    turns, never silently permits a red movement. The loss is audited.
    """
    result = {'instances': [], 'controllers': [], 'sequences': []}
    by_tls = defaultdict(lambda: defaultdict(list))
    for signal in index.get('signals', []):
        if signal['lane'] in lanes:
            by_tls[signal['tls']][signal['lane']].append(signal)
    next_id = 1
    audit = []
    for tls in sorted(index.get('tls', []), key=lambda t: t['id']):
        grouped = by_tls[tls['id']]
        if not grouped:
            continue
        cycle = tls['programs'][tls['default_program']]
        seqid = next_id
        next_id += 1
        controller_ids = []
        for lane_id, heads in sorted(grouped.items()):
            states = []
            reduced = False
            for duration, state in cycle:
                colors = [state[h['index']].lower() for h in heads]
                reduced |= len(set(colors)) > 1
                color = 'greenTrafficLight' if all(c == 'g' for c in colors) else (
                    'yellowTrafficLight' if all(c in 'gy' for c in colors) and 'y' in colors else 'redTrafficLight')
                if not math.isfinite(duration) or duration <= 0:
                    raise ValueError('Invalid signal phase duration')
                if states and states[-1]['state'] == color:
                    states[-1]['duration'] += duration
                else:
                    states.append({'state': color, 'duration': duration})
            if not any(s['state'] == 'greenTrafficLight' for s in states):
                audit.append({'lane': lane_id, 'reason': 'no common green; signal omitted'})
                continue
            cid = next_id
            iid = next_id + 1
            next_id += 2
            controller_ids.append(cid)
            name = stable_id('kyiv_signal', lane_id)
            result['controllers'].append({'id': cid, 'name': name + '_controller', 'type': 'lightsBasic',
                                          'isSimple': False, 'defaultIndex': len(states), 'states': states})
            pts = [beam_point(p) for p in lanes[lane_id]['points']]
            result['instances'].append({'id': iid, 'name': name, 'controllerId': cid, 'sequenceId': seqid,
                                        'pos': beam_point(heads[0]['position']), 'dir': normal(sub(pts[-1], pts[-2])),
                                        'group': stable_id('junction', tls['id']), 'startDisabled': False})
            if reduced:
                audit.append({'lane': lane_id, 'reason': 'mixed turn heads reduced to common green'})
        if not controller_ids:
            continue
        result['sequences'].append({'id': seqid, 'name': stable_id('cycle', tls['id']),
                                    'startTime': 0, 'startDisabled': False, 'ignoreTimer': False,
                                    'phases': [{'controllerIds': controller_ids, 'autoReset': True,
                                                'totalDuration': sum(p[0] for p in cycle)}]})
    return result, audit
