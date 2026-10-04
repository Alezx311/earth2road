"""Shared, generated road geometry. Source OSM and SUMO files are not mutated.

Only topologically connected surfaces on the same explicit structure level may
share a seam. Higher priority carriageways remain fixed. All coordinates are
SUMO x/y/up metres; exporters consume the resulting triangles unchanged.
"""
from collections import Counter
import math

import numpy as np
from shapely.geometry import LineString, Point, Polygon
from shapely import set_precision
from shapely.errors import GEOSException
from shapely.ops import nearest_points, unary_union
from shapely.strtree import STRtree

from . import scene
from .surface_audit import TriangleIndex, at, plane, relationship, ribbon_triangles, structure

TAPER = 60.0
SPACING = 2.0
RANK = {v: i for i, v in enumerate(('motorway', 'trunk', 'primary', 'secondary', 'tertiary',
                                    'unclassified', 'residential', 'living_street', 'service'))}


GRIDS = (1e-6, 1e-4, 1e-3)  # metres; snapping used only after a GEOS noding failure.


def _snapped(run, geoms):
    try:
        return run(geoms)
    except GEOSException:
        for i, grid in enumerate(GRIDS):
            try:
                return run([set_precision(g, grid) for g in geoms])
            except GEOSException:
                if i == len(GRIDS)-1:
                    raise


def robust(name, a, b):
    """a.<name>(b), retried on progressively coarser (<=1 mm) grids on GEOS noding failure."""
    return _snapped(lambda g: getattr(g[0], name)(g[1]), [a, b])


def union(geoms):
    return _snapped(unary_union, list(geoms))


def densify(points, step=SPACING):
    result = [tuple(points[0])] if points else []
    for a, b in zip(points, points[1:]):
        count = max(1, math.ceil(math.dist(a[:2], b[:2])/step))
        result.extend(tuple(a[k]+(b[k]-a[k])*j/count for k in range(len(a))) for j in range(1, count+1))
    return result


def smooth_turn(points, tolerance=.3):
    """Hermite curve with fixed ends/tangents, accepted only inside the SUMO corridor."""
    if len(points) < 3:
        return densify(points, 1.)
    xy = [tuple(p[:2]) for p in points]
    corridor = LineString(xy).buffer(tolerance)
    tangents = []
    for i, p in enumerate(xy):
        a, b = xy[max(0, i-1)], xy[min(i+1, len(xy)-1)]
        length = math.dist(a, b) or 1.
        tangents.append(((b[0]-a[0])/length, (b[1]-a[1])/length))
    result = [tuple(points[0])]
    for i, (a, b) in enumerate(zip(points, points[1:])):
        length = math.dist(a[:2], b[:2])
        for j in range(1, max(2, math.ceil(length/.75))+1):
            t = j/max(2, math.ceil(length/.75))
            pos = tuple((2*t**3-3*t*t+1)*a[k]+(t**3-2*t*t+t)*length*tangents[i][k]
                        +(-2*t**3+3*t*t)*b[k]+(t**3-t*t)*length*tangents[i+1][k] for k in range(2))
            result.append((*pos, a[2]+(b[2]-a[2])*t))
    if not corridor.covers(LineString([p[:2] for p in result])):
        return densify(points, 1.)
    return result


def metadata(net, tags, refs):
    result = {}
    for edge in net.getEdges():
        if edge.getFunction():
            continue
        for lane in edge.getLanes():
            ways = lane.getParam('origId', '').split()
            facts = [tags.get(w, {}) for w in ways]
            kinds = [f.get('highway', 'service') for f in facts]
            result[lane.getID()] = {
                'nodes': [edge.getFromNode().getID(), edge.getToNode().getID()], 'ways': ways,
                'osm_nodes': sorted({n for w in ways for n in refs.get(w, [])}),
                'levels': [list(s) for s in sorted({structure(f) for f in facts})],
                'rank': min((RANK.get(k.removesuffix('_link'), 8)+(.5 if k.endswith('_link') else 0) for k in kinds), default=8),
                'edge': edge.getID()}
    return result


def height_on(mesh, x, y, fallback=None):
    hits = mesh.hits(x, y)
    if hits:
        return min(hits, key=lambda h: abs(h[0]-fallback))[0] if fallback is not None else hits[0][0]
    if not mesh.polys:
        return fallback
    i = int(mesh.tree.nearest(Point(x, y)))
    return at(mesh.planes[i], x, y)


def align_strips(strips):
    """Clip followers to fixed major surfaces and taper the seam correction over 60 m.

    The intersection is computed along complete segments, including where there
    are no OSM/SUMO vertices. Each resulting border vertex samples the exact major
    triangle plane. The uncut main pavement supplies the other half of the seam.
    """
    groups = {}
    for road in strips:
        # SUMO names the opposite direction of edge X "-X": both directions of one
        # two-way road form one carriageway and receive one correction.
        edge = str(road['topology'].get('edge', road['lane']))
        groups.setdefault(edge.lstrip('-'), []).append(road)
    carriageways = list(groups.values())
    polygons = [union(scene.strip_polygon(r['points'], r['width']) for r in group) for group in carriageways]
    tree = STRtree(polygons)
    report = Counter()
    details = []
    order = sorted(range(len(carriageways)), key=lambda k: (carriageways[k][0]['topology']['rank'], carriageways[k][0]['lane']))
    position = {k: n for n, k in enumerate(order)}
    for i in order:
        group, footprint = carriageways[i], polygons[i]
        meta = group[0]['topology']
        candidates = []
        for k in tree.query(footprint):
            k = int(k)
            major = carriageways[k][0]
            # Equal rank: the carriageway settled earlier is the reference, so the
            # dependency order is acyclic and each seam is solved once.
            if k == i or major['topology']['rank'] > meta['rank'] or position[k] > position[i]:
                continue
            if not footprint.intersects(polygons[k]):
                continue
            relation = relationship(meta, major['topology'])
            if relation != 'connected':
                report[relation+'_candidates'] += 1
                continue
            overlap = robust('intersection', footprint, polygons[k])
            if overlap.area > .005:
                candidates.append(k)
        if not candidates:
            continue
        # Every lane in the major carriageway participates, so the follower does
        # not alternately snap to individual lane edges while crossing the road.
        candidates.sort(key=lambda k: (carriageways[k][0]['topology']['rank'], carriageways[k][0]['lane']))
        main_roads = [r for k in candidates for r in carriageways[k]]
        main_mesh = TriangleIndex((r['lane'], r.get('triangles', list(ribbon_triangles(r['points'], r['width']))),
                                   r['topology']) for r in main_roads)
        main_area = union(main_mesh.polys)
        contact = robust('intersection', footprint, main_area)
        if contact.is_empty:
            continue
        bases = {r['lane']: densify(r['points']) for r in group}
        original = TriangleIndex((r['lane'], r.get('triangles', ribbon_triangles(bases[r['lane']], r['width'])), meta) for r in group)
        line = LineString([p[:2] for p in group[0]['points']])
        contact_points = [p for pg in scene.polygons(contact) for p in pg.exterior.coords]
        distances = [line.project(Point(p)) for p in contact_points]
        if not distances:
            continue
        start, end = min(distances), max(distances)

        corrected = make_height(original, main_mesh, main_area, line, start, end)

        for road in group:
            base_points = bases[road['lane']]
            road['points'] = [(x, y, corrected(x, y)) for x, y, _ in base_points]
            tris = []
            for tri in road.get('triangles', ribbon_triangles(base_points, road['width'])):
                poly = robust('difference', Polygon([p[:2] for p in tri]), main_area)
                for cut in scene.triangles(poly):
                    tris.append([(x, y, corrected(x, y)) for x, y in cut])
            road['triangles'] = tris
            road['_height'] = corrected
            report['aligned_strips'] += 1
            report['virtual_points'] += max(0, len(base_points)-2)
            details.append({'lane': road['lane'], 'main_lanes': [r['lane'] for r in main_roads],
                            'contact_start_m': round(start, 3), 'contact_end_m': round(end, 3),
                            'clipped_area_m2': round(contact.area, 3)})
    return {'counts': dict(report), 'seams': details, 'taper_m': TAPER, 'provenance': 'generated'}


def make_height(original, main_mesh, main_area, line, start, end):
    def height(x, y):
        old = height_on(original, x, y)
        pt = Point(x, y)
        if main_area.covers(pt):
            return height_on(main_mesh, x, y, old)
        s = line.project(pt)
        u = min(1., max(start-s, s-end, 0.)/TAPER)
        if u == 1.:
            return old
        return old+(1-3*u*u+2*u*u*u)*(height_on(main_mesh, x, y, old)-old)
    return height


def junction_surface(poly, adjoining, fallback):
    """Constrained boundary + harmonic interior, after subtracting same-level roads."""
    mesh = TriangleIndex((r['lane'], r.get('triangles', list(ribbon_triangles(r['points'], r['width']))), r['topology']) for r in adjoining)
    cut = union(mesh.polys)
    poly = union(scene.polygons(robust('difference', poly, cut)))
    knots = [p for pg in mesh.polys for p in pg.exterior.coords]
    parts = scene.stitch_vertices(scene.polygons(poly), knots, tol=1e-6)
    # Subdivide without losing knots on common borders.
    raw = [t for pg in parts for t in scene.draped_triangles(pg, cell=2.)]
    lookup, points, ids = {}, [], []
    for tri in raw:
        row = []
        for p in tri:
            key = (round(p[0], 8), round(p[1], 8))
            if key not in lookup:
                lookup[key] = len(points)
                points.append(p)
            row.append(lookup[key])
        ids.append(row)
    if not points:
        return poly, [], fallback
    values = np.array([fallback(*p) for p in points])
    fixed = np.zeros(len(points), dtype=bool)
    boundary = poly.boundary
    for i, p in enumerate(points):
        q = Point(p)
        if mesh.polys and cut.distance(q) < .003:
            values[i] = height_on(mesh, *p, values[i])
            fixed[i] = True
        elif boundary.distance(q) < 1e-7:
            fixed[i] = True
    neighbors = [set() for _ in points]
    for tri in ids:
        for a in tri:
            neighbors[a].update(b for b in tri if b != a)
    src = np.array([i for i, ns in enumerate(neighbors) for _ in ns], dtype=int)
    dst = np.array([j for ns in neighbors for j in sorted(ns)], dtype=int)
    count = np.maximum(1, np.bincount(src, minlength=len(points)))
    for _ in range(250):
        avg = np.bincount(src, weights=values[dst], minlength=len(points))/count
        avg[fixed] = values[fixed]
        if np.max(np.abs(avg-values)) < 1e-5:
            values = avg
            break
        values = avg
    triangles = [[(*points[i], float(values[i])) for i in tri] for tri in ids]
    output = TriangleIndex([('junction', triangles, {})])
    def height(x, y):
        hits = output.hits(x, y)
        if hits:
            return hits[0][0]
        return height_on(mesh, x, y, fallback(x, y)) if mesh.polys else fallback(x, y)
    return poly, triangles, height


def dash_parts(points, on=3., off=6.):
    """Split after laying out one continuous phase over the complete curve."""
    along, current = 0., []
    for a, b in zip(points, points[1:]):
        length = math.dist(a[:2], b[:2])
        if length < 1e-9:
            continue
        s = 0.
        while s < length-1e-8:
            phase = (along+s+1e-9) % (on+off)
            drawing = phase < on
            step = min((on-phase if drawing else on+off-phase), length-s)
            if step < 1e-8:
                step = min(1e-7, length-s)
            p = tuple(a[k]+(b[k]-a[k])*s/length for k in range(3))
            q = tuple(a[k]+(b[k]-a[k])*(s+step)/length for k in range(3))
            if drawing:
                if not current:
                    current.append(p)
                current.append(q)
            elif current:
                yield current
                current = []
            s += step
        along += length
    if len(current) >= 2:
        yield current


def turn_markings(net, road_z, node_polys):
    """Generated turn guides follow the same smoothed internal curves and surface.

    Adjacent lane connections only: do not invent an isolated centreline for every
    crossing trajectory. Paint phase is applied before clipping to the junction.
    """
    markings, seen = [], set()
    for edge in net.getEdges():
        lanes = sorted([l for l in edge.getLanes() if l.allows('passenger')], key=lambda l: l.getIndex())
        for inner, outer in zip(lanes, lanes[1:]):
            for conn in inner.getOutgoing():
                if not any(c.getToLane().getEdge() == conn.getToLane().getEdge() and
                           c.getToLane().getIndex() == conn.getToLane().getIndex()+1 for c in outer.getOutgoing()):
                    continue
                chain, via = [], conn.getViaLaneID()
                while via and via not in chain:
                    chain.append(via)
                    outs = net.getLane(via).getOutgoing()
                    via = outs[0].getViaLaneID() if outs else ''
                if not chain or tuple(chain) in seen:
                    continue
                seen.add(tuple(chain))
                node_id = edge.getToNode().getID()
                poly = node_polys.get(node_id)
                if poly is None or poly.is_empty:
                    continue
                pts = []
                for lid in chain:
                    lane = net.getLane(lid)
                    segment = scene.offset_line(scene.lane_xyz(lane, road_z), lane.getWidth()/2)
                    pts += segment[1:] if pts and math.dist(pts[-1][:2], segment[0][:2]) < .01 else segment
                height = road_z.node_z[node_id]
                # Erode by half stripe width: even the outside edge stays off the main road.
                allowed = poly.buffer(-scene.LINE_WIDTH/2)
                for dash in dash_parts(pts, *scene.DASH_LANE):
                    clipped = LineString([p[:2] for p in dash]).intersection(allowed)
                    for part in getattr(clipped, 'geoms', [clipped]):
                        if part.geom_type == 'LineString' and part.length > .03:
                            markings.append({'points': [(x, y, height(x,y)) for x,y in part.coords],
                                             'width': scene.LINE_WIDTH, 'dash': [], 'kind': 'white',
                                             'provenance': 'generated', 'internal_lanes': chain})
    return markings
