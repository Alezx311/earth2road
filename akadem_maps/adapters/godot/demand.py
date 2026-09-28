#!/usr/bin/env python3
"""Synthetic travel demand from OpenStreetMap: who drives from where to where, by hour.

Producers are homes: residential buildings weighted by floor area (footprint x levels).
Attractors are workplaces, shops, schools, hospitals and metro/rail stations (building
floor area or a fixed equivalent for point features). Gateways are the main roads
where the network is cut at the map boundary (through traffic and commuters).

Each is snapped to its nearest drivable edge. Trips are sampled per category and routed
with duarouter; the bridge (tools/traffic.py) keeps the requested number of cars on the
road and picks new trips by category with the hour-of-day mix in PROFILE.

Optional calibration: config/counts.json lists observed counts (vehicles/hour on a road
at a place and direction). routeSampler.py (SUMO) then picks the route mix that best
reproduces them for the counted hours. Without counts, nothing here is measured."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import random
import subprocess
import sys
import xml.etree.ElementTree as ET

import sumolib
from shapely import STRtree

from akadem_maps.core import corridor

from akadem_maps import runtime
from shapely.geometry import LineString, Point, Polygon, shape

SUMO_TOOLS = Path(sumolib.__file__).resolve().parents[1] / 'sumo/tools'

# Typical levels when OSM has no building:levels (assumptions, counted in the report).
LEVELS = {'apartments': 9, 'residential': 5, 'dormitory': 5, 'house': 1.5, 'detached': 1.5,
          'semidetached_house': 2, 'terrace': 2, 'bungalow': 1, 'yes': 5}
HOMES = {'apartments', 'residential', 'dormitory', 'house', 'detached', 'semidetached_house', 'terrace', 'bungalow'}
# Attraction per m2 of floor area, relative to home floor area (assumed).
WORK_BUILDINGS = {'office': 1.0, 'commercial': 1.0, 'retail': 1.3, 'supermarket': 1.5, 'mall': 1.5,
                  'industrial': 0.4, 'warehouse': 0.25, 'school': 0.8, 'university': 1.0, 'college': 0.8,
                  'hospital': 1.0, 'kindergarten': 0.6, 'public': 0.8, 'civic': 0.6, 'government': 0.8,
                  'train_station': 1.0, 'hotel': 0.5}
# Point features: fixed floor-area equivalents, m2 (assumed).
POINTS = {('amenity', 'school'): 4000, ('amenity', 'university'): 10000, ('amenity', 'college'): 4000,
          ('amenity', 'hospital'): 8000, ('amenity', 'clinic'): 1500, ('amenity', 'kindergarten'): 1500,
          ('shop', 'mall'): 20000, ('shop', 'supermarket'): 3000, ('railway', 'station'): 6000,
          ('railway', 'subway_entrance'): 2500, ('station', 'subway'): 4000, ('office', '*'): 800,
          ('amenity', 'marketplace'): 4000}
# Land use without buildings mapped: share of area counted as floor area.
LANDUSE = {'commercial': 0.3, 'retail': 0.4, 'industrial': 0.15}
GATEWAY = {'highway.motorway': 8, 'highway.trunk': 6, 'highway.primary': 5, 'highway.secondary': 3, 'highway.tertiary': 1.2}
MIN_TRIP_M = 500          # shorter trips are mostly walked (assumption)
SNAP_M = 250
CATEGORIES = ('hw', 'wh', 'oo', 'tin', 'tout', 'tt')
# Hour-of-day category shares (synthetic): hw home->work, wh work->home, oo other local,
# tin/tout commuters crossing the boundary, tt through traffic.
PROFILE_BLOCKS = [
    (0, 6, {'hw': .10, 'wh': .15, 'oo': .30, 'tin': .15, 'tout': .10, 'tt': .20}),
    (6, 10, {'hw': .42, 'wh': .05, 'oo': .15, 'tin': .16, 'tout': .10, 'tt': .12}),
    (10, 16, {'hw': .10, 'wh': .12, 'oo': .43, 'tin': .10, 'tout': .10, 'tt': .15}),
    (16, 20, {'hw': .05, 'wh': .42, 'oo': .15, 'tin': .08, 'tout': .18, 'tt': .12}),
    (20, 24, {'hw': .05, 'wh': .25, 'oo': .35, 'tin': .08, 'tout': .12, 'tt': .15}),
]
PROFILE = [next(mix for a, b, mix in PROFILE_BLOCKS if a <= h < b) for h in range(24)]

def lonlat_area(coords):
    """Polygon area in m2 from lon/lat (local equirectangular; fine at district scale)."""
    lat0 = math.radians(sum(c[1] for c in coords) / len(coords))
    pts = [(lon * 111320 * math.cos(lat0), lat * 110540) for lon, lat in coords]
    return abs(Polygon(pts).area) if len(pts) >= 3 else 0.0

def levels(t, default):
    try:
        return max(1.0, float(str(t.get('building:levels', '')).split(';')[0].replace(',', '.')))
    except ValueError:
        return default

class Snapper:
    """Nearest drivable (passenger, non-internal) edge to a point, via an STRtree."""
    def __init__(self, net):
        self.edges = [e for e in net.getEdges() if e.getFunction() == '' and e.allows('passenger')]
        self.lines = [LineString(e.getShape()) for e in self.edges]
        self.tree = STRtree(self.lines)
    def edge(self, x, y, service_ok=True):
        p = Point(x, y)
        near = sorted(self.tree.query(p.buffer(SNAP_M)), key=lambda i: self.lines[i].distance(p))
        for i in near:
            e = self.edges[i]
            if service_ok or e.getType() != 'highway.service':
                return e
        return None

def features(root):
    """Homes, attractors (floor-area weights) from buildings, points and land use."""
    nodes = {n.attrib['id']: (float(n.attrib['lon']), float(n.attrib['lat'])) for n in root.findall('node')}
    tags = lambda e: {t.attrib['k']: t.attrib['v'] for t in e.findall('tag')}
    homes, work, report = [], [], Counter()
    residential_areas = []
    for w in root.findall('way'):
        t = tags(w)
        if t.get('landuse') == 'residential':
            coords = [nodes[n.attrib['ref']] for n in w.findall('nd') if n.attrib['ref'] in nodes]
            if len(coords) >= 4:
                residential_areas.append(Polygon(coords))
    res_tree = STRtree(residential_areas) if residential_areas else None
    for w in root.findall('way'):
        t = tags(w)
        coords = [nodes[n.attrib['ref']] for n in w.findall('nd') if n.attrib['ref'] in nodes]
        if len(coords) < 4 or coords[0] != coords[-1]:
            continue
        area = lonlat_area(coords)
        centre = Polygon(coords).centroid
        kind = t.get('building')
        if kind:
            use = WORK_BUILDINGS.get(kind)
            if 'shop' in t or t.get('amenity') in ('school', 'university', 'college', 'hospital', 'kindergarten'):
                use = use or 1.0
            if 'building:levels' not in t:
                report['buildings_levels_assumed'] += 1
            floor = area * levels(t, LEVELS.get(kind, 3))
            if use:
                work.append((centre.x, centre.y, floor * use)); report['work_buildings'] += 1
            elif kind in HOMES:
                homes.append((centre.x, centre.y, floor)); report['home_buildings'] += 1
            elif kind == 'yes' and res_tree is not None and len(res_tree.query(centre, predicate='within')):
                homes.append((centre.x, centre.y, floor)); report['home_buildings_from_landuse'] += 1
            continue
        share = LANDUSE.get(t.get('landuse'))
        if share:
            work.append((centre.x, centre.y, area * share)); report['work_landuse_areas'] += 1
    for n in root.findall('node'):
        t = tags(n)
        if not t:
            continue
        for (k, v), weight in POINTS.items():
            if k in t and (v == '*' or t[k] == v):
                lon, lat = nodes[n.attrib['id']]
                work.append((lon, lat, weight)); report['work_points'] += 1
                break
    report['home_floor_km2'] = round(sum(w for *_, w in homes) / 1e6, 3)
    report['work_floor_km2'] = round(sum(w for *_, w in work) / 1e6, 3)
    return homes, work, report

def snap(net, snapper, items, report, key):
    weights = Counter()
    for lon, lat, w in items:
        x, y = net.convertLonLat2XY(lon, lat)
        e = snapper.edge(x, y)
        if e is None:
            report[key + '_unsnapped'] += 1
            continue
        weights[e.getID()] += w
    return weights

def gateways(net, bbox, area=None):
    """Main-road edges cut by the map boundary: sources have no predecessor, sinks no successor.
    area: the map polygon in network XY (a corridor); None means the bbox rectangle."""
    w, s, e, n = bbox
    corners = [net.convertLonLat2XY(lon, lat) for lon, lat in ((w, s), (e, n))]
    (x0, y0), (x1, y1) = corners
    def at_border(node, margin=250):
        x, y = node.getCoord()
        if area is not None:
            return area.exterior.distance(Point(x, y)) < margin
        return min(x - x0, x1 - x, y - y0, y1 - y) < margin
    sources, sinks = Counter(), Counter()
    for edge in net.getEdges():
        weight = GATEWAY.get(edge.getType())
        if not weight or edge.getFunction() != '' or not edge.allows('passenger'):
            continue
        lanes = edge.getLaneNumber()
        if not [i for i in edge.getIncoming() if i.getFunction() == '' and i.getFromNode() != edge.getToNode()] and at_border(edge.getFromNode()):
            sources[edge.getID()] = weight * lanes
        if not [o for o in edge.getOutgoing() if o.getFunction() == '' and o.getToNode() != edge.getFromNode()] and at_border(edge.getToNode()):
            sinks[edge.getID()] = weight * lanes
    return sources, sinks

def sample_trips(net, pools, pool_size, rng):
    """pools: category -> (origin weights, destination weights). Weighted OD pairs at
    least MIN_TRIP_M apart (straight line)."""
    centre = {e.getID(): e.getShape()[len(e.getShape()) // 2] for e in net.getEdges() if e.getFunction() == ''}
    trips = []
    for cat, (orig, dest) in pools.items():
        if not orig or not dest:
            continue
        o_ids, o_w = zip(*orig.items()); d_ids, d_w = zip(*dest.items())
        made = tries = 0
        while made < pool_size and tries < pool_size * 20:
            tries += 1
            a = rng.choices(o_ids, o_w)[0]; b = rng.choices(d_ids, d_w)[0]
            if a == b or math.dist(centre[a], centre[b]) < MIN_TRIP_M:
                continue
            trips.append((f'{cat}_{made}', a, b)); made += 1
    return trips

def route(trips, name, context):
    BUILD = context.build
    """duarouter (C++): fastest routes, unroutable pairs dropped."""
    trip_file = BUILD / f'{name}.trips.xml'
    out = BUILD / f'{name}.rou.xml'
    root = ET.Element('routes')
    for tid, a, b in trips:
        ET.SubElement(root, 'trip', id=tid, depart='0', attrib={'from': a, 'to': b})
    ET.ElementTree(root).write(trip_file, encoding='utf-8', xml_declaration=True)
    subprocess.run([str(runtime.sumo_binary('duarouter')), '-n', str(BUILD / 'network.net.xml'), '--route-files', str(trip_file),
                    '-o', str(out), '--ignore-errors', '--no-warnings', '--no-step-log', '--routing-threads', '8',
                    '--departlane', 'best', '--remove-loops'],
                   check=True, stdout=subprocess.DEVNULL)
    routes = {}
    for v in ET.parse(out).getroot().iter('vehicle'):
        edges = v.find('route').attrib['edges'].split()
        if len(edges) >= 2:
            routes[v.attrib['id']] = edges
    return routes

def calibrate(net, snapper, pool_routes, counts, rng, context):
    BUILD = context.build
    """routeSampler: choose routes from the pool that reproduce observed hourly counts.
    Returns ({hour: [[edges], ...]}, report)."""
    by_hour = {}
    report = {'counts': len(counts), 'matched': [], 'unmatched': []}
    for c in counts:
        x, y = net.convertLonLat2XY(c['lon'], c['lat'])
        best = None
        candidates = sorted(snapper.tree.query(Point(x, y).buffer(60)), key=lambda i: snapper.lines[i].distance(Point(x, y)))
        for i in candidates:
            e = snapper.edges[i]
            if 'bearing' in c and c['bearing'] is not None:
                shp = e.getShape(); (ax, ay), (bx, by) = shp[0], shp[-1]
                heading = math.degrees(math.atan2(bx - ax, by - ay)) % 360
                if abs((heading - c['bearing'] + 180) % 360 - 180) > 45:
                    continue
            best = e; break
        if best is None:
            report['unmatched'].append(c); continue
        by_hour.setdefault(int(c['hour']), {})[best.getID()] = by_hour.get(int(c['hour']), {}).get(best.getID(), 0) + float(c['vehicles_per_hour'])
    calibrated = {}
    candidates = BUILD / 'calibration_candidates.rou.xml'
    root = ET.Element('routes')
    flat = [r for routes in pool_routes.values() for r in routes]
    for i, edges in enumerate(flat):
        ET.SubElement(root, 'route', id=f'c{i}', edges=' '.join(edges))
    ET.ElementTree(root).write(candidates, encoding='utf-8', xml_declaration=True)
    for hour, edges in sorted(by_hour.items()):
        data = ET.Element('data'); interval = ET.SubElement(data, 'interval', id=f'h{hour}', begin='0', end='3600')
        for eid, n in edges.items():
            ET.SubElement(interval, 'edge', id=eid, entered=str(n))
        counts_file = BUILD / f'counts_h{hour}.xml'; out = BUILD / f'calibrated_h{hour}.rou.xml'; mismatch = BUILD / f'calibration_mismatch_h{hour}.xml'
        ET.ElementTree(data).write(counts_file, encoding='utf-8', xml_declaration=True)
        import os
        env = {**os.environ, 'SUMO_HOME': str(SUMO_TOOLS.parent)}
        subprocess.run([sys.executable, str(SUMO_TOOLS / 'routeSampler.py'), '-r', str(candidates), '-d', str(counts_file),
                        '-o', str(out), '--mismatch-output', str(mismatch), '-s', str(rng.randrange(1 << 30)), '-b', '0', '-e', '3600'],
                       check=True, stdout=subprocess.DEVNULL, env=env)
        chosen = [v.find('route').attrib['edges'].split() if v.find('route') is not None else None for v in ET.parse(out).getroot().iter('vehicle')]
        # routeSampler writes route references; resolve them to edges.
        ref = {f'c{i}': edges for i, edges in enumerate(flat)}
        chosen = [c if c else ref[v.attrib['route']] for c, v in zip(chosen, ET.parse(out).getroot().iter('vehicle'))]
        calibrated[hour] = chosen
        got = Counter(e for r in chosen for e in set(r))
        for eid, want in edges.items():
            have = got[eid]
            geh = math.sqrt(2 * (have - want) ** 2 / (have + want)) if have + want else 0.0
            report['matched'].append({'hour': hour, 'edge': eid, 'target': want, 'sampled': have, 'geh': round(geh, 2)})
    return calibrated, report

def roadworks(net, cfg, report, context):
    RAW = context.raw
    """Kyiv open data 'road closures and repairs' (optional): active works -> slower edges."""
    spec = cfg.get('roadworks')
    if not spec:
        return []
    path = RAW / 'roadworks.geojson'
    if not path.exists():
        context.download(spec['url'], path, max_time=120)
    raw = path.read_bytes()
    report['roadworks_source'] = {'url': spec['url'], 'sha256': hashlib.sha256(raw).hexdigest(), 'features': 0}
    data = json.loads(raw)
    snapper_lines = [(e, LineString(e.getShape())) for e in net.getEdges() if e.getFunction() == '' and e.allows('passenger')]
    tree = STRtree([l for _, l in snapper_lines])
    out = []
    for f in data.get('features', []):
        p = f.get('properties', {})
        report['roadworks_source']['features'] += 1
        if p.get('workstatus') not in spec['active_statuses'] or not f.get('geometry'):
            continue
        geom = shape(f['geometry'])
        rings = [geom] if geom.geom_type == 'Polygon' else list(geom.geoms)
        for poly in rings:
            local = Polygon([net.convertLonLat2XY(lon, lat) for lon, lat in poly.exterior.coords])
            for i in tree.query(local, predicate='intersects'):
                e = snapper_lines[i][0]
                out.append({'edge': e.getID(), 'speed': spec['speed'], 'status': p.get('workstatus'), 'what': p.get('addressdescription')})
    report['roadworks_edges'] = len(out)
    return out

def build(cfg, root, net, seed, counts_path=None, *, context):
    BUILD = context.build
    rng = random.Random(seed)
    report = Counter()
    homes, work, feature_report = features(root)
    report.update(feature_report)
    snapper = Snapper(net)
    home_w = snap(net, snapper, homes, report, 'home')
    work_w = snap(net, snapper, work, report, 'work')
    area = corridor.to_net(corridor.area(cfg, context=context), net) if corridor.shaped(cfg) else None
    sources, sinks = gateways(net, cfg['bbox'], area)
    report['gateway_sources'] = len(sources); report['gateway_sinks'] = len(sinks)
    local = home_w + work_w
    pools = {'hw': (home_w, work_w), 'wh': (work_w, home_w), 'oo': (local, local),
             'tin': (sources, local), 'tout': (local, sinks), 'tt': (sources, sinks)}
    size = int(cfg.get('demand_pool', 600))
    trips = sample_trips(net, pools, size, rng)
    routed = route(trips, 'demand', context)
    categories = {c: [] for c in CATEGORIES}
    for tid, edges in routed.items():
        categories[tid.split('_')[0]].append(edges)
    report.update({f'routes_{c}': len(r) for c, r in categories.items()})
    report['trips_unroutable'] = len(trips) - len(routed)
    counts_path = Path(counts_path) if counts_path else context.config_root / 'config/counts.json'
    counts = json.loads(counts_path.read_text())['counts'] if counts_path.exists() else []
    calibrated, calibration = calibrate(net, snapper, categories, counts, rng, context) if counts else ({}, {'counts': 0})
    works = roadworks(net, cfg, report, context)
    demand = {'generated_at': datetime.now(timezone.utc).isoformat(), 'seed': seed,
              'start_time': cfg.get('start_time', '07:30'), 'profile': PROFILE, 'categories': categories,
              'calibrated': {str(h): r for h, r in calibrated.items()}, 'roadworks': works,
              'note': 'Synthetic demand from OSM land use; category mix per hour assumed. Calibrated hours follow config/counts.json.'}
    (BUILD / 'demand.json').write_text(json.dumps(demand, separators=(',', ':')))
    summary = {**dict(report), 'calibration': calibration, 'assumptions': [
        'Homes and destinations from OSM buildings (floor area = footprint x levels; typical levels assumed where missing), point features and land use with assumed weights.',
        'Hour-of-day category mix (home->work, work->home, local, commuters, through traffic) is assumed, not measured.',
        f'Trips shorter than {MIN_TRIP_M} m straight line are not driven (assumed walked).',
        'Gateway weights by road class x lanes (assumed).']}
    return summary
