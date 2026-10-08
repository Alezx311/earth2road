"""OSM building facts beyond plain closed ways (playtest 2026-10-06, notes 7, 9, 10).

* Multipolygon relations become ordinary footprints; courtyards are kept by
  splitting the outline into hole-free pieces that share the relation's ID.
* Simple 3D Buildings: an outline whose area is mostly covered by
  ``building:part`` items is not drawn; the parts inherit its colours and one
  style key, so a church is not assembled from unrelated facades.
* Observed ``building:colour``/``roof:colour`` and supported ``roof:shape``
  values are rendered in every map mode, not only with Local Visual DNA.
* Roof solids (pyramidal, hipped, dome, onion) are derived geometry within
  the exact footprint; ``roof:height`` is used when tagged.
* Small kiosks get one storey; footprints over the carriageway are clipped or
  dropped and reported, so nothing stands on a driving surface.

Coordinates of render items are world X/Y/Z metres (Y up); footprints for
geometry tests are network XY metres.
"""
import math

from shapely.geometry import LineString, MultiPolygon, Point, Polygon
from shapely.ops import polygonize, unary_union

from . import local_dna

SHAPED_ROOFS = ('pyramidal', 'hipped', 'dome', 'onion')
# (ring scale, fraction of roof height): rings shrink monotonically, so every face
# points up and one-sided roof materials stay visible. The onion is the pointed,
# slightly swollen silhouette without an overhanging bulb.
PROFILES = {
    'pyramidal': [(1.0, 0.0), (0.0, 1.0)],
    'dome': [(math.cos(a), math.sin(a)) for a in (i*math.pi/12 for i in range(6))] + [(0.0, 1.0)],
    'onion': [(1.0, 0.0), (0.97, 0.22), (0.86, 0.45), (0.62, 0.66), (0.32, 0.83), (0.1, 0.94), (0.0, 1.0)],
}
PUBLIC_TYPES = {'church', 'cathedral', 'chapel', 'temple', 'mosque', 'synagogue', 'monastery',
                'civic', 'public', 'government', 'train_station', 'university', 'school',
                'college', 'museum', 'theatre', 'hospital'}
INDUSTRIAL_TYPES = {'industrial', 'warehouse', 'hangar', 'garages', 'garage', 'shed', 'service'}
APPEARANCE = ('building:colour', 'building:color', 'roof:colour', 'roof:color', 'building:material')
KIOSK_AREA_M2 = 40.0
BOOTH_AREA_M2 = 25.0
# Drop instead of clipping: most of a footprint on the carriageway, or a small one
# (kiosk, passage piece) substantially on it. Large buildings are only clipped.
DROP_SHARE = 0.6
SMALL_AREA_M2 = 60.0
SMALL_DROP_SHARE = 0.3
MIN_OVERLAP_M2 = 0.5


ROBUST_GRIDS = (1e-3, 1e-2)  # m


def robust(fn, *geoms):
    """Run a shapely operation; on a GEOS error retry on repaired geometry: made valid,
    then snapped to 1 mm and 1 cm grids, then buffer(0) (an invalid OSM ring must not stop
    a 40-minute build). Every repair step is guarded, since set_precision itself can raise.
    If all fail, the inputs are written as WKB to $AKADEM_MAPS_GEOS_DUMP (when set): a
    failure seen only on a full-size map then reproduces in seconds."""
    from shapely import make_valid, set_precision
    from shapely.errors import GEOSException
    try:
        return fn(*geoms)
    except GEOSException as error:
        first = error
    steps = [lambda g: make_valid(g)]
    steps += [lambda g, grid=grid: set_precision(make_valid(g), grid) for grid in ROBUST_GRIDS]
    steps += [lambda g: make_valid(g).buffer(0)]
    for step in steps:
        try:
            return fn(*(step(g) for g in geoms))
        except GEOSException:
            continue
    _dump_geometries(geoms)
    raise first


def _dump_geometries(geoms):
    import os
    import time
    folder = os.environ.get('AKADEM_MAPS_GEOS_DUMP')
    if not folder:
        return
    from pathlib import Path
    path = Path(folder)/f'robust-{time.strftime("%Y%m%d-%H%M%S")}-{os.getpid()}'
    path.mkdir(parents=True, exist_ok=True)
    for k, g in enumerate(geoms):
        (path/f'{k}.wkb').write_bytes(g.wkb)


def union(geoms):
    geoms = list(geoms)
    return robust(lambda *g: unary_union(list(g)), *geoms) if geoms else Polygon()


LOCAL_CELL = 200.0  # m


class LocalArea:
    """A large area cut once into grid cells; ``within`` returns its part inside a box.

    Detroit 4 km (07.10.2026): buffering or unioning the whole city carriageway once per
    sidewalk or house stalled the build for hours. Operations that only depend on the
    area near a small shape give the same result on a window with a sufficient margin."""

    def __init__(self, area, cell=LOCAL_CELL):
        from shapely.geometry import box
        self.cell, self.pieces = cell, {}
        if area.is_empty:
            return
        x0, y0, x1, y1 = area.bounds
        for i in range(math.floor(x0/cell), math.floor(x1/cell)+1):
            for j in range(math.floor(y0/cell), math.floor(y1/cell)+1):
                piece = robust(lambda a, b: a.intersection(b), area, box(i*cell, j*cell, (i+1)*cell, (j+1)*cell))
                if not piece.is_empty:
                    self.pieces[i, j] = piece

    def within(self, x0, y0, x1, y1):
        from shapely.geometry import box
        c = self.cell
        parts = [self.pieces[i, j] for i in range(math.floor(x0/c), math.floor(x1/c)+1)
                 for j in range(math.floor(y0/c), math.floor(y1/c)+1) if (i, j) in self.pieces]
        return robust(lambda a, b: a.intersection(b), union(parts), box(x0, y0, x1, y1)) if parts else Polygon()

    def nearest(self, point, start=50.0):
        """Nearest point of the area to ``point`` (None if empty): grow a window until a hit
        lies within its radius, which makes it the global nearest point."""
        from shapely.ops import nearest_points
        if not self.pieces:
            return None
        r = start
        while True:
            near = self.within(point.x-r, point.y-r, point.x+r, point.y+r)
            if not near.is_empty:
                hit = nearest_points(point, near)[1]
                if hit.distance(point) <= r:
                    return hit
            if r > 1e6:
                return None
            r *= 2


def number(value):
    try:
        return float(str(value).split()[0].replace(',', '.'))
    except (TypeError, ValueError, IndexError):
        return None


def relation_footprints(root, nodes):
    """(id, tags, lon/lat Polygon|MultiPolygon) of building multipolygon relations."""
    ways = {w.get('id'): w for w in root.findall('way')}
    result = []
    for rel in root.findall('relation'):
        tags = {t.get('k'): t.get('v') for t in rel.findall('tag')}
        if tags.get('type') != 'multipolygon' or not ('building' in tags or 'building:part' in tags):
            continue
        rings = {'outer': [], 'inner': []}
        for m in rel.findall('member'):
            w = ways.get(m.get('ref')) if m.get('type') == 'way' else None
            if w is None:
                continue
            refs = [n.get('ref') for n in w.findall('nd')]
            if len(refs) < 2 or any(r not in nodes for r in refs):
                continue
            rings['inner' if m.get('role') == 'inner' else 'outer'].append(LineString([nodes[r] for r in refs]))
        outer = unary_union(list(polygonize(unary_union(rings['outer'])))) if rings['outer'] else Polygon()
        inner = unary_union(list(polygonize(unary_union(rings['inner'])))) if rings['inner'] else Polygon()
        shape = robust(lambda a, b: a.difference(b), outer, inner).buffer(0) if not outer.is_empty else outer
        if not shape.is_empty:
            result.append(('r' + rel.get('id'), tags, shape))
    return result


def polygons(shape):
    if shape.is_empty:
        return []
    if isinstance(shape, Polygon):
        return [shape]
    if isinstance(shape, MultiPolygon):
        return list(shape.geoms)
    return [g for g in getattr(shape, 'geoms', []) if isinstance(g, Polygon)]


def hole_free(poly, depth=0, min_area=None):
    """Hole-free pieces covering ``poly``: cut through each courtyard and recurse.
    Slivers below 1e-4 of the outline are dropped; relative, because callers pass lon/lat
    (a school is ~5e-7 deg²) as well as metres."""
    if not poly.interiors or depth > 12:
        return [Polygon(poly.exterior)]
    if min_area is None:
        min_area = Polygon(poly.exterior).area*1e-4
    hole = Polygon(poly.interiors[0])
    x = hole.representative_point().x
    _, y0, _, y1 = poly.bounds
    left = Polygon([(poly.bounds[0]-1, y0-1), (x, y0-1), (x, y1+1), (poly.bounds[0]-1, y1+1)])
    out = []
    for half in (robust(lambda a, b: a.intersection(b), poly, left), robust(lambda a, b: a.difference(b), poly, left)):
        for piece in polygons(half.buffer(0)):
            if piece.area > min_area:
                out += hole_free(piece, depth+1, min_area)
    return out


def assumed_levels(tags, area_m2, default):
    """One storey for kiosks and booths that OSM gives no height or levels."""
    if tags.get('building') in ('kiosk', 'booth') or tags.get('shop') == 'kiosk' or tags.get('amenity') == 'kiosk':
        return 1
    if area_m2 < KIOSK_AREA_M2 and ('shop' in tags or 'amenity' in tags):
        return 1
    if area_m2 < BOOTH_AREA_M2:
        return 1
    return default


def family(tags, parent_tags=None):
    kind = tags.get('building') if tags.get('building') not in (None, 'yes', 'part') else None
    kind = kind or (parent_tags or {}).get('building', '')
    if kind in PUBLIC_TYPES or tags.get('amenity') == 'place_of_worship' or (parent_tags or {}).get('amenity') == 'place_of_worship':
        return 'historic'
    if kind in INDUSTRIAL_TYPES:
        return 'industrial'
    if kind in ('apartments', 'residential', 'dormitory'):
        return 'panel'
    if kind in ('commercial', 'retail', 'office', 'supermarket'):
        return 'modern'
    return 'brick'


DEFAULT_MATERIAL = {'historic': 'plaster', 'panel': 'concrete', 'modern': 'glass', 'industrial': 'metal', 'brick': 'brick'}


def observed(tags, parent_tags=None):
    """Value of an appearance tag on the part, else on its outline."""
    parent_tags = parent_tags or {}
    def get(*keys):
        for source in (tags, parent_tags):
            for k in keys:
                if source.get(k):
                    return source[k]
        return None
    return {'color': get('building:colour', 'building:color'), 'roof_color': get('roof:colour', 'roof:color'),
            'material': get('building:material'), 'roof': tags.get('roof:shape')}


def wants_style(tags, parent_tags=None):
    o = observed(tags, parent_tags)
    return bool(o['color'] or o['roof_color'] or o['roof'] in SHAPED_ROOFS or parent_tags is not None)


def observe(b, tags, parent_tags=None):
    """OSM-observed appearance for a building without a grammar style.

    Unknown properties fall back to a type-derived family; provenance says so.
    """
    o = observed(tags, parent_tags)
    fam = family(tags, parent_tags)
    material = o['material'] or DEFAULT_MATERIAL[fam]
    origin = {'architecture': 'derived:osm_building_type', 'material': 'osm' if o['material'] else 'derived:osm_building_type',
              'color': 'osm' if o['color'] else 'default', 'roof': 'osm' if o['roof'] else 'default',
              'levels': 'osm' if 'building:levels' in tags else b.get('height_source', 'assumed')}
    color = local_dna.colour(o['color']) if o['color'] else None
    if o['color'] and not color:
        origin['color'] = 'unsupported:osm'
    b['local_style'] = {'version': 1, 'architecture': fam, 'material': material, 'color': color,
                        'roof': o['roof'] or 'flat', 'provenance': origin, 'influences': []}
    if o['color']:
        b['local_style']['observed_color'] = o['color']
    b['visual_family'] = local_dna.VISUAL_FAMILY[fam]
    b['visual_source'] = 'osm appearance tags; see local_style.provenance'


def roof_colour(b, tags, parent_tags=None):
    value = observed(tags, parent_tags)['roof_color']
    hexa = local_dna.colour(value) if value else None
    if hexa:
        b['roof_color'] = hexa


def _star(poly, c):
    """Every footprint edge sees the apex: a fan from c covers the footprint exactly."""
    pts = list(poly.exterior.coords)[:-1]
    areas = [((a[0]-c[0])*(b[1]-c[1])-(b[0]-c[0])*(a[1]-c[1]))/2 for a, b in zip(pts, pts[1:]+pts[:1])]
    sign = 1 if sum(areas) > 0 else -1
    return all(a*sign > -1e-6 for a in areas) and abs(abs(sum(areas))-poly.area) < 0.01*poly.area


def _default_rise(shape, poly):
    rect = poly.minimum_rotated_rectangle
    ring = list(rect.exterior.coords)
    sides = sorted(math.dist(a, b) for a, b in zip(ring, ring[1:]))
    short = sides[0] if sides else 1.0
    return {'dome': short*0.5, 'onion': short*1.1, 'pyramidal': short*0.35, 'hipped': min(2.6, short*0.35)}[shape]


def shaped_roof(b, shape, roof_height=None):
    """Roof solid within the exact footprint; total height is preserved. Returns a fallback reason or None."""
    pts = b['points']
    poly = Polygon([(p[0], p[2]) for p in pts])
    if not poly.is_valid or poly.area < 2:
        return 'flat: invalid or tiny footprint'
    floor = min(p[1] for p in pts)
    base = float(b.get('base', 0))
    rise = roof_height if roof_height and roof_height > 0 else _default_rise(shape, poly)
    rise = max(0.3, min(rise, (b['height']-base)*0.85 if b['height'] > base else 0.3))
    wall = b['height'] - rise
    if wall < base + 0.2:
        return 'flat: no wall height left under the roof'
    top = floor + wall
    c = (poly.centroid.x, poly.centroid.y)
    ring = [(p[0], p[2]) for p in pts]
    if Polygon(ring).exterior.is_ccw is False:
        ring.reverse()
    tris = []
    if shape == 'hipped' and len(ring) == 4 and poly.convex_hull.area - poly.area < 0.02*poly.area:
        rect = poly.minimum_rotated_rectangle
        rr = list(rect.exterior.coords)[:4]
        e0, e1 = (rr[1][0]-rr[0][0], rr[1][1]-rr[0][1]), (rr[2][0]-rr[1][0], rr[2][1]-rr[1][1])
        long_, short = (e0, e1) if math.hypot(*e0) >= math.hypot(*e1) else (e1, e0)
        length, width = math.hypot(*long_), math.hypot(*short)
        ax = (long_[0]/length, long_[1]/length)
        hl = max(0.0, (length-width)/2)
        ends = [(c[0]-ax[0]*hl, c[1]-ax[1]*hl), (c[0]+ax[0]*hl, c[1]+ax[1]*hl)]
        def near(p):
            return ends[0] if (p[0]-c[0])*ax[0]+(p[1]-c[1])*ax[1] < 0 else ends[1]
        lift = lambda p, h: [round(p[0], 3), round(h, 3), round(p[1], 3)]
        for p, q in zip(ring, ring[1:]+ring[:1]):
            d = (q[0]-p[0], q[1]-p[1])
            along = abs(d[0]*ax[0]+d[1]*ax[1]) > abs(-d[0]*ax[1]+d[1]*ax[0])
            rp, rq = (near(p), near(q)) if along else ((near(((p[0]+q[0])/2, (p[1]+q[1])/2)),)*2)
            tris.append([lift(p, top), lift(q, top), lift(rq, top+rise)])
            if rp != rq:
                tris.append([lift(p, top), lift(rq, top+rise), lift(rp, top+rise)])
    else:
        if not _star(poly, c):
            return 'flat: footprint not star-shaped from its centroid'
        profile = PROFILES['pyramidal' if shape == 'hipped' else shape]
        rings = [[[round(c[0]+(x-c[0])*s, 3), round(top+rise*f, 3), round(c[1]+(z-c[1])*s, 3)] for x, z in ring]
                 for s, f in profile]
        for lo, hi, (s_hi, _) in zip(rings, rings[1:], profile[1:]):
            n = len(lo)
            for i in range(n):
                j = (i+1) % n
                tris.append([lo[i], lo[j], hi[j]])
                if s_hi > 0:
                    tris.append([lo[i], hi[j], hi[i]])
    b['floor_height'] = floor
    b['wall_height'] = wall
    b['roof_triangles'] = tris
    b['roof_gables'] = []
    b['roof_shape_rendered'] = shape
    return None


def apply_parts(items, footprints, counts):
    """Hide S3DB outlines covered by their parts; parts inherit the outline's facts.

    ``items`` are render items with ``_tags``/``_part`` markers; ``footprints`` maps
    id(item) to its network-XY polygon. Returns the items to keep.
    """
    from shapely import STRtree
    parts = [b for b in items if b['_part']]
    if not parts:
        return items
    part_polys = [footprints[id(b)] for b in parts]
    tree = STRtree(part_polys)
    dropped = set()
    for b in items:
        if b['_part'] or 'building' not in b['_tags']:
            continue
        outline = footprints[id(b)]
        inside = [int(k) for k in tree.query(outline)
                  if outline.contains(part_polys[int(k)].representative_point())]
        if not inside:
            continue
        covered = robust(lambda a, b: a.intersection(b), union(part_polys[k] for k in inside), outline).area
        for k in inside:
            p = parts[k]
            if '_parent' not in p or footprints[id(p['_parent'])].area > outline.area:
                p['_parent'] = b
        if covered >= 0.5*outline.area:
            dropped.add(id(b))
    counts['s3db_outlines_hidden'] += len(dropped)
    counts['s3db_parts'] += len(parts)
    return [b for b in items if id(b) not in dropped]


def clear_carriageway(items, footprints, carriageway, to_world, to_lonlat, counts, audit):
    """Clip or drop footprints standing on the carriageway (not under a deck, not raised)."""
    from shapely import STRtree
    if carriageway.is_empty:
        return items
    pieces = polygons(carriageway)
    tree = STRtree(pieces)
    out = []
    for b in items:
        fp = footprints.get(id(b))
        if fp is None or b.get('base', 0) or fp.area <= 0:
            out.append(b)
            continue
        hits = [pieces[int(k)] for k in tree.query(fp) if pieces[int(k)].intersects(fp)]
        blocked = union(hits) if hits else Polygon()
        overlap = robust(lambda a, b: a.intersection(b), blocked, fp).area if hits else 0.0
        if overlap < MIN_OVERLAP_M2:
            out.append(b)
            continue
        c = fp.centroid
        lon, lat = to_lonlat(c.x, c.y)
        record = {'id': str(b['id']), 'lonlat': [round(lon, 7), round(lat, 7)], 'area_m2': round(fp.area, 1),
                  'overlap_m2': round(overlap, 1)}
        rest = [p for g in polygons(robust(lambda a, b: a.difference(b), fp, blocked).buffer(0)) for p in hole_free(g) if p.area >= 2]
        share = overlap/fp.area
        if share > DROP_SHARE or (fp.area < SMALL_AREA_M2 and share > SMALL_DROP_SHARE) or not rest:
            record['action'] = 'dropped'
            counts['buildings_on_carriageway_dropped'] += 1
        else:
            record['action'] = 'clipped'
            counts['buildings_on_carriageway_clipped'] += 1
            for poly in rest:
                piece = {k: v for k, v in b.items() if k not in ('roof_triangles', 'roof_gables', 'roof_shape_rendered')}
                piece['points'] = [to_world(x, y) for x, y in list(poly.exterior.coords)[:-1]]
                footprints[id(piece)] = poly
                out.append(piece)
        audit.append(record)
    return out
