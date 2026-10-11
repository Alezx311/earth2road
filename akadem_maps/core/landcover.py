"""Area landcover from OSM ways and multipolygon relations (playtest 2026-10-06, notes 5 and 9).

Large lakes and forests are almost always multipolygon relations; they were only read
for rural maps. Sports pitches and running tracks were drawn as plain grass or not at
all. One classifier now serves closed ways and relations in every map mode, and
overlapping areas are resolved by priority so each point of ground has one cover.
"""
import math

from shapely import STRtree
from shapely.geometry import LineString, Point, Polygon
from shapely.ops import polygonize, transform, unary_union

from . import rural
from .osm_buildings import robust, union

# Lower draws first and wins an overlap: a pond in a park, a pitch inside a track.
PRIORITY = {'water': 0, 'pitch': 1, 'track': 2, 'garden': 3, 'orchard': 4, 'farmland': 4,
            'yard': 4, 'green': 5, 'wood': 6}


def kind(tags, is_rural=False):
    if is_rural and rural.cover(tags):
        return rural.cover(tags)
    if tags.get('natural') in ('water', 'bay') or tags.get('landuse') in ('reservoir', 'basin'):
        return 'water'
    if tags.get('leisure') == 'pitch':
        return 'pitch'
    if tags.get('leisure') == 'track' and tags.get('area') != 'no':
        return 'track'
    if tags.get('landuse') == 'forest' or tags.get('natural') in ('wood', 'scrub'):
        return 'wood'
    if (tags.get('landuse') in ('grass', 'recreation_ground', 'meadow', 'village_green')
            or tags.get('natural') == 'grassland'
            or tags.get('leisure') in ('park', 'garden', 'playground')):
        return 'green'
    return None


def relation_covers(root, nodes, to_xy, clip, is_rural=False):
    """Multipolygon landcover with holes, clipped to the map area (network XY)."""
    ways = {w.get('id'): w for w in root.findall('way')}
    result = []
    for rel in root.findall('relation'):
        tags = {t.get('k'): t.get('v') for t in rel.findall('tag')}
        if tags.get('type') != 'multipolygon':
            continue
        area_kind = kind(tags, is_rural)
        if not area_kind:
            continue
        rings = {'outer': [], 'inner': []}
        for member in rel.findall('member'):
            w = ways.get(member.get('ref')) if member.get('type') == 'way' else None
            if w is None:
                continue
            refs = [n.get('ref') for n in w.findall('nd')]
            if len(refs) < 2 or any(r not in nodes for r in refs):
                continue
            rings['inner' if member.get('role') == 'inner' else 'outer'].append(LineString([nodes[r] for r in refs]))
        if not rings['outer']:
            continue
        outer = union(polygonize(union(rings['outer'])))
        inner = union(polygonize(union(rings['inner']))) if rings['inner'] else Polygon()
        if outer.is_empty:
            continue
        local = robust(lambda a, b, c: a.difference(b).intersection(c), outer, inner, clip)
        if local.is_empty:
            continue
        result.append({'id': 'relation_' + rel.get('id'), 'kind': area_kind,
                       'poly': transform(lambda x, y, z=None: to_xy(x, y), local).buffer(0),
                       'provenance': 'osm multipolygon'})
    return result


def sea(root, nodes, to_xy, clip):
    """Sea inside the map area from ``natural=coastline`` ways (lon/lat in, network XY out).

    OSM draws coastlines with the land on the left and the water on the right. The map area
    is cut by the coastline; each piece is sea when the side test of a coastline segment on
    its boundary points into it. Odesa 2026-10-11: without this the Black Sea was drawn as
    flat land."""
    lines = []
    for w in root.findall('way'):
        if not any(t.get('k') == 'natural' and t.get('v') == 'coastline' for t in w.findall('tag')):
            continue
        refs = [n.get('ref') for n in w.findall('nd')]
        if len(refs) >= 2 and all(r in nodes for r in refs):
            lines.append([nodes[r] for r in refs])
    if not lines:
        return []
    coast = robust(lambda a, b: a.intersection(b), unary_union([LineString(l) for l in lines]), clip)
    if coast.is_empty:
        return []
    segments = [(a, b) for line in lines for a, b in zip(line, line[1:]) if a != b]
    tree = STRtree([LineString(sg) for sg in segments])
    faces = list(polygonize(unary_union([clip.boundary, coast])))
    result = []
    for k, face in enumerate(faces):
        if not clip.buffer(1e-9).covers(face.representative_point()):
            continue
        ring = list(face.exterior.coords)
        water = None
        for p, q in zip(ring, ring[1:]):
            mid = ((p[0]+q[0])/2, (p[1]+q[1])/2)
            nearest = int(tree.nearest(Point(mid)))
            if tree.geometries[nearest].distance(Point(mid)) > 1e-9:
                continue
            a, b = segments[nearest]
            dx, dy = b[0]-a[0], b[1]-a[1]
            n = math.hypot(dx, dy)
            probe = Point(mid[0]+dy/n*1e-6, mid[1]-dx/n*1e-6)       # right of the coastline
            water = face.contains(probe)
            break
        if water:
            result.append({'id': f'coastline_sea_{k}', 'kind': 'water',
                           'poly': transform(lambda x, y, z=None: to_xy(x, y), face).buffer(0),
                           'provenance': 'osm natural=coastline (sea side)'})
    return result


def resolve(areas):
    """Areas sorted by priority, each minus everything drawn before it (in place: 'poly')."""
    areas = sorted(areas, key=lambda a: PRIORITY.get(a['kind'], 9))
    done = []
    for a in areas:
        poly = a['poly']
        if poly.is_empty:
            continue
        x0, y0, x1, y1 = poly.bounds
        near = [p for p in done if not (p.bounds[0] > x1 or p.bounds[2] < x0 or p.bounds[1] > y1 or p.bounds[3] < y0)]
        if near:
            poly = robust(lambda a, b: a.difference(b), poly, union(near)).buffer(0)
        a['poly'] = poly
        if not poly.is_empty:
            done.append(poly)
    return [a for a in areas if not a['poly'].is_empty]


WATER_SAMPLES = 300
WATER_PERCENTILE = 10
SHORE_STEP = 8.0


def water_level(poly, height):
    """A flat surface for a lake or river: a low percentile of the DEM inside it.

    The z12 DEM blurs steep banks into the water, so draping drew rivers up slopes
    (Khreshchatyk build, Dnipro below Volodymyrska hill). Derived, not surveyed."""
    import numpy as np
    from shapely.geometry import Point
    x0, y0, x1, y1 = poly.bounds
    step = max(4.0, math.sqrt(max(poly.area, 1.0)/WATER_SAMPLES))
    pts = [(x, y) for x in np.arange(x0+step/2, x1, step) for y in np.arange(y0+step/2, y1, step)
           if poly.contains(Point(x, y))] or [tuple(poly.representative_point().coords[0])]
    return float(np.percentile([height(x, y) for x, y in pts], WATER_PERCENTILE))


def shore(poly, level, keep_out):
    """Densified shoreline at the water level, outside ``keep_out`` (roads, decks)."""
    lines = []
    for ring in [poly.exterior, *poly.interiors]:
        line = robust(lambda a, b: a.difference(b), LineString(ring.coords), keep_out)
        for part in ([line] if line.geom_type == 'LineString' else getattr(line, 'geoms', [])):
            if part.geom_type != 'LineString' or part.length < SHORE_STEP:
                continue
            n = max(1, int(part.length/SHORE_STEP))
            pts = [part.interpolate(i*part.length/n) for i in range(n+1)]
            lines.append([(p.x, p.y, level) for p in pts])
    return lines
