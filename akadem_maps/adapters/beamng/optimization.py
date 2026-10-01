"""Conservative, deterministic mesh reduction and export measurements."""
from collections import Counter, defaultdict
from time import perf_counter

from .beamng_geometry import cross, sub, triangulate


def simplify_ground(triangles, tolerance=.05):
    """Remove independent interior vertex fans, keeping every boundary vertex.

    A fan is replaced only if it is a simple heightfield disk and all of its
    vertices lie in a slab <= tolerance thick around one plane. Both old and
    new linear interpolants lie in that same slab everywhere, bounding their
    vertical difference without sampling. Tile/material/hole edges stay exact.
    Only original boundary vertices are used; uncertain topology is retained.
    """
    faces = [tuple(tuple(p) for p in t) for t in triangles]
    incident = defaultdict(list)
    edges = Counter()
    for i, tri in enumerate(faces):
        for p in tri:
            incident[p].append(i)
        for a, b in zip(tri, tri[1:]+tri[:1]):
            edges[tuple(sorted((a,b)))] += 1
    fixed = {p for edge, count in edges.items() if count != 2 for p in edge}
    removed, replacement, blocked = set(), [], set()
    worst = 0.
    for centre, ids in sorted(incident.items()):
        if centre in fixed or centre in blocked or not 3 <= len(ids) <= 12:
            continue
        ring_edges = []
        for i in ids:
            other = [p for p in faces[i] if p != centre]
            if len(other) != 2:
                break
            ring_edges.append(other)
        else:
            neighbours = defaultdict(list)
            for a,b in ring_edges:
                neighbours[a].append(b); neighbours[b].append(a)
            if any(len(v) != 2 for v in neighbours.values()):
                continue
            start = min(neighbours)
            ring, prev, cur = [], None, start
            for _ in range(len(neighbours)):
                ring.append(cur)
                nxt = next((p for p in sorted(neighbours[cur]) if p != prev), None)
                prev, cur = cur, nxt
                if cur == start:
                    break
            if cur != start or len(ring) != len(neighbours):
                continue
            # Select the largest projected face to avoid unstable near-vertical planes.
            tri = max((faces[i] for i in ids), key=lambda t: abs(cross(sub(t[1],t[0]),sub(t[2],t[0]))[2]))
            a,b,c = tri
            n = cross(sub(b,a),sub(c,a))
            if abs(n[2]) < 1e-9:
                continue
            residual = [p[2] - (a[2]-(n[0]*(p[0]-a[0])+n[1]*(p[1]-a[1]))/n[2]) for p in [centre,*ring]]
            bound = max(residual)-min(residual)
            if bound > tolerance-1e-8:
                continue
            from shapely.geometry import Polygon, Point
            pg = Polygon([p[:2] for p in ring])
            if not pg.is_valid or not pg.contains(Point(centre[:2])):
                continue
            old_area = sum(abs(cross(sub(faces[i][1],faces[i][0]),sub(faces[i][2],faces[i][0]))[2])/2 for i in ids)
            if abs(pg.area-old_area) > max(1e-8, old_area*1e-10):
                continue
            try:
                new = triangulate(ring)
            except ValueError:
                continue
            # Ear clipping may discard collinear boundary points. Reject that case:
            # keeping them is necessary for identical shared edges / no T junctions.
            if {p for t in new for p in t} != set(ring) or len(new) >= len(ids):
                continue
            removed.update(ids)
            replacement.extend(new)
            blocked.update(ring)
            worst = max(worst, bound)
    return [t for i,t in enumerate(faces) if i not in removed]+replacement, {
        'input_triangles': len(faces), 'output_triangles': len(faces)-len(removed)+len(replacement),
        'max_error_bound_m': worst, 'tolerance_m': tolerance}


class ExportMetrics:
    def __init__(self, optimization):
        self.optimization = optimization
        self.categories = defaultdict(Counter)
        self.timings = Counter()
        self.started = self.last = perf_counter()
        self.stage = 'prepare'

    def enter(self, stage):
        now = perf_counter()
        self.timings[self.stage] += now-self.last
        self.stage, self.last = stage, now

    def add(self, category, stats, collision=True):
        record = self.categories[category]
        record.update(stats)
        record['objects'] += 1
        if collision and not stats.get('collision_triangles'):
            record['collision_triangles'] += stats['triangles']

    def report(self):
        self.enter(self.stage)
        return {'version': 1, 'optimization': self.optimization,
                'categories': dict(self.categories), 'stage_seconds': dict(self.timings),
                'elapsed_seconds': perf_counter()-self.started,
                'note': 'Generated meshes only; stock prop/forest collision triangles require engine measurements. Timings are outside the deterministic runtime ZIP.'}
