"""Source road topology and its explicit binding to the SUMO lane network.

The source graph uses node identity, never geometric crossings. Coordinates in
the effective graph are SUMO east/north metres; widths are SUMO-derived, not a
claim that an OSM width was surveyed. All output ordering is deterministic.
"""
from collections import Counter, defaultdict
import math

from .surface_audit import structure


def source_graph(root, drivable, *, synthetic=False):
    nodes = {n.get('id'): [float(n.get('lon')), float(n.get('lat'))]
             for n in root.findall('node')}
    ways, degree = {}, Counter()
    for w in sorted(root.findall('way'), key=lambda w: w.get('id')):
        tags = {t.get('k'): t.get('v') for t in w.findall('tag')}
        if not drivable(tags):
            continue
        refs = [r.get('ref') for r in w.findall('nd')]
        if len(refs) < 2 or any(r not in nodes for r in refs):
            continue
        ways[w.get('id')] = {'nodes': refs, 'tags': tags,
                            'structure': list(structure(tags))}
        for a, b in zip(refs, refs[1:]):
            if a != b:
                degree[a] += 1
                degree[b] += 1
    # A way boundary preserves changes of profile even at a degree-two node.
    breaks = {n for n, d in degree.items() if d != 2}
    breaks.update(n for w in ways.values() for n in (w['nodes'][0], w['nodes'][-1]))
    segments = []
    for wid, way in ways.items():
        refs, start = way['nodes'], 0
        for i in range(1, len(refs)):
            if refs[i] in breaks or i == len(refs)-1:
                if i > start:
                    segments.append({'id': f'{wid}:{start}:{i}', 'way': wid,
                                     'from': refs[start], 'to': refs[i],
                                     'nodes': refs[start:i+1]})
                start = i
    return {'version': 1, 'provenance': 'synthetic' if synthetic else 'osm',
            'coordinates': 'longitude, latitude',
            'nodes': {n: nodes[n] for n in sorted(degree)},
            'ways': ways, 'segments': segments}


def _unit(a, b):
    dx, dy = b[0]-a[0], b[1]-a[1]
    length = math.hypot(dx, dy)
    return (dx/length, dy/length) if length > 1e-9 else (0., 0.)


def classify(arms, *, roundabout=False):
    if roundabout:
        return 'roundabout'
    n = len(arms)
    if n <= 2:
        return ('isolated', 'endcap', 'transition')[n]
    if n > 4:
        return 'complex'
    if n == 4:
        return 'X'
    incoming = sum(bool(a['incoming']) for a in arms)
    outgoing = sum(bool(a['outgoing']) for a in arms)
    if incoming == 2 and outgoing == 1 and all(not (a['incoming'] and a['outgoing']) for a in arms):
        return 'merge'
    if incoming == 1 and outgoing == 2 and all(not (a['incoming'] and a['outgoing']) for a in arms):
        return 'split'
    opposite = min(sum(x*y for x, y in zip(a['direction'], b['direction']))
                   for i, a in enumerate(arms) for b in arms[i+1:])
    return 'T' if opposite <= math.cos(math.radians(150)) else 'Y'


def bind(source, net, strips):
    """Group opposite directions only when both their source ways and end pair agree."""
    effective = []
    for node in sorted(net.getNodes(), key=lambda n: n.getID()):
        groups = defaultdict(list)
        for edge in sorted(set(node.getIncoming()+node.getOutgoing()), key=lambda e: e.getID()):
            if edge.getFunction():
                continue
            lanes = [l for l in edge.getLanes() if l.getID() in strips]
            if not lanes:
                continue
            ids = sorted({w for l in lanes for w in l.getParam('origId', '').split()})
            other = edge.getToNode() if edge.getFromNode() == node else edge.getFromNode()
            # Physical divided carriageways have different source ways even if
            # SUMO joins both ends. They must not be collapsed into one mouth.
            key = (other.getID(), tuple(ids) if ids else (edge.getID().lstrip('-'),))
            groups[key].append((edge, lanes))
        arms = []
        for key, members in sorted(groups.items()):
            rows, incoming, outgoing, dirs = [], [], [], []
            for edge, lanes in members:
                is_in = edge.getToNode() == node
                for lane in lanes:
                    pts = strips[lane.getID()]['points']
                    pts = list(reversed(pts)) if is_in else pts
                    direction = next((_unit(pts[0], p) for p in pts[1:]
                                      if math.dist(pts[0][:2], p[:2]) > .5), (0., 0.))
                    dirs.append(direction)
                    rows.append({'lane': lane.getID(), 'incoming': is_in,
                                 'width': lane.getWidth(), 'edge': edge.getID()})
                    (incoming if is_in else outgoing).append(lane.getID())
            dx, dy = (sum(v[i] for v in dirs) for i in (0, 1))
            d = math.hypot(dx, dy) or 1.
            wids = sorted({w for e, ls in members for l in ls for w in l.getParam('origId', '').split()})
            arms.append({'id': min(e.getID() for e, _ in members), 'other': key[0],
                         'ways': wids, 'lanes': rows, 'incoming': sorted(incoming),
                         'outgoing': sorted(outgoing), 'direction': [dx/d, dy/d],
                         'width': sum(r['width'] for r in rows),
                         'width_provenance': 'sumo-derived',
                         'source_tags': {w: source['ways'][w]['tags'] for w in wids if w in source['ways']}})
        arms.sort(key=lambda a: (math.atan2(a['direction'][1], a['direction'][0]), a['id']))
        wids = sorted({w for a in arms for w in a['ways']})
        levels = sorted({tuple(source['ways'][w]['structure']) for w in wids if w in source['ways']})
        roundabout = any(source['ways'].get(w, {}).get('tags', {}).get('junction') == 'roundabout' for w in wids)
        effective.append({'id': node.getID(), 'position': list(node.getCoord()), 'arms': arms,
                          'family': classify(arms, roundabout=roundabout), 'levels': [list(s) for s in levels],
                          'source_ways': wids, 'unmapped_ways': [w for w in wids if w not in source['ways']],
                          'source_nodes': sorted({n for w in wids if w in source['ways'] for n in source['ways'][w]['nodes']}),
                          'provenance': 'derived'})
    return {**source, 'effective_coordinates': 'SUMO x east, y north, z up; metres',
            'junctions': effective}
