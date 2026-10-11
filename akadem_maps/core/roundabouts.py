"""One lane count around each roundabout (playtest 2026-10-06, note 3).

OSM often tags a ring piecewise (none/none/2/2/4 on Kholmska Square), so the drawn
ring narrows and widens between approaches. Before netconvert every way of a ring
gets the same ``lanes``: the length-weighted mean of the tagged pieces, else the
widest approach (1..3). A derived correction; the report keeps the original tags.
"""
import math

RING = ('roundabout', 'circular')


def _length(coords):
    total = 0.0
    for (lon0, lat0), (lon1, lat1) in zip(coords, coords[1:]):
        k = math.cos(math.radians((lat0+lat1)/2))
        total += math.hypot((lon1-lon0)*k, lat1-lat0)*111_320
    return total


def _lanes(tags):
    try:
        n = int(str(tags.get('lanes', '')).split(';')[0])
    except ValueError:
        return None
    if tags.get('oneway') in ('yes', '1', 'true', '-1') or tags.get('junction') in RING:
        return n
    return max(1, n//2)


def unify(root, nodes, drivable):
    """Set one ``lanes`` value on every way of each ring; returns a per-ring report."""
    ways = [w for w in root.findall('way')]
    tag = lambda w: {t.get('k'): t.get('v') for t in w.findall('tag')}
    ring_ways = [w for w in ways if tag(w).get('junction') in RING and drivable(tag(w))]
    refs = {w.get('id'): [n.get('ref') for n in w.findall('nd')] for w in ring_ways}
    parent = {w.get('id'): w.get('id') for w in ring_ways}
    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    by_node = {}
    for wid, rs in refs.items():
        for r in rs:
            by_node.setdefault(r, []).append(wid)
    for ids in by_node.values():
        for other in ids[1:]:
            parent[find(other)] = find(ids[0])
    groups = {}
    for w in ring_ways:
        groups.setdefault(find(w.get('id')), []).append(w)
    report = []
    for members in groups.values():
        ring_nodes = {r for w in members for r in refs[w.get('id')]}
        tagged = [(n, _length([nodes[r] for r in refs[w.get('id')] if r in nodes]))
                  for w in members if (n := _lanes(tag(w))) is not None]
        weight = sum(length for _, length in tagged)
        if tagged and weight > 0:
            lanes = max(1, math.floor(sum(n*length for n, length in tagged)/weight + 0.5))
            source = 'osm_ring_weighted_mean'
        else:
            approach = [n for w in ways if w not in members and drivable(tag(w))
                        and ring_nodes & {nd.get('ref') for nd in w.findall('nd')}
                        and (n := _lanes(tag(w))) is not None]
            lanes = min(3, max([1, *approach]))
            source = 'derived_widest_approach'
        before = {w.get('id'): tag(w).get('lanes') for w in members}
        if len(set(before.values())) == 1 and next(iter(before.values())) == str(lanes):
            continue
        for w in members:
            for t in list(w.findall('tag')):
                if t.get('k') in ('lanes', 'lanes:forward', 'lanes:backward', 'turn:lanes'):
                    w.remove(t)
            el = w.makeelement('tag', {'k': 'lanes', 'v': str(lanes)})
            w.append(el)
        report.append({'ways': sorted(before), 'osm_lanes': before, 'lanes': lanes, 'source': source})
    return report
