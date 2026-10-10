"""What a build of an area will have to process, known before the build starts.

The picker shows an honest waiting time (akadem_maps/estimates.py). Area alone is a
poor predictor: a 500 m square of a city centre has more roads and buildings than a
2 km square of fields. These features are counted, in order of preference, from

1. a verified local OSM snapshot covering the area (``basis: osm_snapshot``),
2. one small Overpass ``out count`` request, no retries (``basis: overpass_count``),
3. nothing: area only (``basis: area_only``), with the reason.

A drawn area (cfg['area'], core/corridor.drawn_area) is counted inside its polygon.
Counts use the drivable classes of the generator (core/prepare.DRIVABLE plus links).
Overpass counts ways intersecting the bbox and road nodes inside it; the local count
approximates that with ways having a node inside. Both are density signals for a time
estimate, not geometry facts.
"""
import json
import math
from pathlib import Path
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from .context import read_json

ROAD_CLASSES = ('motorway', 'trunk', 'primary', 'secondary', 'tertiary', 'residential',
                'unclassified', 'service', 'living_street')
ROAD_REGEX = '^(' + '|'.join(ROAD_CLASSES) + ')$|_link$'
USER_AGENT = 'Earth2Road-estimate/1.0 (open-source driving sandbox)'
COUNT_TIMEOUT = 25  # s; a count query is tiny, a busy server is not waited for
FEATURES = ('area_km2', 'roads', 'road_nodes', 'buildings', 'dem_tiles', 'dem_missing', 'osm_ready')


def area_km2(geometry):
    from pyproj import Geod
    from shapely.geometry import shape
    area, _ = Geod(ellps='WGS84').geometry_area_perimeter(shape(geometry))
    return abs(area) / 1e6


def road(tags):
    highway = tags.get('highway', '')
    return highway in ROAD_CLASSES or highway.endswith('_link')


def count_osm(path, bbox, polygon=None):
    """roads / road_km / road_nodes / buildings of an OSM XML file inside bbox and the
    optional lon/lat polygon (streamed). road_km is the full length of the roads that
    touch the area, like Overpass length() on the ways it selects."""
    from shapely import contains_xy, prepare
    w, s, e, n = bbox
    if polygon is not None:
        prepare(polygon)
    where, inside = {}, set()
    roads = buildings = 0
    road_m = 0.0
    road_nodes = set()
    for _, elem in ET.iterparse(path, events=('end',)):
        if elem.tag == 'node':
            nid, lon, lat = elem.get('id'), float(elem.get('lon')), float(elem.get('lat'))
            where[nid] = complex(lon, lat)
            if w <= lon <= e and s <= lat <= n and (polygon is None or contains_xy(polygon, lon, lat)):
                inside.add(nid)
            elem.clear()
        elif elem.tag == 'way':
            refs = [nd.get('ref') for nd in elem.findall('nd')]
            tags = {t.get('k'): t.get('v') for t in elem.findall('tag')}
            hit = [r for r in refs if r in inside]
            if hit:
                if road(tags):
                    roads += 1
                    road_nodes.update(hit)
                    points = [where[r] for r in refs if r in where]
                    road_m += sum(metres(a, b) for a, b in zip(points, points[1:]))
                elif 'building' in tags:
                    buildings += 1
            elem.clear()
        elif elem.tag == 'relation':
            elem.clear()
    return {'roads': roads, 'road_km': round(road_m / 1000, 3), 'road_nodes': len(road_nodes),
            'buildings': buildings}


def metres(a, b):
    """Equirectangular distance between lon+lat*1j points; metre-accurate at road scale."""
    return math.hypot((b.real - a.real) * 111320 * math.cos(math.radians(a.imag)), (b.imag - a.imag) * 110574)


def count_query(bbox, timeout=COUNT_TIMEOUT, polygon=None, length=True):
    """One request: road count and length (make stat), road nodes, buildings.
    Only the default set is used; length=False drops the stat for servers without it."""
    w, s, e, n = bbox
    b = f'{s},{w},{n},{e}'
    if polygon is not None:
        b = 'poly:"' + ' '.join(f'{lat:.6f} {lon:.6f}' for lon, lat in polygon.exterior.coords[:-1]) + '"'
    roads = f'way["highway"~"{ROAD_REGEX}"]({b});'
    first = roads + ('make stat roads=count(ways),road_m=sum(length());out;' if length else 'out count;')
    return (f'[out:json][timeout:{timeout}];' + first +
            roads + f'node(w)({b});out count;'
            f'way["building"]({b});out count;')


def parse_counts(document):
    elements = document.get('elements', [])
    counts = [e['tags'] for e in elements if e.get('type') == 'count']
    stats = [e['tags'] for e in elements if e.get('type') == 'stat']
    if stats and len(counts) == 2:
        return {'roads': int(float(stats[0]['roads'])), 'road_km': round(float(stats[0]['road_m']) / 1000, 3),
                'road_nodes': int(counts[0]['nodes']), 'buildings': int(counts[1]['ways'])}
    if len(counts) == 3:
        return {'roads': int(counts[0]['ways']), 'road_nodes': int(counts[1]['nodes']),
                'buildings': int(counts[2]['ways'])}
    raise ValueError('Unexpected Overpass count response')


def count_overpass(url, bbox, polygon=None, timeout=COUNT_TIMEOUT):
    def ask(length):
        data = ('data=' + urllib.parse.quote(count_query(bbox, timeout, polygon, length))).encode()
        request = urllib.request.Request(url, data=data, headers={'User-Agent': USER_AGENT})
        with urllib.request.urlopen(request, timeout=timeout + 5) as response:
            return parse_counts(json.load(response))
    try:
        return ask(True)
    except urllib.error.HTTPError as exc:
        if exc.code != 400:
            raise
        # A server that rejects the length statistic still answers plain counts;
        # road length is then estimated from the node count (estimates.term_values).
        return ask(False)


def terrain(cfg, raw):
    """DEM tiles the bbox needs (without the way-envelope extension) and how many are missing."""
    from .offline import terrain_keys, valid_tile
    keys = terrain_keys(cfg, ET.Element('osm'))
    return len(keys), sum(not valid_tile(Path(raw) / key) for key in keys)


def probe(cfg, raw, *, offline=False, counter=count_overpass):
    """Features of cfg['bbox'] for the estimate; never raises for a missing source."""
    from shapely.geometry import box, mapping, shape
    from .sources import area_key, coverage, snapshots
    bbox = cfg['bbox']
    geometry = coverage(cfg) if 'area' in cfg else mapping(box(*bbox))
    polygon = shape(geometry) if 'area' in cfg else None
    raw = Path(raw)
    result = {'area_km2': round(area_km2(geometry), 4), 'osm_ready': False, 'basis': 'area_only', 'note': ''}
    result['dem_tiles'], result['dem_missing'] = terrain(cfg, raw)
    cache = raw / 'estimates' / (area_key(geometry) + '.json')
    try:
        found = snapshots(raw, geometry)
    except Exception:  # a damaged snapshot only means "not ready"
        found = []
    if found:
        result.update(count_osm(found[0][0], bbox, polygon), osm_ready=True, basis='osm_snapshot')
    elif cache.exists():
        try:
            cached = read_json(cache)
            result.update({k: cached[k] for k in ('roads', 'road_km', 'road_nodes', 'buildings') if k in cached},
                          basis=cached['basis'])
        except (OSError, ValueError, KeyError):
            pass
    if result['basis'] == 'area_only':
        if offline:
            result['note'] = 'offline and no local OSM snapshot: area only'
        else:
            urls = [cfg.get('overpass')] + list(cfg.get('overpass_mirrors', []))
            for url in [u for u in urls if u]:
                try:
                    counts = counter(url, bbox, polygon) if polygon is not None else counter(url, bbox)
                    result.update(counts, basis='overpass_count')
                    break
                except urllib.error.HTTPError as exc:
                    # 429/504: the server asked us to back off; do not hammer a mirror chain.
                    result['note'] = f'Overpass HTTP {exc.code}: area only'
                    break
                except (OSError, ValueError) as exc:
                    result['note'] = f'Overpass unavailable ({type(exc).__name__}): area only'
    if result['basis'] != 'area_only' and not found:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps({k: result[k] for k in ('roads', 'road_km', 'road_nodes', 'buildings', 'basis')
                                     if k in result}),
                         encoding='utf8')
    return result
