"""Map area: the config bbox rectangle, or a corridor buffered around named OSM roads.

Config key ``corridor``::

    {"axis": {"names": [...], "highway": ["trunk"]}, "buffer_m": 500, "lat_range": [south, north]}

The axis is every OSM way whose name is listed and whose highway class matches, clipped
to ``lat_range``. The polygon is that axis buffered by ``buffer_m`` in local metres. It is
derived once from the dated Geofabrik extract and cached with its inputs in
data/build/<id>/corridor.geojson, so later stages never read the pbf again. The corridor
is a working area around a road, not an administrative boundary.

Maps without ``corridor`` keep the plain bbox rectangle, unchanged.
"""
import hashlib
import json
import math
from pathlib import Path

import shapely
from shapely.geometry import LineString, Polygon, box, mapping, shape
from shapely.ops import transform, unary_union



ROOT = Path(__file__).resolve().parents[2]
SIMPLIFY_M = 5.0      # polygon vertex tolerance; netconvert gets the boundary as a list


def shaped(cfg):
    return 'corridor' in cfg or 'boundary' in cfg


def boundary_area(cfg, context=None):
    """Reviewed settlement outline + outward metric buffer. Never a centre radius.

    boundary: {geojson: repo-relative FeatureCollection, buffer_m: metres}.
    The source feature has role=settlement; the resulting playable area has no holes.
    """
    from pyproj import CRS, Transformer
    spec = cfg['boundary']
    doc = json.loads((context.config_file(spec['geojson']) if context else ROOT / spec['geojson']).read_text(encoding='utf8'))
    polygons = [shape(f['geometry']) for f in doc['features']
                if f.get('properties', {}).get('role') == 'settlement']
    if not polygons or any(not p.is_valid or p.is_empty or p.geom_type not in ('Polygon', 'MultiPolygon') for p in polygons):
        raise ValueError('boundary requires valid settlement polygons')
    outline = unary_union(polygons)
    lon, lat = outline.centroid.coords[0]
    crs = CRS.from_proj4(f'+proj=aeqd +lat_0={lat} +lon_0={lon} +datum=WGS84 +units=m')
    forward = Transformer.from_crs(4326, crs, always_xy=True).transform
    reverse = Transformer.from_crs(crs, 4326, always_xy=True).transform
    distance = float(spec['buffer_m'])
    if not math.isfinite(distance) or distance < 0:
        raise ValueError('boundary buffer_m must be finite and nonnegative')
    # Circumscribed approximation: even midway between arc vertices the buffer
    # covers the requested radius (ordinary GEOS buffers inscribe their arcs).
    # 10 cm also covers projection/arc chord error at this village scale.
    distance = (distance + 0.1) / math.cos(math.pi / 256) if distance else 0.0
    buffered = transform(forward, outline).buffer(distance, quad_segs=64)
    if buffered.geom_type != 'Polygon':
        raise ValueError('settlement buffer must form one connected playable area')
    return transform(reverse, Polygon(buffered.exterior))


def area_digest(cfg, context=None):
    if 'boundary' in cfg:
        source = (context.config_file(cfg['boundary']['geojson']) if context else ROOT / cfg['boundary']['geojson']).read_bytes()
        return hashlib.sha256(source + json.dumps(cfg['boundary'], sort_keys=True).encode()
                              + cfg.get('geofabrik', {}).get('md5', '').encode()).hexdigest()
    if cfg.get('corridor') and cfg.get('geofabrik'):
        return spec_digest(cfg['corridor'], cfg['geofabrik']['md5'])
    return None


class Local:
    """Equirectangular metres around (lon0, lat0); corridor-scale error is centimetres."""

    def __init__(self, lon0, lat0):
        self.lon0, self.lat0 = lon0, lat0
        self.kx = 111320.0 * math.cos(math.radians(lat0))
        self.ky = 110540.0

    def to_xy(self, lon, lat):
        return (lon - self.lon0) * self.kx, (lat - self.lat0) * self.ky

    def to_lonlat(self, x, y):
        return self.lon0 + x / self.kx, self.lat0 + y / self.ky


def spec_digest(spec, pbf_md5):
    return hashlib.sha256(json.dumps([spec, pbf_md5], sort_keys=True, ensure_ascii=False).encode('utf8')).hexdigest()


def axis_ways(pbf, spec):
    """[(way id, name, [(lon, lat), ...])] for the named axis roads in the pbf."""
    import osmium
    axes = spec.get('axes', [spec.get('axis', {})])
    names = {name for axis in axes for name in axis['names']}
    found = []
    for obj in osmium.FileProcessor(str(pbf)).with_locations().with_filter(osmium.filter.KeyFilter('highway')):
        if not obj.is_way() or obj.tags.get('name') not in names:
            continue
        if not any(obj.tags.get('name') in axis['names'] and
                   (not axis.get('highway') or obj.tags.get('highway') in axis['highway']) for axis in axes):
            continue
        points = [(nd.location.lon, nd.location.lat) for nd in obj.nodes if nd.location.valid()]
        if len(points) >= 2:
            found.append((obj.id, obj.tags.get('name'), points))
    return sorted(found)


def polygon_from_axes(ways, spec):
    """Union separately bounded axes; legacy one-axis specs retain exact behaviour.

    `clip_bbox` bounds an avenue at its OSM-verified terminal junctions before the
    scenery buffer is applied. Every matching carriageway is retained.
    """
    if 'axes' not in spec:
        area, axis = polygon_from_axis(ways, float(spec['buffer_m']), spec['lat_range'])
        return include_areas(area, spec), axis
    areas, lines = [], []
    for axis in spec['axes']:
        selected = [w for w in ways if w[1] in axis['names']]
        if axis.get('clip_bbox'):
            clipped = []
            for wid, name, points in selected:
                geom = LineString(points).intersection(box(*axis['clip_bbox']))
                for part in getattr(geom, 'geoms', [geom]):
                    if part.geom_type == 'LineString' and not part.is_empty:
                        clipped.append((wid, name, list(part.coords)))
            selected = clipped
        area, line = polygon_from_axis(selected, float(spec['buffer_m']),
                                       axis.get('lat_range', [-90, 90]))
        areas.append(area)
        lines.append(line)
    area = unary_union(areas)
    if area.geom_type != 'Polygon':
        raise ValueError('Corridor branches do not connect')
    return include_areas(Polygon(area.exterior), spec), unary_union(lines)


def validate_includes(spec):
    includes = spec.get('include_bboxes', [])
    if not isinstance(includes, list):
        raise ValueError('corridor.include_bboxes must be a list of bboxes')
    for bounds in includes:
        if (not isinstance(bounds, (list, tuple)) or len(bounds) != 4 or
            any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in bounds)):
            raise ValueError('include_bboxes entries require four finite numbers')
        w, s, e, n = bounds
        if not (-180 <= w < e <= 180 and -85 < s < n < 85):
            raise ValueError('Invalid include_bboxes bounds')
    return includes


def include_areas(area, spec):
    """Union with explicitly included areas, never the bounding rectangle."""
    boxes = validate_includes(spec)
    if not boxes:
        return area
    result = unary_union([area, *(box(*bounds) for bounds in boxes)])
    if result.geom_type != 'Polygon':
        raise ValueError('Included areas must connect to the corridor')
    return result


def polygon_from_axis(ways, buffer_m, lat_range):
    """Buffered union of the axis clipped to lat_range, as a lon/lat Polygon."""
    south, north = lat_range
    lines = [LineString(points) for _wid, _name, points in ways]
    band = box(-180, south, 180, north)
    axis = unary_union([line.intersection(band) for line in lines])
    if axis.is_empty:
        raise ValueError('Corridor axis is empty: no named way inside lat_range')
    lon0, lat0 = axis.centroid.x, axis.centroid.y
    local = Local(lon0, lat0)
    metric = transform(lambda x, y, z=None: local.to_xy(x, y), axis)
    area = metric.buffer(buffer_m, quad_segs=8).simplify(SIMPLIFY_M)
    if area.geom_type != 'Polygon':
        raise ValueError(f'Corridor is {area.geom_type}; the axis has a gap wider than 2 x buffer')
    # Holes would be enclosed pockets of the map with no scenery; fill them.
    area = Polygon(area.exterior)
    return (transform(lambda x, y, z=None: local.to_lonlat(x, y), area),
            transform(lambda x, y, z=None: local.to_lonlat(x, y), metric))


def bounds(polygon):
    """Outward-rounded [west, south, east, north] at 1e-4 deg."""
    w, s, e, n = polygon.bounds
    return [math.floor(w * 1e4) / 1e4, math.floor(s * 1e4) / 1e4, math.ceil(e * 1e4) / 1e4, math.ceil(n * 1e4) / 1e4]


def cache_path(cfg, context=None):
    return (context.build if context else ROOT / 'data/build' / cfg['id']) / 'corridor.geojson'


def build(cfg, pbf, context=None):
    """Derive the corridor from the pbf and cache it. Returns the lon/lat Polygon."""
    spec = cfg['corridor']
    ways = axis_ways(pbf, spec)
    polygon, axis = polygon_from_axes(ways, spec)
    area_m2 = transform(lambda x, y, z=None: Local(*polygon.centroid.coords[0]).to_xy(x, y), polygon).area
    document = {'type': 'FeatureCollection', 'digest': spec_digest(spec, cfg['geofabrik']['md5']),
                'spec': spec, 'source': cfg['geofabrik']['url'],
                'note': 'Working corridor around the named roads; not an administrative boundary.',
                'features': [
                    {'type': 'Feature', 'properties': {'role': 'area', 'area_km2': round(area_m2 / 1e6, 3)},
                     'geometry': mapping(polygon)},
                    {'type': 'Feature', 'properties': {'role': 'axis', 'osm_ways': [w for w, _n, _p in ways]},
                     'geometry': mapping(axis)}]}
    path = cache_path(cfg, context)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, ensure_ascii=False), encoding='utf8')
    return polygon


def load(cfg, context=None):
    """Cached corridor (area Polygon, axis geometry), or None if missing or stale."""
    path = cache_path(cfg, context)
    if not path.exists():
        return None
    document = json.loads(path.read_text(encoding='utf8'))
    if document.get('digest') != spec_digest(cfg['corridor'], cfg['geofabrik']['md5']):
        return None
    geometry = {f['properties']['role']: shape(f['geometry']) for f in document['features']}
    return geometry['area'], geometry['axis']


def area(cfg, pbf=None, context=None):
    """lon/lat Polygon of the map. Sets cfg['bbox'] from a corridor when it has none."""
    if 'boundary' in cfg:
        if 'corridor' in cfg:
            raise ValueError('boundary and corridor are mutually exclusive')
        polygon = boundary_area(cfg, context)
        cfg['bbox'] = bounds(polygon)
        return polygon
    if 'corridor' not in cfg:
        return box(*cfg['bbox'])
    cached = load(cfg, context)
    if cached is None:
        if pbf is None:
            pbf = (context.raw if context else ROOT / 'data/raw') / 'geofabrik' / cfg['geofabrik']['url'].rsplit('/', 1)[1]
            if context and not pbf.exists():
                context.download(cfg['geofabrik']['url'], pbf, max_time=3600)
        polygon = build(cfg, pbf, context)
    else:
        polygon = cached[0]
    cfg['bbox'] = bounds(polygon)  # A stored bbox must not truncate newly included areas.
    return polygon


def geo_boundary(polygon):
    """netconvert --keep-edges.in-geo-boundary value: lon,lat pairs of the exterior ring."""
    return ','.join(f'{x:.6f},{y:.6f}' for x, y in polygon.exterior.coords)


def contains(polygon):
    """Fast vectorised point test f(lon, lat) -> bool for a prepared polygon."""
    shapely.prepare(polygon)
    return lambda lon, lat: bool(shapely.contains_xy(polygon, lon, lat))


def to_net(polygon, net):
    """The lon/lat polygon in SUMO network XY."""
    return Polygon([net.convertLonLat2XY(x, y) for x, y in polygon.exterior.coords])
