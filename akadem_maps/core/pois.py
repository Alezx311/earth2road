"""Quick-travel points: fuel stations and large shops from OSM, placed on a nearby lane.

Candidates are OSM nodes or ways tagged as in osm_extract.POI_TAGS whose position lies in
the map area. Each kept point gets a spawn position on the rightmost lane of the nearest
ordinary road (not a yard, bridge or short stub), facing along that lane. The player
starts on the road beside the station, not on the forecourt. Config ``pois.anchors`` adds
named points of its own (map ends, interchanges); these are not OSM facts.
"""
import math

import sumolib
from shapely import STRtree
from shapely.geometry import LineString, Point

from akadem_maps.core.osm_extract import poi

KIND_LABEL = {'fuel': 'АЗС', 'supermarket': 'Супермаркет', 'hypermarket': 'Гіпермаркет', 'mall': 'ТРЦ',
              'doityourself': 'Будмаркет', 'department_store': 'Універмаг'}
SPACING = 250.0       # metres; closer candidates are one stop
LIMIT = 25            # OSM points kept in total
FUEL_LIMIT = 18       # of which fuel stations; the rest are named large shops
# Shop preference. department_store is left out: in Kyiv OSM it mostly tags small
# sole-trader shops named after their owner, not department stores.
SHOP_ORDER = ('mall', 'hypermarket', 'doityourself', 'supermarket')
SNAP_MAX = 150.0      # metres from the point to the lane it spawns on
END_MARGIN = 10.0     # keep the spawn this far from either end of its lane


def kind_of(tags):
    return tags.get('amenity') if tags.get('amenity') == 'fuel' else tags.get('shop')


def candidates(root, tags, nodes, inside):
    """[{osm, kind, name, lon, lat}] for tagged nodes and ways in the area (OSM XML root)."""
    found = []
    for n in root.findall('node'):
        t = tags(n)
        if t and poi(t):
            lon, lat = float(n.get('lon')), float(n.get('lat'))
            if inside(lon, lat):
                found.append(_record('node', n.get('id'), t, lon, lat))
    for w in root.findall('way'):
        t = tags(w)
        if not t or not poi(t) or 'highway' in t:
            continue
        refs = [nd.get('ref') for nd in w.findall('nd') if nd.get('ref') in nodes]
        if refs[:1] == refs[-1:] and len(refs) > 1:
            refs = refs[:-1]
        if not refs:
            continue
        lon = sum(nodes[r][0] for r in refs) / len(refs)
        lat = sum(nodes[r][1] for r in refs) / len(refs)
        if inside(lon, lat):
            found.append(_record('way', w.get('id'), t, lon, lat))
    return found


def _record(kind, oid, t, lon, lat):
    return {'osm': f'{kind}/{oid}', 'kind': kind_of(t), 'name': t.get('brand') or t.get('name') or '',
            'lon': lon, 'lat': lat}


def select(found, to_xy, spacing=SPACING, limit=LIMIT, fuel_limit=FUEL_LIMIT):
    """Up to fuel_limit fuel stations, then named shops by SHOP_ORDER up to limit in total
    (more fuel if shops run out). Anything within `spacing` of a kept point is dropped."""
    fuel = sorted((c for c in found if c['kind'] == 'fuel'), key=lambda c: (not c['name'], c['osm']))
    shops = sorted((c for c in found if c['kind'] in SHOP_ORDER and c['name']),
                   key=lambda c: (SHOP_ORDER.index(c['kind']), c['osm']))
    kept = []

    def take(pool, cap):
        for c in pool:
            if len(kept) >= cap:
                return
            x, y = to_xy(c['lon'], c['lat'])
            if c not in kept and all(math.dist((x, y), to_xy(v['lon'], v['lat'])) >= spacing for v in kept):
                kept.append(c)
    take(fuel, min(fuel_limit, limit))
    take(shops, limit)
    take(fuel, limit)
    return kept


class Snapper:
    """Nearest acceptable road for a point; `edge_ok` and `rightmost` come from prepare."""

    def __init__(self, net, edge_ok, rightmost):
        self.edges = [e for e in net.getEdges() if edge_ok(e) and rightmost(e)]
        self.lines = [LineString(e.getShape()) for e in self.edges]
        self.tree = STRtree(self.lines)
        self.rightmost = rightmost

    def lane_at(self, x, y, heading=None, max_dist=SNAP_MAX):
        """(lane, offset along lane) nearest to (x, y), or None."""
        best = None
        for i in self.tree.query(Point(x, y).buffer(max_dist)):
            lane = self.rightmost(self.edges[i])
            shape = lane.getShape()
            offset = sumolib.geomhelper.polygonOffsetWithMinimumDistanceToPoint((x, y), shape)
            offset = min(max(offset, END_MARGIN), lane.getLength() - END_MARGIN)
            px, py = sumolib.geomhelper.positionAtShapeOffset(shape, offset)
            d = math.dist((x, y), (px, py))
            if d > max_dist:
                continue
            if heading is not None and abs((lane_heading(lane, offset) - heading + 180) % 360 - 180) > 45:
                continue
            if best is None or d < best[0]:
                best = (d, lane, offset)
        return best[1:] if best else None


def lane_heading(lane, offset):
    shape = lane.getShape()
    x, y = sumolib.geomhelper.positionAtShapeOffset(shape, offset)
    xa, ya = sumolib.geomhelper.positionAtShapeOffset(shape, min(offset + 2, lane.getLength()))
    return math.degrees(math.atan2(xa - x, ya - y)) % 360


def place(points, anchors, net, snapper, point, lane_z, report):
    """Spawn records for OSM points and config anchors, numbered south to north.

    point(x, y, z) -> map coordinates; lane_z(lane, offset) -> road height."""
    placed = []
    items = [(p, None) for p in points]
    items += [({'osm': None, 'kind': 'anchor', 'name': a['name'], 'lon': a['lon'], 'lat': a['lat']},
               a.get('heading')) for a in anchors]
    items.sort(key=lambda item: (item[0]['lat'], item[0]['osm'] or ''))
    for item, heading in items:
        x, y = net.convertLonLat2XY(item['lon'], item['lat'])
        hit = snapper.lane_at(x, y, heading)
        if hit is None:
            report['pois_unsnapped'].append(item['osm'] or item['name'])
            continue
        lane, offset = hit
        px, py = sumolib.geomhelper.positionAtShapeOffset(lane.getShape(), offset)
        n = len(placed) + 1
        if item['kind'] == 'anchor':
            title = item['name']
        else:
            title = ' '.join(v for v in (KIND_LABEL.get(item['kind'], item['kind']), item['name']) if v)
        placed.append({'id': f'poi_{n:02d}', 'title': f'{n:02d} · {title}', 'kind': item['kind'],
                       'osm': item['osm'], 'provenance': 'osm' if item['osm'] else 'config',
                       'lane': lane.getID(), 'lane_position': round(offset, 2),
                       'position': point(px, py, lane_z(lane, offset)), 'angle': lane_heading(lane, offset)})
    return placed
