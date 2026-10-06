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
from shapely.ops import unary_union
from shapely.geometry import LineString, Point, Polygon
from shapely.prepared import prep
from shapely.strtree import STRtree

from . import road_elevation, road_geometry as geometry, road_graph, scene, surface_audit as audit

SUPPORTED = {'T', 'X', 'Y', 'merge', 'split', 'transition', 'endcap', 'cluster'}
# Junctions joined by lanes shorter than this become one cluster template.
CLUSTER_EDGE = 9.
CLUSTER_MAX = 4
CLUSTER_ARMS = 6  # e.g. a divided road crossing a two-way street
# Pieces of a cut must tile its outline; same floor as prepare.MIN_TRIANGLE_AREA.
MIN_PIECE = 1e-4
SPECK = 1e-6           # m², pinholes left by unioning densified ribbon triangles
# Cross-section spacing of a transition; smoothstep chord error stays below 5 mm
# for a 10 cm height change over the shortest (8 m) transition.
BAND_STEP = 2.
# Lane centreline station spacing inside a patch (see lane_heights).
LANE_STEP = 1.
# Shortened sockets between close junctions: margin after the lane start,
# shortest transition and the clearance left before the far lane end (metres).
SHORT_MARGIN = 1.5
SHORT_TRANSITION = 4.
SHORT_END = 1.5
SHORT_GAP = .25  # each side of a lane shared by two templates stops this far from its middle
SLIT = .15  # half the widest gap closed between the lanes of one arm
MAIN_TURN = 45.  # degrees; widest bend of a pair of arms that may carry a core's through profile


class Unsupported(ValueError):
    """A geometric precondition failed; the complete patch must use legacy."""


class Slit(Unsupported):
    """Opposite lanes of an arm are a few centimetres apart."""


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
    if cut.geom_type == 'MultiLineString':
        pieces = sorted(cut.geoms, key=lambda g: g.distance(Point(c)))
        if any(g.distance(pieces[0]) < 2*SLIT for g in pieces[1:]):
            raise Slit('lanes of one arm separated by a slit')
        # A road curving back crosses the line again far from this arm: keep
        # the piece at the arm axis.
        cut = pieces[0]
    if cut.geom_type != 'LineString' or cut.length < .5:
        raise Unsupported('disconnected or missing socket cross-section')
    pts = sorted(cut.coords, key=lambda p: _dot(p, normal))
    return tuple(pts[0]), tuple(pts[-1])  # right, left looking outward


def _touching(area, section):
    """Parts of `area` at this socket; a road curving back leaves others further away."""
    line = LineString(section)
    return geometry.union([g for g in scene.polygons(area) if g.distance(line) < 1e-6]) if not area.is_empty else area


def _transition(area, origin, u, inner, outer):
    ri, li = _section(area, origin, u, inner)
    ro, lo = _section(area, origin, u, outer)
    band = area.intersection(_halfplane(origin, u, inner, before=False)).intersection(_halfplane(origin, u, outer))
    if band.geom_type == 'MultiPolygon':
        # Other pieces belong to the same road curving back across the strip.
        mouth, end = LineString([ri, li]), LineString([ro, lo])
        band = min(band.geoms, key=lambda g: g.distance(mouth))
        if band.distance(end) > 1e-6:
            raise Unsupported('transition is not a single ribbon')
    if band.geom_type != 'Polygon' or band.interiors:
        raise Unsupported('transition is not a single ribbon')
    return ri, li, ro, lo, band


def _solid(area):
    # Densified ribbons (v2 elevation) union with zero-area pinholes between
    # neighbouring triangles and lanes; they rejected 536 Bilychi templates as
    # "not a single ribbon". Fill only specks, never a real island.
    return unary_union([Polygon(p.exterior, [r for r in p.interiors if Polygon(r).area >= SPECK])
                        for p in scene.polygons(area)])


# Lane areas by the identity of their triangle list, valid while generate()
# evaluates candidates (cutting assigns new lists); cleared around each run.
_AREAS = {}


def _road_area(road):
    triangles = road.get('triangles')
    hit = _AREAS.get(id(triangles)) if triangles is not None else None
    if hit is not None and hit[0] is triangles:
        return hit[1]
    area = _solid(geometry.union(Polygon([p[:2] for p in tri]) for tri in (triangles if triangles is not None else
                                 audit.ribbon_triangles(road['points'], road['width']))))
    if triangles is not None:
        _AREAS[id(triangles)] = (triangles, area)
    return area


def _lanes_area(strips, lanes):
    return _solid(geometry.union(_road_area(strips[r['lane']]) for r in lanes))


def candidate(junction, strips, tolerance=.02, shared=()):
    """`shared`: neighbour junctions whose own template needs the same approach;
    each side then keeps to its half of the lane between them."""
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
        area = _lanes_area(strips, arm['lanes'])
        starts, ends = [], []
        for row in arm['lanes']:
            points = strips[row['lane']]['points']
            points = list(reversed(points)) if row['incoming'] else points
            starts.append(_dot((points[0][0]-origin[0], points[0][1]-origin[1]), u))
            ends.append(max(_dot((p[0]-origin[0], p[1]-origin[1]), u) for p in points))
        inner = max(starts)+max(3., arm['width']*.6)
        outer = inner+max(8., arm['width'])
        limit = ((max(starts)+min(ends))/2-SHORT_GAP if arm.get('other') in shared else min(ends)-3.)
        short = outer > limit
        if short:
            # A close neighbour junction: a shorter socket margin and transition.
            # The profiled core already meets the approach, so the transition
            # only removes a small residual.
            room = (limit if arm.get('other') in shared else min(ends)-SHORT_END)-max(starts)
            margin = min(max(3., arm['width']*.6), max(SHORT_MARGIN, room*.25))
            if room-margin < SHORT_TRANSITION:
                raise Unsupported('approach too short for socket and transition')
            inner = max(starts)+margin
            outer = inner+min(max(8., arm['width']), room-margin)
        try:
            ri, li, ro, lo, band = _transition(area, origin, u, inner, outer)
        except Slit:
            # Close the slit between opposite lanes and try once more.
            area = _solid(area.buffer(SLIT, join_style='mitre').buffer(-SLIT, join_style='mitre'))
            ri, li, ro, lo, band = _transition(area, origin, u, inner, outer)
        arms.append({**arm, 'inner_m': inner, 'outer_m': outer, 'start_m': max(starts), 'short': short,
                     'inner': [ri, li], 'outer': [ro, lo], '_band': band, '_area': area})
    # Order mouths by where their sockets are, not by heading: parallel one-way
    # carriageways of a cluster share a heading but sit side by side.
    arms.sort(key=lambda a: math.atan2((a['inner'][0][1]+a['inner'][1][1])/2-origin[1],
                                       (a['inner'][0][0]+a['inner'][1][0])/2-origin[0]))
    ring = [] if len(arms) > 1 else _cap(origin, arms[0], tolerance)
    for i, arm in enumerate(arms if len(arms) > 1 else []):
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
    stubs = [_touching(a['_area'].intersection(_halfplane(origin, a['direction'], a['inner_m'])), a['inner'])
             for a in arms]
    # A cluster's lanes between its own junctions lie wholly inside the core.
    stubs += [_road_area(strips[lid]) for lid in junction.get('absorbed', [])]
    # ...and so do its SUMO junction areas and turning lanes, which tie them together.
    stubs += [_solid(junction['fill'])] if junction.get('fill') is not None else []
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
        approach = _touching(a['_area'].intersection(_halfplane(origin,a['direction'],a['outer_m'])), a['outer'])
        if approach.difference(poly.buffer(2e-6)).area > .001:
            raise Unsupported('curved approach crosses template boundary before socket')
    centrelines = {lid: LineString([p[:2] for p in r['points']]) for lid, r in strips.items()}
    def road(x, y, fallback):
        # Lanes of one arm can overlap at different heights (a way split by
        # netconvert); a point belongs to the lane whose centreline is nearest.
        hits = original.hits(x, y)
        if len(hits) > 1:
            q = Point(x, y)
            return min(hits, key=lambda h: (centrelines[h[1]].distance(q), abs(h[0]-fallback)))[0]
        return geometry.height_on(original, x, y, fallback)
    samples = [(x, y, road(x, y, geometry.height_on(original, x, y))) for a in arms for x, y in a['outer']]
    if any(z is None or not math.isfinite(z) for _, _, z in samples):
        raise Unsupported('missing socket height')
    # Centre the least-squares system to avoid projection-coordinate conditioning.
    coeff = np.linalg.lstsq(np.array([[x-origin[0], y-origin[1], 1.] for x, y, _ in samples]),
                            np.array([p[2] for p in samples]), rcond=None)[0]
    def plane(x, y):
        return float(coeff[0]*(x-origin[0])+coeff[1]*(y-origin[1])+coeff[2])
    if len(arms) == 1:
        field = _arm_field(origin, arms[0], strips)
    elif junction.get('members'):
        # Parallel carriageways of a cluster may lie at different heights; no
        # single through profile fits them.
        field = _harmonic_field(poly, arms, road, plane)
    else:
        field = _core_field(origin, arms, strips) or _harmonic_field(poly, arms, road, plane)
    field = field or plane
    own = getattr(field, 'own', {})
    def height(x, y):
        p = Point(x, y)
        for a in arms:
            if a['_band'].distance(p) < 2e-6:
                s = _dot((x-origin[0], y-origin[1]), a['direction'])
                t = min(1., max(0., (s-a['inner_m'])/(a['outer_m']-a['inner_m'])))
                blend = t*t*(3-2*t)
                base = field(x, y)
                # A side arm already ramps to its own profile inside the field;
                # the transition then only removes what remains of the road.
                target = own[a['id']](x, y) if a['id'] in own else base
                return base+(road(x, y, base)-target)*blend
        return field(x, y)
    return {'id': junction['id'], 'family': junction['family'], 'arms': arms, 'origin': origin,
            'poly': poly, 'core': core, 'height': height, 'plane': plane, 'planar': field is plane}


def _cap(origin, arm, tolerance):
    """Outline of a dead end: the road's last full cross-section closed by a half circle."""
    u = arm['direction']
    right, left = _section(arm['_area'], origin, u, arm['start_m']+.05)
    centre = ((right[0]+left[0])/2, (right[1]+left[1])/2)
    radius = math.dist(right, left)/2
    # Chord sagitta below `tolerance`, as for the Bezier curb returns.
    n = max(4, math.ceil(math.pi/(2*math.acos(max(0., 1-tolerance/max(radius, tolerance))))))
    a = math.atan2(left[1]-centre[1], left[0]-centre[0])
    for sign in (1, -1):
        arc = [(centre[0]+radius*math.cos(a+sign*math.pi*k/n), centre[1]+radius*math.sin(a+sign*math.pi*k/n))
               for k in range(n+1)]
        if _dot((arc[n//2][0]-centre[0], arc[n//2][1]-centre[1]), u) < 0:
            break
    return [*arm['inner'], left, *arc[1:-1], right]


def _axis(arm, origin):
    """Point at station 0 of an arm's own axis: the line through the middle of its
    socket. A cluster's one-way carriageways sit metres beside the cluster centre."""
    (rx, ry), (lx, ly) = arm['inner']
    u = arm['direction']
    return ((rx+lx)/2-u[0]*arm['inner_m'], (ry+ly)/2-u[1]*arm['inner_m'])


def _profile(mesh, base, u, start, stop, ease=None):
    """Approach heights along an arm axis, extrapolated below the first sample:
    linearly, or with the grade fading to level over `ease` metres."""
    ts = np.arange(max(0., start), stop+1e-9, 1.)
    known = [(t, v) for t, v in zip(ts, _axis_profile(mesh, base, u, ts)) if v is not None]
    if len(known) < 2 or known[-1][0]-known[0][0] < 2.:
        return None
    (t0, z0), (t1, z1) = known[0], next(k for k in known if k[0]-known[0][0] >= 2.)
    g = (z1-z0)/(t1-t0)
    kt, kz = np.array([k[0] for k in known]), np.array([k[1] for k in known])
    def height(along):
        if along >= t0:
            return float(np.interp(along, kt, kz))
        d = t0-along
        if ease:
            d = min(d, ease)
            return float(z0-g*(d-d*d/(2*ease)))
        return float(z0-g*d)
    return height


def _lanes_mesh(strips, arms):
    return audit.TriangleIndex((r['lane'], strips[r['lane']].get('triangles', list(audit.ribbon_triangles(
        strips[r['lane']]['points'], strips[r['lane']]['width']))), {}) for arm in arms for r in arm['lanes'])


def _arm_field(origin, arm, strips):
    """A dead end continues its approach profile into the cap, levelling out
    there: a turning lane on a slope would otherwise flip its grade at once."""
    u = arm['direction']
    profile = _profile(_lanes_mesh(strips, [arm]), _axis(arm, origin), u, 0., arm['outer_m'], ease=arm['width']/2)
    if profile is None:
        return None
    return lambda x, y: profile((x-origin[0])*u[0]+(y-origin[1])*u[1])


def _harmonic_field(poly, arms, road, initial):
    """The smoothest surface (discrete Laplace, 2 m grid) through the outer sockets.

    Only the sockets are fixed; the curb outline is a natural boundary."""
    tris = scene.draped_triangles(poly, cell=BAND_STEP, min_area=MIN_PIECE)
    lookup, points, ids = {}, [], []
    for tri in tris:
        row = []
        for x, y in tri:
            key = (round(x, 7), round(y, 7))
            if key not in lookup:
                lookup[key] = len(points)
                points.append((x, y))
            row.append(lookup[key])
        ids.append(row)
    if not points:
        return None
    sockets = [LineString(a['outer']) for a in arms]
    values = np.array([initial(x, y) for x, y in points])
    fixed = np.zeros(len(points), dtype=bool)
    for i, (x, y) in enumerate(points):
        q = Point(x, y)
        if any(s.distance(q) < 1e-6 for s in sockets):
            values[i] = road(x, y, values[i])
            fixed[i] = True
    if not fixed.any():
        return None
    neighbours = [set() for _ in points]
    for row in ids:
        for a in row:
            neighbours[a].update(b for b in row if b != a)
    src = np.array([i for i, ns in enumerate(neighbours) for _ in ns], dtype=int)
    dst = np.array([j for ns in neighbours for j in sorted(ns)], dtype=int)
    count = np.maximum(1, np.bincount(src, minlength=len(points)))
    values = geometry.harmonic(values, fixed, src, dst, count)
    mesh = audit.TriangleIndex([('', [[(*points[i], float(values[i])) for i in row] for row in ids], {})])
    return lambda x, y: float(geometry.height_on(mesh, x, y, initial(x, y)))


def _smoothstep(t):
    t = min(1., max(0., t))
    return t*t*(3-2*t)


def _axis_profile(mesh, origin, direction, stations, lateral=(0., -1.5, 1.5, -3., 3.)):
    """Mean pavement height across a ray from `origin`; None where it has no pavement.

    The mean, not one lane: opposite lanes of an arm can disagree (decimetres
    to a metre where netconvert splits a way), and a profile switching between
    them would carry that step into the whole template."""
    nx, ny = -direction[1], direction[0]
    out = []
    for t in stations:
        x, y = origin[0]+direction[0]*t, origin[1]+direction[1]*t
        zs = [hits[0][0] for o in lateral for hits in [mesh.hits(x+nx*o, y+ny*o)] if hits]
        out.append(float(sum(zs)/len(zs)) if zs else None)
    return out


def _hermite_fill(s, z):
    """Fill the gap between known samples with a cubic matching both end grades."""
    known = [i for i, v in enumerate(z) if v is not None]
    if len(known) < 4:
        return None
    z = list(z)
    def grade(i, j):
        return (z[j]-z[i])/(s[j]-s[i]) if s[j] != s[i] else 0.
    for a, b in zip(known, known[1:]):
        if b-a < 2:
            continue
        a0 = min(k for k in known if k <= a and s[a]-s[k] <= 4.)
        b1 = max(k for k in known if k >= b and s[k]-s[b] <= 4.)
        m0 = grade(a0, a) if a0 != a else grade(a, b)
        m1 = grade(b, b1) if b1 != b else grade(a, b)
        h = s[b]-s[a]
        for i in range(a+1, b):
            t = (s[i]-s[a])/h
            h00, h10, h01, h11 = 2*t**3-3*t*t+1, t**3-2*t*t+t, -2*t**3+3*t*t, t**3-t*t
            z[i] = h00*z[a]+h10*h*m0+h01*z[b]+h11*h*m1
    first, last = known[0], known[-1]
    for i in range(first):
        z[i] = z[first]
    for i in range(last+1, len(z)):
        z[i] = z[last]
    return z


def _core_field(origin, arms, strips):
    """Height of a template core: one through road keeps its own profile.

    A single plane through every socket turns each road's grade into the other
    road's crossfall. Here a pair of roughly opposite arms is the through road:
    its profile, sampled from its own approach lanes and bridged across the
    junction by a cubic, is constant across the axis between its mouths. Every
    other arm ramps from the through road's edge to its own approach profile.
    The through road's grade becomes the others' crossfall inside the core, so
    the flattest pair is chosen (then the wider one): a steep street levels out
    across a flat one, as built intersections do. None means: keep the plane.
    """
    meshes = {id(arm): _lanes_mesh(strips, [arm]) for arm in arms}
    outer = {}
    for arm in arms:
        base, u = _axis(arm, origin), arm['direction']
        z = _axis_profile(meshes[id(arm)], base, u, [arm['outer_m']])[0]
        outer[id(arm)] = (z, (base[0]+u[0]*arm['outer_m'], base[1]+u[1]*arm['outer_m']))
    pairs = []
    for i, a in enumerate(arms):
        for b in arms[i+1:]:
            dot = _dot(a['direction'], b['direction'])
            (za, pa), (zb, pb) = outer[id(a)], outer[id(b)]
            if dot < -math.cos(math.radians(MAIN_TURN)) and za is not None and zb is not None:
                grade = abs(zb-za)/max(math.dist(pa, pb), 1.)
                pairs.append(((round(grade, 2), -min(a['width'], b['width']), dot), a, b))
    if not pairs:
        return None
    _, a, b = min(pairs, key=lambda p: p[0])
    m = np.subtract(b['direction'], a['direction'])
    m = m/np.linalg.norm(m)
    main_mesh = _lanes_mesh(strips, [a, b])
    rows = []
    for arm, sign in ((a, -1.), (b, 1.)):
        ts = np.arange(0. if sign < 0 else 1., arm['outer_m']+1e-9, 1.)
        base, u = _axis(arm, origin), arm['direction']
        for t, z in zip(ts, _axis_profile(main_mesh, base, u, ts)):
            rows.append((float(_dot((base[0]+u[0]*t-origin[0], base[1]+u[1]*t-origin[1]), m)), z))
    rows.sort(key=lambda r: r[0])
    s = [r[0] for r in rows]
    z = _hermite_fill(s, [r[1] for r in rows])
    if z is None:
        return None
    s, z = np.array(s), np.array(z, dtype=float)
    half = max(a['width'], b['width'])/2
    sides, own = [], {}
    for arm in arms:
        if arm is a or arm is b:
            continue
        u = arm['direction']
        sine = abs(u[0]*m[1]-u[1]*m[0])
        edge = min(half/max(sine, .3), arm['inner_m']-1.)
        base = _axis(arm, origin)
        profile = _profile(meshes[id(arm)], base, u, edge, arm['outer_m'])
        if profile is not None:
            sides.append((u, prep(arm['_area']), arm['_area'], edge, arm['outer_m'], profile))
            own[arm['id']] = lambda x, y, u=u, profile=profile: profile((x-origin[0])*u[0]+(y-origin[1])*u[1])
    def field(x, y):
        dx, dy = x-origin[0], y-origin[1]
        base = float(np.interp(dx*m[0]+dy*m[1], s, z))
        total, weight = 0., 0.
        for u, inside, area, edge, outer, profile in sides:
            along = dx*u[0]+dy*u[1]
            if along <= edge:
                continue
            # Full weight on the arm's own pavement, even where it curves away
            # from its axis (the field must equal the road at the outer socket),
            # fading beside it.
            q = Point(x, y)
            across = 0. if inside.covers(q) else area.distance(q)
            w = _smoothstep((along-edge)/(outer-edge))*(1-_smoothstep(across/max(3., .5*along)))
            if w <= 0.:
                continue
            total += w*(profile(along)-base)
            weight += w
        return base+(total/weight if weight > 1. else total)
    field.own = own
    return field


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


def clusters(graph, strips):
    """Groups of junctions joined only by lanes shorter than CLUSTER_EDGE.

    netconvert keeps some source nodes a few decimetres apart; neither of them
    has room for a socket on that lane, so the group gets one template."""
    by_id = {n['id']: n for n in graph['junctions']}
    parent = {n: n for n in by_id}
    def find(n):
        while parent[n] != n:
            parent[n] = parent[parent[n]]
            n = parent[n]
        return n
    for node in graph['junctions']:
        for arm in node['arms']:
            if arm['other'] not in by_id:
                continue
            lengths = [LineString([p[:2] for p in strips[r['lane']]['points']]).length for r in arm['lanes']]
            if lengths and max(lengths) < CLUSTER_EDGE:
                parent[find(node['id'])] = find(arm['other'])
    groups = {}
    for n in sorted(by_id):
        groups.setdefault(find(n), []).append(n)
    result = []
    for members in groups.values():
        if len(members) < 2:
            continue
        inside = set(members)
        arms = [a for m in members for a in by_id[m]['arms'] if a['other'] not in inside]
        absorbed = sorted({r['lane'] for m in members for a in by_id[m]['arms'] if a['other'] in inside
                           for r in a['lanes']})
        arms.sort(key=lambda a: (math.atan2(a['direction'][1], a['direction'][0]), a['id']))
        positions = [by_id[m]['position'] for m in members]
        shape = road_graph.classify(arms, roundabout=any(by_id[m]['family'] == 'roundabout' for m in members))
        result.append({'id': members[0], 'members': members, 'absorbed': absorbed, 'arms': arms,
                       'position': [sum(p[i] for p in positions)/len(positions) for i in (0, 1)],
                       # The cluster template accepts the shapes the single templates do.
                       'family': ('cluster' if shape in SUPPORTED-{'endcap', 'cluster'}|{'complex'}
                                  and len(members) <= CLUSTER_MAX and len(arms) <= CLUSTER_ARMS else shape),
                       'shape': shape,
                       'levels': [list(l) for l in sorted({tuple(l) for m in members for l in by_id[m]['levels']})],
                       'unmapped_ways': sorted({w for m in members for w in by_id[m]['unmapped_ways']})})
    return result


def generate(source, net, strips, road_z, tolerance=.02, targets=None):
    started = time.perf_counter()
    _AREAS.clear()
    try:
        return _generate(source, net, strips, road_z, tolerance, targets, started)
    finally:
        _AREAS.clear()


def _generate(source, net, strips, road_z, tolerance, targets, started):
    graph = road_graph.bind(source, net, strips)
    patches, records, envelopes = {}, {}, {}
    groups = clusters(graph, strips)
    member_of = {m: g for g in groups for m in g['members']}
    def internal_lanes(node):
        return [lid for m in node.get('members', [node['id']]) for lid in road_z.internal_by_node.get(m, [])]
    for node in graph['junctions']:
        nid = node['id']
        records[nid] = {'id': nid, 'family': node['family'], 'status': 'fallback', 'reason': ''}
        raw = net.getNode(nid).getShape()
        legacy_parts = [Polygon(raw).buffer(0)] if len(raw) >= 3 else []
        for lid in road_z.internal_by_node.get(nid, []):
            lane = net.getLane(lid)
            if lane.allows('passenger'):
                legacy_parts.append(scene.strip_polygon(scene.lane_xyz(lane, road_z), lane.getWidth()))
        envelopes[nid] = geometry.union(legacy_parts)
    # A cluster is one entity from here on: its id is its first member.
    for g in groups:
        envelopes[g['id']] = g['fill'] = geometry.union([envelopes.pop(m) for m in g['members']])
        for m in g['members']:
            records[m]['cluster'] = g['id']
    for node in [*[n for n in graph['junctions'] if n['id'] not in member_of], *groups]:
        nid = node['id']
        if targets is not None and not set(node.get('members', [nid])) & set(targets):
            for m in node.get('members', [nid]):
                records[m].update(status='not_selected',reason='outside selected lab case')
            continue
        adjacent = {r['lane']: strips[r['lane']] for a in node['arms'] for r in a['lanes']}
        adjacent.update({lid: strips[lid] for lid in node.get('absorbed', [])})
        try:
            patch = candidate(node, adjacent, tolerance)
            # Every traffic centreline must remain supported; topology is never
            # rewritten to hide a template that doesn't fit its source network.
            for lid in internal_lanes(node):
                lane = net.getLane(lid)
                if lane.allows('passenger') and not patch['poly'].buffer(.01).covers(LineString(road_z.shape(lane))):
                    raise Unsupported('template does not cover internal lane')
            patch['members'] = node.get('members', [nid])
            patch['absorbed'] = node.get('absorbed', [])
            patches[nid] = patch
        except Unsupported as exc:
            for m in node.get('members', [nid]):
                records[m]['reason'] = ('cluster: ' if 'members' in node else '')+str(exc)
    # Two templates sized independently both claim a short lane between them;
    # rebuild each to its half of that lane before the conflict check below.
    by_id = {**{n['id']: n for n in graph['junctions']}, **{g['id']: g for g in groups}}
    ids = sorted(patches)
    tree = STRtree([patches[n]['poly'] for n in ids])
    shared = {}
    for i, nid in enumerate(ids):
        neighbours = {member_of[a['other']]['id'] if a['other'] in member_of else a['other']
                      for a in patches[nid]['arms']}
        for j in tree.query(patches[nid]['poly']):
            other = ids[int(j)]
            if other in neighbours and patches[nid]['poly'].intersection(patches[other]['poly']).area > .001:
                shared.setdefault(nid, set()).add(other)
                shared.setdefault(other, set()).add(nid)
    for nid in sorted(shared):
        node = by_id[nid]
        adjacent = {r['lane']: strips[r['lane']] for a in node['arms'] for r in a['lanes']}
        adjacent.update({lid: strips[lid] for lid in node.get('absorbed', [])})
        # Arms name neighbouring junctions, not clusters.
        near = {m for n in shared[nid] for m in (by_id[n].get('members', [n]))}
        try:
            patch = candidate(node, adjacent, tolerance, near)
            for lid in internal_lanes(node):
                lane = net.getLane(lid)
                if lane.allows('passenger') and not patch['poly'].buffer(.01).covers(LineString(road_z.shape(lane))):
                    raise Unsupported('template does not cover internal lane')
            patch['members'] = node.get('members', [nid])
            patch['absorbed'] = node.get('absorbed', [])
            patches[nid] = patch
        except Unsupported as exc:
            for m in patches.pop(nid)['members']:
                records[m]['reason'] = ('cluster: ' if 'members' in node else '')+str(exc)
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
            for m in patches.pop(nid)['members']:
                records[m]['reason'] = 'overlapping junction group'
    by_lane = {}
    for nid, patch in sorted(patches.items()):
        for lid in [*[row['lane'] for a in patch['arms'] for row in a['lanes']], *patch['absorbed']]:
            by_lane.setdefault(lid, []).append(patch)
        # A collar only where an approach has a SUMO sidewalk: service dead
        # ends and driveways have none.
        patch['sidewalk'] = any(lane.allows('pedestrian') and not lane.allows('passenger')
                                for a in patch['arms'] for e in {r['edge'] for r in a['lanes']}
                                for lane in net.getEdge(e).getLanes())
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
        # A transition varies only along its arm: cross-sections at most
        # BAND_STEP apart. A planar core is triangulated whole, any other core
        # (through-road profile or harmonic) on a BAND_STEP grid.
        for region, arm in [(patch['core'], None), *[(a['_band'], a) for a in patch['arms']]]:
            for pg in scene.stitch_vertices([region], knots, tol=1e-6):
                pieces = (_band_slices(pg, patch['origin'], arm) if arm is not None or patch['planar'] else
                          [pg.intersection(c) for c in _core_cells(pg)])
                for piece in pieces:
                    for tri in scene.triangles(piece, MIN_PIECE):
                        triangles.append([(x, y, patch['height'](x, y)) for x, y in tri])
        patch['triangles'] = triangles
        mesh = audit.TriangleIndex([(nid, triangles, {})])
        analytic = patch['height']
        # All consumers sample the final triangulated surface, not an independent curve.
        patch['height'] = lambda x, y, m=mesh, f=analytic: geometry.height_on(m, x, y, f(x, y))
        records[nid].update(status='v2', reason='', triangles=len(triangles),
                            sockets=[{k: v for k, v in a.items() if not k.startswith('_')} for a in patch['arms']])
        if len(patch['members']) > 1:
            records[nid].update(family='cluster', shape=by_id[nid]['shape'])
            for m in patch['members'][1:]:
                records[m].update(status='v2', reason='', family='cluster')
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


def _core_cells(poly, cell=BAND_STEP):
    from shapely.geometry import box
    x0, y0, x1, y1 = poly.bounds
    return [box(i*cell, j*cell, (i+1)*cell, (j+1)*cell)
            for i in range(math.floor(x0/cell), math.ceil(x1/cell))
            for j in range(math.floor(y0/cell), math.ceil(y1/cell))]


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
        lids.update(patch.get('absorbed', []))
        for m in patch.get('members', [nid]):
            lids.update(road_z.internal_by_node.get(m, []))
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
    patches = {k: p for k, p in patches.items() if p.get('sidewalk', True)}
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


SIDEWALK_MIN_RUN = 4.0     # m; a shorter leftover is a shard, not a sidewalk
SIDEWALK_OVERLAP = 0.15    # m of carriageway a sidewalk edge may touch
WALK_MIN_AREA = 1.5        # m²
WALK_MIN_WIDTH = 0.6       # m


def clear_sidewalks(strips, areas, carriageway):
    """Sidewalks follow the carriageway, never cross it (playtest 2026-10-06, note 4).

    The carriageway (same-level road strips and junction surfaces) is drawn first;
    a sidewalk run whose centreline comes within half its width of the shrunk
    carriageway is removed: at a merging slip road the main road's SUMO sidewalk
    otherwise runs across the gore and over the slip road. Short leftovers and thin
    walking-area slivers are dropped instead of drawn as kerb shards."""
    if carriageway.is_empty:
        return strips, areas, {'sidewalk_runs_cut': 0, 'walking_slivers_dropped': 0}
    core = carriageway.buffer(-SIDEWALK_OVERLAP)
    near = prep(core)
    out, cut = [], 0
    for s in strips:
        if s.get('structure_level', 0) or s.get('bridge'):
            out.append(s)
            continue
        poly = scene.strip_polygon(s['points'], s['width'])
        if poly.is_empty or not near.intersects(poly):
            out.append(s)
            continue
        runs = _runs_clear_of(s['points'], core.buffer(s['width']/2), max(SIDEWALK_MIN_RUN, s['width']))
        cut += 1
        out += [{**s, 'points': run} for run in runs]
    kept, dropped = [], 0
    for a in areas:
        if a.get('structure_level', 0) or a.get('bridge'):
            kept.append(a)
            continue
        tri_polys = [Polygon([p[:2] for p in t]) for t in a['triangles']]
        parts = scene.polygons(geometry.union(tp.buffer(1e-6) for tp in tri_polys))
        solid = [pg for pg in parts if pg.area >= WALK_MIN_AREA and not pg.buffer(-WALK_MIN_WIDTH/2).is_empty]
        if len(solid) == len(parts):
            kept.append(a)
            continue
        dropped += len(parts)-len(solid)
        if not solid:
            continue
        keep = prep(geometry.union(solid).buffer(1e-4))
        rings = [r for r in a.get('rings', []) if len(r) >= 3 and keep.intersects(Polygon([p[:2] for p in r]).buffer(0))]
        kept.append({**a, 'triangles': [t for t, tp in zip(a['triangles'], tri_polys) if keep.contains(tp.centroid)],
                     'rings': rings})
    return out, kept, {'sidewalk_runs_cut': cut, 'walking_slivers_dropped': dropped}
