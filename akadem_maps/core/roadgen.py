"""Opt-in socket / transition / junction pavement generator.

SUMO's lane graph is immutable. Only generated pavement and its height sampler
change. Candidate patches are validated before any strip is changed; overlapping
or unsupported patches fall back together, with explicit diagnostic reasons.
"""
from collections import Counter
import math
import time

import numpy as np
from shapely import set_precision, line_merge
from shapely.geometry import LineString, Point, Polygon
from shapely.prepared import prep
from shapely.strtree import STRtree

from . import road_geometry as geometry, road_graph, scene, surface_audit as audit

SUPPORTED = {'T', 'X', 'Y', 'merge', 'split', 'transition'}
# Pieces of a cut must tile its outline; same floor as prepare.MIN_TRIANGLE_AREA.
MIN_PIECE = 1e-4
# Cross-section spacing of a transition; smoothstep chord error stays below 5 mm
# for a 10 cm height change over the shortest (8 m) transition.
BAND_STEP = 2.
# Lane centreline station spacing inside a patch (see lane_heights).
LANE_STEP = 1.


class Unsupported(ValueError):
    """A geometric precondition failed; the complete patch must use legacy."""


def options(cfg):
    raw = cfg.get('road_geometry', {})
    if not isinstance(raw, dict) or set(raw)-{'mode', 'curve_tolerance_m'}:
        raise ValueError('road_geometry accepts mode and curve_tolerance_m')
    mode = raw.get('mode', 'legacy')
    tolerance = raw.get('curve_tolerance_m', .02)
    if mode not in ('legacy', 'v2'):
        raise ValueError('road_geometry.mode must be legacy or v2')
    if isinstance(tolerance, bool) or not isinstance(tolerance, (float, int)) or not math.isfinite(tolerance) or not .002 <= tolerance <= .2:
        raise ValueError('road_geometry.curve_tolerance_m must be between 0.002 and 0.2')
    return {'mode': mode, 'curve_tolerance_m': tolerance}


def bezier(p0, p1, p2, p3, tolerance=.02):
    """Adaptive de Casteljau subdivision, bounded by control-polygon flatness."""
    result = [tuple(p0)]
    def split(a, b, c, d, depth):
        chord = LineString([a, d])
        flat = max(chord.distance(Point(b)), chord.distance(Point(c)))
        if flat <= tolerance and math.dist(a, d) <= 2.:
            result.append(tuple(d))
            return
        if depth >= 16:
            raise Unsupported('curve subdivision budget')
        mid = lambda p, q: tuple((x+y)/2 for x, y in zip(p, q))
        ab, bc, cd = mid(a, b), mid(b, c), mid(c, d)
        abc, bcd = mid(ab, bc), mid(bc, cd)
        m = mid(abc, bcd)
        split(a, ab, abc, m, depth+1)
        split(m, bcd, cd, d, depth+1)
    split(tuple(p0), tuple(p1), tuple(p2), tuple(p3), 0)
    return result


def _dot(p, d):
    return sum(x*y for x, y in zip(p[:2], d))


def _halfplane(origin, direction, distance, *, before=True):
    u, v = direction, (-direction[1], direction[0])
    c = [origin[i]+distance*u[i] for i in (0, 1)]
    sign, span = (-1 if before else 1), 100000.
    return Polygon([(c[0]+v[0]*s+u[0]*t, c[1]+v[1]*s+u[1]*t)
                    for s, t in [(-span, 0), (span, 0), (span, sign*span), (-span, sign*span)]])


def _section(area, origin, direction, distance):
    normal = (-direction[1], direction[0])
    c = [origin[i]+distance*direction[i] for i in (0, 1)]
    line = LineString([(c[0]+normal[0]*s, c[1]+normal[1]*s) for s in (-1000., 1000.)])
    cut = area.intersection(line)
    if cut.geom_type == 'MultiLineString':
        # Densified collinear ribbon triangles can leave sub-micrometre gaps
        # in the overlay. Merge only touching fragments, never a real island.
        cut = line_merge(set_precision(cut, 1e-6))
    if cut.geom_type != 'LineString' or cut.length < .5:
        raise Unsupported('disconnected or missing socket cross-section')
    pts = sorted(cut.coords, key=lambda p: _dot(p, normal))
    return tuple(pts[0]), tuple(pts[-1])  # right, left looking outward


def _road_area(road):
    return geometry.union(Polygon([p[:2] for p in tri]) for tri in road.get(
        'triangles', list(audit.ribbon_triangles(road['points'], road['width']))))


def candidate(junction, strips, tolerance=.02):
    if junction['family'] not in SUPPORTED:
        raise Unsupported('unsupported family: '+junction['family'])
    if junction['unmapped_ways'] or any(not a['ways'] for a in junction['arms']):
        raise Unsupported('unresolved source mapping')
    if junction['levels'] != [[0, False, False]]:
        raise Unsupported('structure level requires legacy')
    origin, arms = junction['position'], []
    original = audit.TriangleIndex((lid, r.get('triangles', list(audit.ribbon_triangles(r['points'], r['width']))), {})
                                  for lid, r in strips.items())
    for arm in junction['arms']:
        u = arm['direction']
        if math.hypot(*u) < .9:
            raise Unsupported('undefined approach tangent')
        area = geometry.union(_road_area(strips[r['lane']]) for r in arm['lanes'])
        starts, ends = [], []
        for row in arm['lanes']:
            points = strips[row['lane']]['points']
            points = list(reversed(points)) if row['incoming'] else points
            starts.append(_dot((points[0][0]-origin[0], points[0][1]-origin[1]), u))
            ends.append(max(_dot((p[0]-origin[0], p[1]-origin[1]), u) for p in points))
        inner = max(starts)+max(3., arm['width']*.6)
        outer = inner+max(8., arm['width'])
        if min(ends) < outer+3.:
            raise Unsupported('approach too short for socket and transition')
        ri, li = _section(area, origin, u, inner)
        ro, lo = _section(area, origin, u, outer)
        band = area.intersection(_halfplane(origin, u, inner, before=False)).intersection(_halfplane(origin, u, outer))
        if band.geom_type != 'Polygon' or band.interiors:
            raise Unsupported('transition is not a single ribbon')
        arms.append({**arm, 'inner_m': inner, 'outer_m': outer,
                     'inner': [ri, li], 'outer': [ro, lo], '_band': band, '_area': area})
    ring = []
    for i, arm in enumerate(arms):
        following = arms[(i+1) % len(arms)]
        right, left = arm['inner']
        ring += [right, left]
        a, b = left, following['inner'][0]
        u, v = arm['direction'], following['direction']
        # Tangents at both mouths follow the approach; control handles remain
        # short enough to avoid overshoot at acute-angle and unequal-width mouths.
        handle = min(math.dist(a, b)*.45, arm['inner_m']*.7, following['inner_m']*.7)
        curve = bezier(a, (a[0]-u[0]*handle, a[1]-u[1]*handle),
                       (b[0]-v[0]*handle, b[1]-v[1]*handle), b, tolerance)
        ring += curve[1:-1]
    core = Polygon(ring)
    if not core.is_valid or core.area < .01 or core.interiors:
        raise Unsupported('self-intersecting template boundary')
    # The approach before its socket is replaced by the core. A wider arm or a
    # skewed corner can leave a sliver of it outside the curb-return curve; the
    # core absorbs it so the road can be cut completely at the socket.
    stubs = [a['_area'].intersection(_halfplane(origin, a['direction'], a['inner_m'])) for a in arms]
    core = geometry.union([core, *stubs])
    if core.geom_type != 'Polygon' or not core.is_valid or core.interiors:
        raise Unsupported('approach stub detached from template core')
    # Transitions must touch the core only at their socket, and may not overlap.
    for i, a in enumerate(arms):
        if core.intersection(a['_band']).area > .001:
            raise Unsupported('core overlaps transition')
        for b in arms[i+1:]:
            if a['_band'].intersection(b['_band']).area > .001:
                raise Unsupported('overlapping approach transitions')
    core = set_precision(core, 1e-6)
    for a in arms:
        a['_band'] = set_precision(a['_band'], 1e-6)
    poly = geometry.union([core, *[a['_band'] for a in arms]])
    if poly.geom_type != 'Polygon' or not poly.is_valid or poly.interiors:
        raise Unsupported('disconnected patch')
    for a in arms:
        incoming_area = geometry.union(_road_area(strips[r['lane']]) for r in a['lanes'])
        approach = incoming_area.intersection(_halfplane(origin,a['direction'],a['outer_m']))
        if approach.difference(poly.buffer(2e-6)).area > .001:
            raise Unsupported('curved approach crosses template boundary before socket')
    samples = [(x, y, geometry.height_on(original, x, y)) for a in arms for x, y in a['outer']]
    if any(z is None or not math.isfinite(z) for _, _, z in samples):
        raise Unsupported('missing socket height')
    # Centre the least-squares system to avoid projection-coordinate conditioning.
    coeff = np.linalg.lstsq(np.array([[x-origin[0], y-origin[1], 1.] for x, y, _ in samples]),
                            np.array([p[2] for p in samples]), rcond=None)[0]
    def plane(x, y):
        return float(coeff[0]*(x-origin[0])+coeff[1]*(y-origin[1])+coeff[2])
    def height(x, y):
        p = Point(x, y)
        for a in arms:
            if a['_band'].distance(p) < 2e-6:
                s = _dot((x-origin[0], y-origin[1]), a['direction'])
                t = min(1., max(0., (s-a['inner_m'])/(a['outer_m']-a['inner_m'])))
                blend = t*t*(3-2*t)
                return plane(x, y)+(geometry.height_on(original, x, y, plane(x, y))-plane(x, y))*blend
        return plane(x, y)
    return {'id': junction['id'], 'family': junction['family'], 'arms': arms, 'origin': origin,
            'poly': poly, 'core': core, 'height': height, 'plane': plane}


def _clip(triangles, cut):
    result = []
    for tri in triangles:
        coeff = audit.plane(tri)
        if coeff is None:
            continue
        poly = Polygon([p[:2] for p in tri])
        if not poly.intersects(cut):
            result.append(tri)
            continue
        for t in scene.triangles(geometry.robust('difference', poly, cut), MIN_PIECE):
            if Polygon(t).area >= 1e-4:
                result.append([(x, y, audit.at(coeff, x, y)) for x, y in t])
    return result


def generate(source, net, strips, road_z, tolerance=.02, targets=None):
    started = time.perf_counter()
    graph = road_graph.bind(source, net, strips)
    patches, records, envelopes = {}, {}, {}
    for node in graph['junctions']:
        nid = node['id']
        records[nid] = {'id': nid, 'family': node['family'], 'status': 'fallback', 'reason': ''}
        adjacent = {r['lane']: strips[r['lane']] for a in node['arms'] for r in a['lanes']}
        raw = net.getNode(nid).getShape()
        legacy_parts = [Polygon(raw).buffer(0)] if len(raw) >= 3 else []
        for lid in road_z.internal_by_node.get(nid, []):
            lane = net.getLane(lid)
            if lane.allows('passenger'):
                legacy_parts.append(scene.strip_polygon(scene.lane_xyz(lane, road_z), lane.getWidth()))
        envelopes[nid] = geometry.union(legacy_parts)
        if targets is not None and nid not in targets:
            records[nid].update(status='not_selected',reason='outside selected lab case')
            continue
        try:
            patch = candidate(node, adjacent, tolerance)
            # Every traffic centreline must remain supported; topology is never
            # rewritten to hide a template that doesn't fit its source network.
            for lid in road_z.internal_by_node.get(nid, []):
                lane = net.getLane(lid)
                if lane.allows('passenger') and not patch['poly'].buffer(.01).covers(LineString(road_z.shape(lane))):
                    raise Unsupported('template does not cover internal lane')
            patches[nid] = patch
        except Unsupported as exc:
            records[nid]['reason'] = str(exc)
    # Reject the complete spatial conflict group. Including legacy envelopes
    # ensures a rejected adjacent patch cannot overlap a surviving v2 patch.
    ids = sorted(envelopes)
    areas = [geometry.union([envelopes[n], patches[n]['poly']]) if n in patches else envelopes[n] for n in ids]
    tree = STRtree(areas)
    conflicts = set()
    for i, area in enumerate(areas):
        for j in tree.query(area):
            j = int(j)
            if j <= i or not (ids[i] in patches or ids[j] in patches):
                continue
            if area.intersection(areas[j]).area > .001:
                conflicts.update((ids[i], ids[j]))
    for nid in sorted(conflicts):
        if nid in patches:
            del patches[nid]
            records[nid]['reason'] = 'overlapping junction group'
    by_lane = {}
    for nid, patch in sorted(patches.items()):
        for a in patch['arms']:
            for row in a['lanes']:
                by_lane.setdefault(row['lane'], []).append(patch)
    owned = {}
    for lid, local in sorted(by_lane.items()):
        road = strips[lid]
        group = road['topology']['edge'].lstrip('-')
        cut = geometry.union([*[p['poly'] for p in local], owned.get(group, Polygon())])
        original_area = _road_area(road)
        road['triangles'] = _clip(road.get('triangles', list(audit.ribbon_triangles(road['points'], road['width']))),
                                  cut)
        owned[group] = geometry.union([owned.get(group, Polygon()), original_area])
        road['geometry'] = 'v2'
    for nid, patch in sorted(patches.items()):
        knots = [p[:2] for a in patch['arms'] for row in a['lanes'] for tri in strips[row['lane']]['triangles'] for p in tri]
        triangles = []
        # The core is one plane and a transition varies only along its arm, so
        # neither needs a world-aligned draping grid: the core is triangulated
        # whole, a transition in cross-sections at most BAND_STEP apart.
        for region, arm in [(patch['core'], None), *[(a['_band'], a) for a in patch['arms']]]:
            for pg in scene.stitch_vertices([region], knots, tol=1e-6):
                for piece in _band_slices(pg, patch['origin'], arm):
                    for tri in scene.triangles(piece, MIN_PIECE):
                        triangles.append([(x, y, patch['height'](x, y)) for x, y in tri])
        patch['triangles'] = triangles
        mesh = audit.TriangleIndex([(nid, triangles, {})])
        analytic = patch['height']
        # All consumers sample the final triangulated surface, not an independent curve.
        patch['height'] = lambda x, y, m=mesh, f=analytic: geometry.height_on(m, x, y, f(x, y))
        records[nid].update(status='v2', reason='', triangles=len(triangles),
                            sockets=[{k: v for k, v in a.items() if not k.startswith('_')} for a in patch['arms']])
    for lid, local in by_lane.items():
        # Overlay precision can leave a micrometre-wide rim of the source road
        # beside a transition. Its boundary must use the same height field,
        # otherwise millimetre serialization turns that rim into a vertical lip.
        def seam_vertex(v):
            for patch in local:
                if patch['poly'].distance(Point(v[:2])) <= .001:
                    return (v[0],v[1],patch['height'](v[0],v[1]))
            return v
        strips[lid]['triangles'] = [[seam_vertex(v) for v in tri] for tri in strips[lid]['triangles']]
    # A cut creates stations on a neighbour's long boundary edges. Insert the
    # same stations on both sides BEFORE millimetre world serialization; otherwise
    # independent rounding of T-junction vertices opens hairline collision gaps.
    groups = {}
    for lid in by_lane:
        groups.setdefault(strips[lid]['topology']['edge'].lstrip('-'), []).append(lid)
    for lids in groups.values():
        local = {p['id']:p for lid in lids for p in by_lane[lid]}
        knots = [v[:2] for lid in lids for tri in strips[lid]['triangles'] for v in tri]
        knots += [v[:2] for p in local.values() for tri in p['triangles'] for v in tri]
        for lid in lids:
            strips[lid]['triangles'] = stitch_mesh(strips[lid]['triangles'], knots)
    for nid, patch in patches.items():
        lids = {r['lane'] for a in patch['arms'] for r in a['lanes']}
        knots = [v[:2] for lid in lids for tri in strips[lid]['triangles'] for v in tri]
        patch['triangles'] = stitch_mesh(patch['triangles'], knots)
        mesh = audit.TriangleIndex([(nid, patch['triangles'], {})])
        previous = patch['height']
        patch['height'] = lambda x,y,m=mesh,f=previous: geometry.height_on(m,x,y,f(x,y))
        records[nid]['triangles'] = len(patch['triangles'])
    for lid, local in by_lane.items():
        adjusted = {}
        for tri in strips[lid]['triangles']:
            for v in tri:
                key = tuple(v[:2])
                if key in adjusted:
                    continue
                adjusted[key] = v
                for patch in local:
                    if patch['poly'].distance(Point(key)) <= .001:
                        adjusted[key] = (*key,patch['height'](*key))
                        break
        strips[lid]['triangles'] = [[adjusted[tuple(v[:2])] for v in tri] for tri in strips[lid]['triangles']]
    return patches, graph, {'version': 1, 'mode': 'v2', 'curve_tolerance_m': tolerance,
                            'counts': dict(Counter(r['status'] for r in records.values())),
                            'families': dict(Counter(p['family'] for p in patches.values())),
                            'junctions': list(records.values()), 'provenance': 'generated'}, {
                                'roadgen_seconds': time.perf_counter()-started}


def _band_slices(poly, origin, arm):
    if arm is None:
        return [poly]
    span = arm['outer_m']-arm['inner_m']
    n = max(1, math.ceil(span/BAND_STEP))
    cuts = [arm['inner_m']+span*k/n for k in range(1, n)]
    pieces, rest = [], poly
    for d in cuts:
        pieces.append(rest.intersection(_halfplane(origin, arm['direction'], d)))
        rest = rest.intersection(_halfplane(origin, arm['direction'], d, before=False))
    return [*pieces, rest]


def stitch_mesh(triangles, knots):
    polygons = [Polygon([v[:2] for v in t]) for t in triangles]
    stitched = scene.stitch_vertices(polygons, knots, tol=2e-6)
    output = []
    for tri, old, new in zip(triangles, polygons, stitched):
        if len(new.exterior.coords) == len(old.exterior.coords):
            output.append(tri)
            continue
        coeff = audit.plane(tri)
        if coeff is not None:
            output.extend([[(x,y,audit.at(coeff,x,y)) for x,y in t] for t in scene.triangles(new, MIN_PIECE)])
    return output


def lane_heights(patches, road_z, step=LANE_STEP):
    """Put approach and internal lane centrelines on the patch surface.

    A transition bends smoothly along its arm; a lane keeping only its sparse
    SUMO vertices would cut the chord (up to 13 cm off the asphalt on Bilychi).
    Inside a patch the line gets a station at least every `step` metres.
    """
    for nid, patch in sorted(patches.items()):
        lids = {row['lane'] for arm in patch['arms'] for row in arm['lanes']}
        lids.update(road_z.internal_by_node.get(nid, []))
        near = prep(patch['poly'].buffer(.01))
        for lid in sorted(lids):
            if lid not in road_z.z:
                continue
            shape, zs = road_z.shapes[lid], road_z.z[lid]
            points, heights = [tuple(shape[0])], [zs[0]]
            for a, b, za, zb in zip(shape, shape[1:], zs, zs[1:]):
                if near.intersects(LineString([a, b])):
                    n = max(1, math.ceil(math.dist(a, b)/step))
                    for k in range(1, n):
                        t = k/n
                        points.append((a[0]+(b[0]-a[0])*t, a[1]+(b[1]-a[1])*t))
                        heights.append(za+(zb-za)*t)
                points.append(tuple(b))
                heights.append(zb)
            road_z.shapes[lid] = points
            road_z.z[lid] = [patch['height'](x, y) if patch['poly'].covers(Point(x, y)) else z
                             for (x, y), z in zip(points, heights)]


def footprint(road):
    return _road_area(road) if road.get('geometry') == 'v2' else scene.strip_polygon(road['points'], road['width'])


def paint_surfaces(patches, strips, road_z):
    by_edge = {}
    road_z.stop_points = {}
    for patch in patches.values():
        for arm in patch['arms']:
            for row in arm['lanes']:
                by_edge.setdefault(row['edge'], []).append((patch, arm))
                if row['incoming']:
                    cut = LineString([p[:2] for p in strips[row['lane']]['points']]).intersection(LineString(arm['inner']))
                    if cut.geom_type == 'Point':
                        road_z.stop_points[row['lane']] = (cut.x, cut.y, patch['height'](cut.x, cut.y))
    for edge, local in by_edge.items():
        roads = [r for r in strips.values() if r['topology'].get('edge') == edge]
        mesh = audit.TriangleIndex((r['lane'], r.get('triangles', list(audit.ribbon_triangles(r['points'], r['width']))), {}) for r in roads)
        road_z.paint_areas[edge] = geometry.union([*mesh.polys, *[a['_band'] for p, a in local]])
        def height(x, y, z, nearby=local, m=mesh):
            for patch, arm in nearby:
                if arm['_band'].distance(Point(x,y)) < 1e-6:
                    return patch['height'](x,y)
            return geometry.height_on(m,x,y,z)
        road_z.paint_heights[edge] = height


def boundaries(road):
    """Exact rendered edges for terrain anchoring (including cut sockets)."""
    mesh = audit.TriangleIndex([('', road['triangles'], {})])
    return [[(x, y, geometry.height_on(mesh, x, y)) for x, y in ring.coords]
            for poly in scene.polygons(footprint(road)) for ring in [poly.exterior, *poly.interiors]]


def sidewalks(strips, areas, patches, carriageway):
    """Replace sidewalk pieces around patches with a shared three-metre collar.

    Only the part of a sidewalk near a collar changes: runs of a strip clear of
    it stay strips and untouched walking areas keep their triangles, so the
    mesh grows with the number of junctions, not with total sidewalk length.
    """
    if not patches:
        return strips, areas
    # The outer edge meets ground or other sidewalks, never asphalt, so it is
    # coarse; the inner edge comes from the exact carriageway below.
    collars = [(p, p['poly'].buffer(3., quad_segs=4).simplify(.05)) for p in patches.values()]
    region = geometry.union(c for _, c in collars)
    near = prep(region)
    kept, adjusted, pieces = [], [], []
    for s in strips:
        poly = scene.strip_polygon(s['points'], s['width'])
        if s.get('structure_level', 0) or not near.intersects(poly):
            kept.append(s)
            continue
        runs = _runs_clear_of(s['points'], region.buffer(s['width']), s['width'])
        kept += [{**s, 'points': run} for run in runs]
        mesh = audit.TriangleIndex([('', audit.ribbon_triangles(s['points'], s['width']), {})])
        remainder = poly.difference(geometry.union(scene.strip_polygon(r, s['width']) for r in runs))
        for pg in scene.polygons(remainder.difference(region).difference(carriageway)):
            pieces.append(_walking_area(pg, lambda x, y, m=mesh: geometry.height_on(m, x, y)))
    for a in areas:
        if a.get('structure_level', 0) or a.get('bridge') or not any(
                near.intersects(Polygon([p[:2] for p in t])) for t in a['triangles']):
            adjusted.append(a)
            continue
        tris = _clip(a['triangles'], region)
        if not tris:
            continue
        # Clipping keeps each triangle's own plane; no re-draping is needed.
        mesh = audit.TriangleIndex([('', tris, {})])
        for pg in scene.polygons(geometry.union(Polygon([p[:2] for p in t]) for t in tris)):
            inside = prep(pg.buffer(1e-6))
            adjusted.append({**a, 'provenance': 'generated',
                             'triangles': [t for t in tris if inside.contains(Polygon([p[:2] for p in t]))],
                             'rings': [[(x, y, geometry.height_on(mesh, x, y)) for x, y in ring.coords]
                                       for ring in [pg.exterior, *pg.interiors]]})
    adjusted += [p for p in pieces if p['triangles']]
    claimed = Polygon()
    for patch, collar in collars:
        allowed = collar.difference(carriageway).difference(claimed)
        for pg in scene.polygons(allowed):
            adjusted.append(_walking_area(pg, patch['height']))
        claimed = geometry.union([claimed, allowed])
    return kept, adjusted


def _runs_clear_of(points, obstacle, width):
    """3D sub-polylines of `points` outside `obstacle`, each at least `width` long."""
    line = LineString([p[:2] for p in points])
    stations = [0.]
    for a, b in zip(points, points[1:]):
        stations.append(stations[-1]+math.dist(a[:2], b[:2]))
    def at(d):
        for (a, b), s0, s1 in zip(zip(points, points[1:]), stations, stations[1:]):
            if d <= s1 and s1 > s0:
                t = max(0., (d-s0)/(s1-s0))
                return tuple(u+(v-u)*t for u, v in zip(a, b))
        return tuple(points[-1])
    runs = []
    rest = line.difference(obstacle)
    for part in getattr(rest, 'geoms', [rest]):
        if part.geom_type != 'LineString' or part.length < width:
            continue
        d0, d1 = sorted((line.project(Point(part.coords[0])), line.project(Point(part.coords[-1]))))
        run = [at(d0), *[tuple(p) for p, s in zip(points, stations) if d0 < s < d1], at(d1)]
        if len(run) >= 2:
            runs.append(run)
    return runs


def _walking_area(poly, height):
    return {'bridge': False, 'structure_level': 0, 'provenance': 'generated',
            'triangles': [[(x, y, height(x, y)) for x, y in t] for t in scene.draped_triangles(poly, cell=2., min_area=MIN_PIECE)],
            'rings': [[(x, y, height(x, y)) for x, y in ring.coords] for ring in [poly.exterior, *poly.interiors]]}
