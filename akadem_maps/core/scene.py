"""Render geometry derived from the SUMO network and OSM (roads, markings, sidewalks,
ground). Coordinates here are SUMO metres (x east, y north); callers convert to Godot
space with prepare.point(). Everything visual that is not in OSM/SUMO is a documented
assumption (marking patterns, curb height, path widths)."""
import math

import numpy as np
import shapely
from shapely.geometry import LineString, MultiPolygon, Point, Polygon, box
from shapely.ops import unary_union

MAIN_ROADS = ('highway.trunk', 'highway.primary', 'highway.secondary', 'highway.tertiary',
              'highway.trunk_link', 'highway.primary_link', 'highway.secondary_link', 'highway.tertiary_link')
UNMARKED = ('highway.service', 'highway.living_street')
DASH_LANE = [3.0, 6.0]        # assumed urban lane divider pattern, metres on/off
LINE_WIDTH = 0.12
STOP_LINE_WIDTH = 0.4
ZEBRA = [0.5, 0.6]
PATH_WIDTH = {'footway': 1.8, 'path': 1.2, 'cycleway': 1.8, 'pedestrian': 3.5, 'bridleway': 1.2}
GROUND_CELL = 20.0
DECK_MEDIAN_GAP = 6.0        # m; narrower slots between parallel bridge decks are closed (assumed single structure)


class LocalCut:
    """`geom` for many small differences against it (paths, green areas).

    Each `x.difference(geom)` re-nodes the whole map-wide polygon; on a 45 km² district
    that took hours. Above LOCAL_CUT_COORDS vertices the polygon is split once into
    quadtree tiles (clip_by_rect) and each query subtracts only the tiles around its envelope.
    Smaller maps keep the exact original operation."""

    def __init__(self, geom, leaf=2000):
        self.geom = geom
        self.tree = None
        if geom is None or geom.is_empty or shapely.get_num_coordinates(geom) <= LOCAL_CUT_COORDS:
            return
        self.leaves, self.rects = [], []
        self._split(geom, geom.bounds, leaf, 0)
        self.tree = shapely.STRtree(self.rects)

    def _split(self, geom, rect, leaf, depth):
        if geom.is_empty:
            return
        if shapely.get_num_coordinates(geom) <= leaf or depth >= 12:
            if not geom.is_valid:
                geom = shapely.make_valid(geom)
            self.leaves.append(geom)
            self.rects.append(box(*rect))
            return
        x0, y0, x1, y1 = rect
        mx, my = (x0 + x1) / 2, (y0 + y1) / 2
        for r in ((x0, y0, mx, my), (mx, y0, x1, my), (x0, my, mx, y1), (mx, my, x1, y1)):
            try:
                part = shapely.clip_by_rect(geom, *r)
            except shapely.errors.GEOSException:
                # RectangleIntersection can emit a collapsed ring; the full overlay cannot.
                part = geom.intersection(box(*r))
            self._split(part, r, leaf, depth + 1)

    def around(self, other):
        if self.tree is None:
            return self.geom
        if other.is_empty:  # empty bounds are NaN; box(NaN...) raises (Detroit 4 km, 07.10.2026)
            return Polygon()
        hits = self.tree.query(box(*other.bounds).buffer(1.0))
        return unary_union([self.leaves[i] for i in hits]) if len(hits) else Polygon()

    def subtract_from(self, other):
        if self.tree is None:
            return other.difference(self.geom)
        if other.is_empty:  # e.g. a green area already fully under the road cover cut
            return other
        # A - (B u C) = (A - B) - C: no union of the tiles per query.
        for i in self.tree.query(box(*other.bounds).buffer(1.0)):
            if other.is_empty:
                break
            other = other.difference(self.leaves[i])
        return other


LOCAL_CUT_COORDS = 100000
DRAPE_SPLIT_WORK = 50_000_000   # polygon vertices x grid cells


def polygons(geom):
    if geom is None or geom.is_empty:
        return []
    if geom.geom_type == 'Polygon':
        return [geom]
    if geom.geom_type in ('MultiPolygon', 'GeometryCollection'):
        return [g for part in geom.geoms for g in polygons(part)]
    return []


def planar(ring):
    """2D polygon from an xyz ring (SUMO metres). Empty if the ring is too short to close.
    West Kyiv has walking-area lanes with 2–3 points; Polygon() raises on those."""
    xy = [(p[0], p[1]) for p in ring]
    if len(xy) < 3:
        return Polygon()
    try:
        poly = Polygon(xy).buffer(0)
    except ValueError:
        return Polygon()
    return poly if not poly.is_empty else Polygon()


def triangles(poly, min_area=0.01):
    """Constrained Delaunay triangulation: keeps concave outlines and holes intact.
    Parts below `min_area` are dropped; callers whose pieces must tile an exact
    outline (generated junction pavement) pass a smaller value."""
    if not poly.is_valid:
        poly = poly.buffer(0)
    out = []
    for p in polygons(poly):
        if p.area < min_area:
            continue
        out += [list(t.exterior.coords)[:3] for t in shapely.constrained_delaunay_triangles(p).geoms]
    return out


def draped_triangles(poly, cell=GROUND_CELL, min_area=0.01):
    """Triangles of `poly` split on a grid so a height field evaluated at the vertices
    follows the terrain instead of spanning it with one flat plane."""
    out = []
    for p in polygons(poly):
        x0, y0, x1, y1 = p.bounds
        ix0, ix1 = math.floor(x0/cell), math.ceil(x1/cell)
        iy0, iy1 = math.floor(y0/cell), math.ceil(y1/cell)
        if int(shapely.get_num_coordinates(p)) * (ix1 - ix0) * (iy1 - iy0) > DRAPE_SPLIT_WORK:
            # District-wide ground: intersecting the whole polygon with every cell is
            # O(cells x vertices). Halve it along the same cell grid first (same cells, same order).
            _drape_split(p, ix0, ix1, iy0, iy1, cell, out, min_area)
            continue
        for ix in range(ix0, ix1):
            for iy in range(iy0, iy1):
                part = p.intersection(box(ix*cell, iy*cell, (ix+1)*cell, (iy+1)*cell))
                out += triangles(part, min_area)
    return out


def _drape_split(p, ix0, ix1, iy0, iy1, cell, out, min_area=0.01):
    if p.is_empty:
        return
    if ix1 - ix0 > 1:
        m = (ix0 + ix1) // 2
        for a, b in ((ix0, m), (m, ix1)):
            _drape_split(p.intersection(box(a*cell, iy0*cell, b*cell, iy1*cell)), a, b, iy0, iy1, cell, out, min_area)
    elif iy1 - iy0 > 1:
        m = (iy0 + iy1) // 2
        for a, b in ((iy0, m), (m, iy1)):
            _drape_split(p.intersection(box(ix0*cell, a*cell, ix1*cell, b*cell)), ix0, ix1, a, b, cell, out, min_area)
    else:
        out += triangles(p.intersection(box(ix0*cell, iy0*cell, ix1*cell, iy1*cell)), min_area)


def offset_line(pts, d):
    """Mitered parallel of a 3D polyline [(x, y, z)], d > 0 to the left of travel."""
    n = len(pts)
    normals = []
    for a, b in zip(pts, pts[1:]):
        tx, ty = b[0]-a[0], b[1]-a[1]
        length = math.hypot(tx, ty) or 1.0
        normals.append((-ty/length, tx/length))
    if not normals:
        return list(pts)
    out = []
    for i in range(n):
        if i == 0:
            mx, my = normals[0]
            scale = 1.0
        elif i == n-1:
            mx, my = normals[-1]
            scale = 1.0
        else:
            (ax, ay), (bx, by) = normals[i-1], normals[i]
            mx, my = ax+bx, ay+by
            length = math.hypot(mx, my)
            if length < 1e-6:
                mx, my, scale = ax, ay, 1.0
            else:
                mx, my = mx/length, my/length
                scale = 1.0/max(0.5, mx*ax+my*ay)
        out.append((pts[i][0]+mx*d*scale, pts[i][1]+my*d*scale, pts[i][2]))
    return out


def lane_xyz(lane, road_z):
    shape = road_z.shape(lane) if hasattr(road_z, 'shape') else lane.getShape()
    return [(x, y, z) for (x, y), z in zip(shape, road_z.z[lane.getID()])]


def reverse_edge(net, edge):
    for other in edge.getToNode().getOutgoing():
        if other.getToNode() == edge.getFromNode() and other.getFunction() == '':
            if {edge.getID(), other.getID()} and (other.getID() == '-'+edge.getID() or edge.getID() == '-'+other.getID()):
                return other
    return None


def markings(net, road_z, structure_of, skip=()):
    """Painted lines as polylines {points, width, dash}. Derived from SUMO topology;
    patterns are assumed (Ukrainian urban style), not surveyed."""
    out = []
    paint_height = None
    paint_area = None
    def add(pts, width, dash=None, kind='white'):
        if len(pts) >= 2:
            if paint_height:
                pts = [(x, y, paint_height(x, y, z)) for x, y, z in pts]
            if paint_area is not None:
                from .road_geometry import dash_parts
                pieces = dash_parts(pts, *dash) if dash else [pts]
                allowed = paint_area.buffer(-width/2)
                for piece in pieces:
                    line = LineString(piece)
                    cut = line.intersection(allowed)
                    for part in getattr(cut, 'geoms', [cut]):
                        if part.geom_type == 'LineString' and part.length > .03:
                            points = [tuple(line.interpolate(line.project(Point(p[:2]))).coords[0]) for p in part.coords]
                            out.append({'points': points, 'width': width, 'dash': [], 'kind': kind, 'provenance': 'generated'})
                return
            out.append({'points': pts, 'width': width, 'dash': dash or [], 'kind': kind, 'provenance': 'generated'})
    for edge in net.getEdges():
        if edge.getFunction() != '' or edge.getType() in UNMARKED or edge.getID() in skip:
            continue
        lanes = sorted([l for l in edge.getLanes() if l.allows('passenger')], key=lambda l: l.getIndex())
        if not lanes:
            continue
        paint_height = getattr(road_z, 'paint_heights', {}).get(edge.getID())
        paint_area = getattr(road_z, 'paint_areas', {}).get(edge.getID())
        main = edge.getType() in MAIN_ROADS
        for inner, outer in zip(lanes, lanes[1:]):
            add(offset_line(lane_xyz(inner, road_z), inner.getWidth()/2), LINE_WIDTH, DASH_LANE)
        right = lanes[0]
        if main:
            add(offset_line(lane_xyz(right, road_z), -right.getWidth()/2+0.25), LINE_WIDTH)
        left = lanes[-1]
        rev = reverse_edge(net, edge)
        centre = offset_line(lane_xyz(left, road_z), left.getWidth()/2)
        if rev is not None:
            if not edge.getID().startswith('-'):
                total = len(lanes)+len([l for l in rev.getLanes() if l.allows('passenger')])
                if total >= 4:
                    add(offset_line(centre, 0.1), LINE_WIDTH)
                    add(offset_line(centre, -0.1), LINE_WIDTH)
                elif sum(l.getWidth() for l in lanes) + sum(l.getWidth() for l in rev.getLanes() if l.allows('passenger')) >= 5.0:
                    # A single shared OSM lane is represented by two half-width
                    # SUMO lanes. A centre stripe would falsely imply two lanes.
                    add(centre, LINE_WIDTH, DASH_LANE if total <= 2 and not main else None)
        elif main:
            add(offset_line(lane_xyz(left, road_z), left.getWidth()/2-0.25), LINE_WIDTH)
        to_node = edge.getToNode()
        signalised = to_node.getType() == 'traffic_light'
        for lane in lanes:
            conns = lane.getOutgoing()
            minor = conns and all(c.getState() in ('m', 's', 'w') for c in conns)
            if (signalised or minor) and lane.getLength() > 8:
                pts = lane_xyz(lane, road_z)
                tip = getattr(road_z, 'stop_points', {}).get(lane.getID(), offset_line(pts, 0)[-1])
                a, b = pts[-2], pts[-1]
                length = math.hypot(b[0]-a[0], b[1]-a[1]) or 1.0
                back = (tip[0]-(b[0]-a[0])/length*0.5, tip[1]-(b[1]-a[1])/length*0.5, tip[2])
                nx, ny = -(b[1]-a[1])/length, (b[0]-a[0])/length
                half = lane.getWidth()/2-0.05
                add([(back[0]-nx*half, back[1]-ny*half, back[2]), (back[0]+nx*half, back[1]+ny*half, back[2])], STOP_LINE_WIDTH)
    for edge in net.getEdges(withInternal=True):
        if edge.getFunction() == 'crossing':
            paint_height = None
            paint_area = None
            for lane in edge.getLanes():
                add(lane_xyz(lane, road_z), max(2.0, lane.getWidth()-0.4), ZEBRA)
    if hasattr(road_z, 'turn_markings'):
        out.extend(road_z.turn_markings)
    return out


def sidewalks(net, road_z, carriageway=None, structure_of=None):
    """Sidewalk strips and walking areas. Walking areas are clipped by `carriageway`
    (junction surfaces, lane strips): SUMO puts them over dead ends and corners, where a
    raised curb would otherwise block the road.

    `structure_of(edge)` returns the structure level of an edge (>0 bridge, <0 tunnel),
    matching prepare.py's levels; pedestrian strips and walking areas on a bridge are then
    flagged 'bridge': True so the ground layer can exclude their elevated borders and cuts.
    The default (None) marks nothing, preserving the plain API."""
    strips, areas = [], []
    def on_bridge(edge):
        return bool(structure_of(edge)) if structure_of is not None else False
    for edge in net.getEdges(withInternal=True):
        for lane in edge.getLanes():
            if not lane.allows('pedestrian') or lane.allows('passenger'):
                continue
            if edge.getFunction() == '':
                strips.append({'points': lane_xyz(lane, road_z), 'width': lane.getWidth(),
                               'bridge': on_bridge(edge), 'structure_level': structure_of(edge) if structure_of else 0})
            elif edge.getFunction() == 'walkingarea':
                ring = lane_xyz(lane, road_z)
                poly = planar(ring)
                if poly.is_empty:
                    continue
                if carriageway is not None:
                    poly = poly.difference(carriageway)
                def z_near(x, y, ring=ring):
                    return min(ring, key=lambda p: (p[0]-x)**2+(p[1]-y)**2)[2]
                parts = [p for p in polygons(poly) if p.area > 0.3]
                tris = [t for p in parts for t in triangles(p)]
                if tris:
                    areas.append({'bridge': on_bridge(edge), 'structure_level': structure_of(edge) if structure_of else 0,
                                  'triangles': [[(x, y, z_near(x, y)) for x, y in t] for t in tris],
                                  'rings': [[(x, y, z_near(x, y)) for x, y in list(r.coords)[:-1]] for p in parts for r in [p.exterior, *p.interiors]]})
    return strips, areas


def strip_borders(points, width, pad=0.0):
    """Left and right border polylines of a strip ribbon, using the same miter formula as
    world.gd `borders` (clamp scale 0.5), so 2D cut geometry and the rendered ribbon agree
    corner for corner even on sharp turns (the old LineString buffer with mitre_limit=3
    differed there by up to one half-width)."""
    half = width/2+pad
    return offset_line(points, half), offset_line(points, -half)


def border_segments(polyline):
    """Consecutive (x, y, z) segments of a border polyline; zero-length spans are skipped."""
    out = []
    for a, b in zip(polyline, polyline[1:]):
        if (b[0]-a[0])**2+(b[1]-a[1])**2 > 1e-12:
            out.append((tuple(a), tuple(b)))
    return out


def strip_polygon(points, width, pad=0.0):
    """2D polygon of a strip cut out of the ground: the exact offset borders closed at both
    ends (flat caps), matching the drawn ribbon in world.gd."""
    if len(points) < 2:
        return Polygon()
    left, right = strip_borders(points, width, pad)
    ring = [(p[0], p[1]) for p in left]+[(p[0], p[1]) for p in reversed(right)]
    try:
        poly = Polygon(ring)
    except ValueError:
        return Polygon()
    if poly.is_empty:
        return Polygon()
    if not poly.is_valid:
        poly = poly.buffer(0)
    return poly


def footprint(strips, widths_pad=0.0):
    """2D union of strip footprints built from the actual offset borders (miter clamp 0.5,
    as world.gd draws), not from buffered centerlines: the ground cut boundary therefore
    coincides with the rendered ribbon edge corner-for-corner."""
    polys = []
    for s in strips:
        if s.get('geometry') == 'v2':
            from .roadgen import footprint as generated_footprint
            p = generated_footprint(s)
            polys.append(p.buffer(widths_pad) if widths_pad else p)
        elif len(s['points']) >= 2:
            polys.append(strip_polygon(s['points'], s['width'], widths_pad))
    polys = [p for p in polys if not p.is_empty]
    if not polys:
        return Polygon()
    if len(polys) == 1:
        return polys[0]
    from .road_geometry import union  # GEOS noding failures retried on a <=1 mm grid
    return union(polys)


class GroundField:
    """Terrain height: DEM, pulled toward adjoining road surfaces within `radius` so the
    ground meets the carriageway without cliffs or gaps. Bridges/tunnels are not used
    as anchors or edges, so ground under a deck stays at terrain level.

    `edges` are the actual ribbon border segments (non-bridge strips, sidewalks at their
    base height, junction outlines). A query point on or very near a segment snaps exactly
    to the segment's interpolated height, so the ground mesh vertex on the seam carries the
    same piecewise-linear profile as the drawn ribbon; outward of `snap` the field blends
    smoothly to the anchor-IDW value over `band` metres. Segments are bucketed in the same
    grid as the anchors, so lookup is O(1) in the number of segments."""
    def __init__(self, dem, anchors, edges=(), radius=22.0, cell=25.0, snap=0.04, band=6.0):
        self.dem, self.radius, self.cell = dem, radius, cell
        self.snap, self.band = snap, band
        grid = {}
        for x, y, z in anchors:
            grid.setdefault((int(x//cell), int(y//cell)), []).append((x, y, z-dem(x, y)))
        self.grid = {k: np.array(v) for k, v in grid.items()}
        self.edges = []
        seg_grid = {}
        for idx, (a, b) in enumerate(edges):
            x0, y0, z0 = a
            x1, y1, z1 = b
            self.edges.append((x0, y0, z0, x1, y1, z1))
            for i in range(int(min(x0, x1)//cell), int(max(x0, x1)//cell)+1):
                for j in range(int(min(y0, y1)//cell), int(max(y0, y1)//cell)+1):
                    seg_grid.setdefault((i, j), []).append(idx)
        self.seg_grid = seg_grid
        self.cache = {}

    def _nearest_edge(self, x, y):
        """(d2, z at projection, px, py) of the nearest border segment within band."""
        cx, cy = int(x//self.cell), int(y//self.cell)
        best = None
        for i in (-1, 0, 1):
            for j in (-1, 0, 1):
                for idx in self.seg_grid.get((cx+i, cy+j), ()):
                    x0, y0, z0, x1, y1, z1 = self.edges[idx]
                    dx, dy = x1-x0, y1-y0
                    length2 = dx*dx+dy*dy
                    if length2 <= 1e-12:
                        px, py, t = x0, y0, 0.0
                    else:
                        t = ((x-x0)*dx+(y-y0)*dy)/length2
                        if t <= 0.0:
                            px, py, t = x0, y0, 0.0
                        elif t >= 1.0:
                            px, py, t = x1, y1, 1.0
                        else:
                            px, py = x0+dx*t, y0+dy*t
                    d2 = (x-px)**2+(y-py)**2
                    if d2 > self.band*self.band:
                        continue
                    if best is None or d2 < best[0]:
                        best = (d2, z0+(z1-z0)*t, px, py)
        return best

    def __call__(self, x, y):
        key = (round(x, 2), round(y, 2))
        if key in self.cache:
            return self.cache[key]
        base = self.dem(x, y)
        cx, cy = int(x//self.cell), int(y//self.cell)
        arrays = [self.grid[k] for k in ((cx+i, cy+j) for i in (-1, 0, 1) for j in (-1, 0, 1)) if k in self.grid]
        value = base
        if arrays:
            a = np.concatenate(arrays)
            d = np.hypot(a[:, 0]-x, a[:, 1]-y)
            near = d < self.radius
            if near.any():
                dn = d[near]
                w = 1/np.maximum(dn, 0.5)**2
                correction = float((w*a[near, 2]).sum()/w.sum())
                t = float(dn.min())/self.radius
                value = base+correction*(1-t*t*(3-2*t))
        best = self._nearest_edge(x, y)
        if best is not None:
            d2, z_seg, _, _ = best
            d = math.sqrt(d2)
            if d <= self.snap:
                value = z_seg
            elif d < self.band:
                u = (d-self.snap)/max(self.band-self.snap, 1e-6)
                f = u*u*(3-2*u)
                value = z_seg+(value-z_seg)*f
        self.cache[key] = value
        return value


LOW_DECK_CLEARANCE = 2.0   # ground this close under a deck (or above it) is not a real underpass
DECK_PAD = 0.3             # hole margin beyond the deck edge, hidden by the 1.2 m deck sides


def low_decks(strips, junctions, ground, clearance=LOW_DECK_CLEARANCE, pad=DECK_PAD):
    """Bridge decks the terrain reaches: (cut polygon, [(x0, y0, z0, x1, y1, z1, half)]).

    Ground under bridges is not cut (a real underpass must stay visible), and the coarse
    DEM can sit above a low deck: the ground mesh then shows through the asphalt. Runs of
    deck segments whose ground is within `clearance` below the deck are cut out of the
    ground instead; the segments feed DeckClamp for the ground around the hole.
    `strips` are bridge road strips in network XY, `junctions` [(polygon, z_at)] bridge nodes."""
    cuts, segments = [], []
    for strip in strips:
        pts, half = strip['points'], strip['width']/2
        low = [ground(p[0], p[1]) > p[2]-clearance for p in pts]
        run = []
        for i, (a, b) in enumerate(zip(pts, pts[1:])):
            if low[i] or low[i+1]:
                if not run:
                    run.append(a)
                run.append(b)
                segments.append((a[0], a[1], a[2], b[0], b[1], b[2], half))
            elif run:
                cuts.append(strip_polygon(run, strip['width'], pad))
                run = []
        if len(run) >= 2:
            cuts.append(strip_polygon(run, strip['width'], pad))
    for poly, z_at in junctions:
        for pg in polygons(poly):
            ring = list(pg.exterior.coords)
            if any(ground(x, y) > z_at(x, y)-clearance for x, y in ring):
                cuts.append(pg.buffer(pad))
                for (x0, y0), (x1, y1) in zip(ring, ring[1:]):
                    segments.append((x0, y0, z_at(x0, y0), x1, y1, z_at(x1, y1), 0.0))
    cuts = [c for c in cuts if not c.is_empty]
    return (unary_union(cuts) if cuts else Polygon()), segments


def deck_medians(strips, max_gap=DECK_MEDIAN_GAP, max_step=0.5, cell=3.0):
    """Deck infill between parallel bridge carriageways: triangles [(x, y, z)*3].

    OSM draws the two directions of an overpass as separate bridge ways a few metres apart.
    Drawn as two decks, the median became a slot down to the terrain. Slots up to `max_gap`
    wide are closed at deck level wherever the nearest deck on either side agrees within
    `max_step`; wider or split-level gaps (a ramp passing over another deck) stay open."""
    live = [s for s in strips if len(s['points']) >= 2]
    if len(live) < 2:
        return []
    polys = [strip_polygon(s['points'], s['width']) for s in live]
    lines = [LineString([(p[0], p[1]) for p in s['points']]) for s in live]
    decks = unary_union([p for p in polys if not p.is_empty])
    closed = decks.buffer(max_gap/2, join_style=2).buffer(-max_gap/2, join_style=2)
    gaps = closed.difference(decks.buffer(-0.05))
    from shapely.strtree import STRtree
    tree = STRtree(lines)
    reach = max_gap+max(s['width'] for s in live)
    def z_on(i, x, y):
        pts, line = live[i]['points'], lines[i]
        s = line.project(Point(x, y))
        along = 0.0
        for a, b in zip(pts, pts[1:]):
            d = math.hypot(b[0]-a[0], b[1]-a[1])
            if s <= along+d:
                t = 0.0 if d == 0 else (s-along)/d
                return a[2]+(b[2]-a[2])*t
            along += d
        return pts[-1][2]
    def sides(x, y):
        """Nearest strip, and the nearest one on the opposite side of (x, y)."""
        c = Point(x, y)
        near = []
        for i in tree.query(c.buffer(reach)):
            q = lines[i].interpolate(lines[i].project(c))
            near.append((c.distance(q), i, (q.x-x, q.y-y)))
        near.sort()
        if not near:
            return None
        _, i, (ax, ay) = near[0]
        for _, j, (bx, by) in near[1:]:
            if ax*bx+ay*by < 0:
                return i, j
        return None
    out = []
    for pg in polygons(gaps):
        if pg.area < 0.5 or pg.buffer(-0.3).is_empty:
            continue
        for tri in draped_triangles(pg, cell=cell):
            pair = sides(sum(p[0] for p in tri)/3, sum(p[1] for p in tri)/3)
            if pair is None:
                continue
            i, j = pair
            pts = []
            for x, y in tri:
                zi, zj = z_on(i, x, y), z_on(j, x, y)
                if abs(zi-zj) > max_step:
                    break
                wi = 1/max(lines[i].distance(Point(x, y)), 0.05)
                wj = 1/max(lines[j].distance(Point(x, y)), 0.05)
                pts.append((x, y, (wi*zi+wj*zj)/(wi+wj)))
            else:
                out.append(pts)
    return out


class DeckClamp:
    """Height field kept under low bridge decks: at most the deck height minus
    `clearance` within the deck edge plus `pad`, rising by `slope` per metre beyond,
    so the ground triangles around a cut deck never reach its surface."""
    def __init__(self, field, segments, clearance=0.15, pad=DECK_PAD+0.2, slope=1.0, band=6.0, cell=25.0):
        self.field, self.clearance, self.pad, self.slope, self.band, self.cell = field, clearance, pad, slope, band, cell
        self.segments = segments
        self.grid = {}
        for idx, (x0, y0, _z0, x1, y1, _z1, half) in enumerate(segments):
            reach = half+pad+band
            for i in range(int((min(x0, x1)-reach)//cell), int((max(x0, x1)+reach)//cell)+1):
                for j in range(int((min(y0, y1)-reach)//cell), int((max(y0, y1)+reach)//cell)+1):
                    self.grid.setdefault((i, j), []).append(idx)

    def ceiling(self, x, y):
        best = None
        for idx in self.grid.get((int(x//self.cell), int(y//self.cell)), ()):
            x0, y0, z0, x1, y1, z1, half = self.segments[idx]
            dx, dy = x1-x0, y1-y0
            length2 = dx*dx+dy*dy
            t = 0.0 if length2 <= 1e-12 else max(0.0, min(1.0, ((x-x0)*dx+(y-y0)*dy)/length2))
            d = math.hypot(x-x0-dx*t, y-y0-dy*t)-half-self.pad
            if d > self.band:
                continue
            limit = z0+(z1-z0)*t-self.clearance+self.slope*max(0.0, d)
            best = limit if best is None else min(best, limit)
        return best

    def __call__(self, x, y):
        value = self.field(x, y)
        limit = self.ceiling(x, y)
        return value if limit is None else min(value, limit)


def stitch_vertices(polys, points, cell=20.0, tol=0.25):
    """Insert `points` that lie on a polygon boundary edge (within `tol`) as boundary
    vertices. The ground cut is the bbox minus the road surface; its draped triangles then
    carry a vertex at every road-profile station, so the rendered terrain along the seam
    follows the same piecewise-linear slope as the ribbon instead of one long chord per
    triangle row.

    A station that is truly collinear with its edge (within 1e-6) keeps its own
    coordinates; a near-but-off-boundary station is inserted as its orthogonal projection
    onto the edge, so the cut outline is subdivided but never bent by the tol tolerance
    and no hairline gap opens between the ground mesh and the ribbon."""
    if not points:
        return list(polys)
    grid = {}
    for px, py in points:
        grid.setdefault((int(px//cell), int(py//cell)), []).append((px, py))
    out = []
    for poly in polys:
        if poly.geom_type != 'Polygon' or poly.is_empty:
            out.append(poly)
            continue
        rings = []
        ring_sources = [poly.exterior, *poly.interiors]
        for source in ring_sources:
            coords = list(source.coords)[:-1]
            n = len(coords)
            if n < 3:
                continue
            new = []
            for k, (ax, ay) in enumerate(coords):
                bx, by = coords[(k+1) % n]
                new.append((ax, ay))
                dx, dy = bx-ax, by-ay
                length = math.sqrt(dx*dx+dy*dy)
                length2 = length*length
                if length2 <= 1e-12:
                    continue
                i0, j0 = int(min(ax, bx)//cell), int(min(ay, by)//cell)
                i1, j1 = int(max(ax, bx)//cell), int(max(ay, by)//cell)
                hits = []
                for i in range(i0, i1+1):
                    for j in range(j0, j1+1):
                        for px, py in grid.get((i, j), ()):
                            t = ((px-ax)*dx+(py-ay)*dy)/length2
                            if t <= 1e-9 or t >= 1-1e-9:
                                continue
                            perp = abs((px-ax)*(-dy)+(py-ay)*dx)/length
                            if perp > tol:
                                continue
                            if perp <= 1e-6:
                                # Truly on the boundary: keep the original station (knot).
                                hits.append((t, px, py))
                            else:
                                # Off the boundary but within tol: insert the projection, so
                                # the cut shape is preserved exactly and the knot still lands
                                # on the seam.
                                hits.append((t, ax+dx*t, ay+dy*t))
                hits.sort()
                last = None
                for t, px, py in hits:
                    if last is not None and math.hypot(px-last[0], py-last[1]) < 1e-6:
                        continue
                    new.append((px, py))
                    last = (px, py)
            rings.append(new)
        try:
            rebuilt = Polygon(rings[0], rings[1:])
            if rebuilt.is_valid and not rebuilt.is_empty:
                out.append(rebuilt)
            else:
                out.append(poly)
        except ValueError:
            out.append(poly)
    return out


def paths(ways, nodes, tags, to_xy, cut, ground, lift=0.05, step=3.0):
    """Decorative footways/cycleways from OSM (not simulated), draped on the ground and
    removed where they would overlap the carriageway or SUMO sidewalks."""
    out = []
    local = LocalCut(cut) if cut is not None else None
    for w in ways.values():
        t = tags(w)
        kind = t.get('highway')
        if kind not in PATH_WIDTH or t.get('area') == 'yes' or t.get('tunnel', 'no') != 'no' or t.get('bridge', 'no') != 'no':
            continue
        refs = [nd.attrib['ref'] for nd in w.findall('nd') if nd.attrib['ref'] in nodes]
        if len(refs) < 2:
            continue
        line = LineString([to_xy(*nodes[r]) for r in refs])
        if local is not None:
            line = local.subtract_from(line)
        parts = [line] if line.geom_type == 'LineString' else [g for g in getattr(line, 'geoms', []) if g.geom_type == 'LineString']
        for part in parts:
            if part.length < 2:
                continue
            count = max(1, math.ceil(part.length/step))
            pts = [part.interpolate(i/count, normalized=True) for i in range(count+1)]
            out.append({'points': [(p.x, p.y, ground(p.x, p.y)+lift) for p in pts], 'width': PATH_WIDTH[kind], 'kind': kind})
    return out
