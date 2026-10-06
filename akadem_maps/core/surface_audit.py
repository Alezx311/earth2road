"""Exact road-triangle contacts, including touching borders and internal lanes.

Coordinates inside this module are x east, y north, z up (metres). Classification
uses source topology and structure tags, never a height-difference cutoff.
"""
from collections import Counter
import json
import math
from pathlib import Path
import xml.etree.ElementTree as ET

from shapely.geometry import Point, Polygon
from shapely.ops import nearest_points
from shapely.strtree import STRtree

from . import scene


def xyz(p):
    return (p[0], -p[2], p[1])


def world(p):
    return [round(p[0], 3), round(p[2], 3), round(-p[1], 3)]


def ribbon_triangles(points, width):
    """Clamped mitres and centre seam, identical to the BeamNG road mesh."""
    left, right = scene.strip_borders(points, width)
    for i in range(len(points)-1):
        a, b = points[i:i+2]
        yield (left[i], a, b)
        yield (left[i], b, left[i+1])
        yield (a, right[i], right[i+1])
        yield (a, right[i+1], b)


def plane(tri):
    a, b, c = tri
    den = (b[1]-c[1])*(a[0]-c[0])+(c[0]-b[0])*(a[1]-c[1])
    if abs(den) < 1e-10:
        return None
    dx = ((b[1]-c[1])*(a[2]-c[2])+(c[1]-a[1])*(b[2]-c[2]))/den
    dy = ((c[0]-b[0])*(a[2]-c[2])+(a[0]-c[0])*(b[2]-c[2]))/den
    return dx, dy, c[2]-dx*c[0]-dy*c[1]


def at(coeff, x, y):
    return coeff[0]*x+coeff[1]*y+coeff[2]


def stations(points, step=2.0):
    """Uniform XY arc stations, with original corners and final remainder omitted."""
    distance, next_s = 0.0, 0.0
    for a, b in zip(points, points[1:]):
        length = math.dist(a[:2], b[:2])
        if length < 1e-9:
            continue
        while next_s <= distance+length+1e-8:
            t = min(1.0, max(0.0, (next_s-distance)/length))
            yield next_s, tuple(a[k]+(b[k]-a[k])*t for k in range(3))
            next_s += step
        distance += length


def source_metadata(folder):
    """Reconstruct metadata for older worlds without changing those worlds."""
    folder = Path(folder)
    tags, refs = {}, {}
    if (folder/'corrected.osm').exists():
        for w in ET.parse(folder/'corrected.osm').getroot().findall('way'):
            tags[w.get('id')] = {t.get('k'): t.get('v') for t in w.findall('tag')}
            refs[w.get('id')] = {n.get('ref') for n in w.findall('nd')}
    lanes, junctions = {}, {}
    if not (folder/'network.net.xml').exists():
        return lanes, junctions
    root = ET.parse(folder/'network.net.xml').getroot()
    for e in root.findall('edge'):
        if e.get('function', ''):
            continue
        for lane in e.findall('lane'):
            ways = next((p.get('value', '').split() for p in lane.findall('param')
                         if p.get('key') == 'origId'), [])
            facts = [tags.get(w, {}) for w in ways]
            structures = {structure(t) for t in facts} or {(0, False, False)}
            nodes = {n for n in (e.get('from'), e.get('to')) if n}
            record = {'edge': e.get('id'), 'ways': ways, 'nodes': sorted(nodes),
                      'osm_nodes': sorted(set().union(*(refs.get(w, set()) for w in ways))),
                      'levels': [list(s) for s in sorted(structures)]}
            lanes[lane.get('id')] = record
            for node in nodes:
                junctions.setdefault(node, []).append(record)
    return lanes, {n: {'nodes': [n], 'ways': sorted({w for r in rs for w in r['ways']}),
                       'levels': [list(s) for s in sorted({tuple(s) for r in rs for s in r['levels']})]}
                  for n, rs in junctions.items()}


def structure(tags):
    try:
        level = int(float(tags.get('layer', 0)))
    except (ValueError, TypeError):
        level = 0
    return (level, tags.get('bridge', 'no') != 'no',
            tags.get('tunnel', 'no') not in ('no', 'building_passage'))


def relationship(a, b):
    shared = any(set(a.get(k, ())) & set(b.get(k, ())) for k in ('nodes', 'ways', 'osm_nodes'))
    la, lb = {tuple(s) for s in a.get('levels', ())}, {tuple(s) for s in b.get('levels', ())}
    if la and lb and not la & lb:
        return 'ambiguous' if shared else 'grade_separated'
    if shared and len(la | lb) <= 1:
        return 'connected'
    return 'ambiguous'


class TriangleIndex:
    def __init__(self, surfaces):
        self.polys, self.planes, self.owners, self.metadata = [], [], [], {}
        for sid, triangles, meta in surfaces:
            self.metadata[sid] = meta
            for tri in triangles:
                coeff = plane(tri)
                if coeff is None:
                    continue
                self.polys.append(Polygon([p[:2] for p in tri]))
                self.planes.append(coeff)
                self.owners.append(sid)
        self.tree = STRtree(self.polys)

    def hits(self, x, y):
        pt = Point(x, y)
        return [(at(self.planes[i], x, y), self.owners[i]) for i in self.tree.query(pt)
                if self.polys[i].covers(pt)]


def surfaces(tiles, lane_meta=None, junction_meta=None):
    lane_meta, junction_meta = lane_meta or {}, junction_meta or {}
    for tile in tiles:
        for r in tile.get('road_strips', []):
            sid = 'lane:'+r.get('lane', r.get('edge', 'unknown'))
            tris = ([tuple(xyz(p) for p in t) for t in r['triangles']] if 'triangles' in r else
                    ribbon_triangles([xyz(p) for p in r['points']], r['width']))
            yield sid, tris, r.get('topology', lane_meta.get(r.get('lane'), {}))
        for j in tile.get('junctions', []):
            yield 'junction:'+j['id'], ([xyz(p) for p in t] for t in j['triangles']), j.get('topology', junction_meta.get(j['id'], {}))


def vertices(geom):
    if geom.is_empty:
        return []
    if geom.geom_type == 'Polygon':
        return list(geom.exterior.coords)
    if hasattr(geom, 'geoms'):
        return [p for g in geom.geoms for p in vertices(g)]
    return list(geom.coords)


def audit(index, tiles, lane_meta=None, junction_meta=None):
    mesh = TriangleIndex(surfaces(tiles, lane_meta, junction_meta))
    contacts = {}
    reporting_floor = .001 if index.get('road_elevation') else .01
    # A 2 mm tolerance detects rounded, nominally common edges without bridging gaps.
    for i, poly in enumerate(mesh.polys):
        owner = mesh.owners[i]
        for k in mesh.tree.query(poly, predicate='dwithin', distance=.002):
            k = int(k)
            other = mesh.owners[k]
            if k <= i or owner == other:
                continue
            pair = tuple(sorted((owner, other)))
            contact = poly.intersection(mesh.polys[k])
            pts = vertices(contact)
            if not pts:
                pa, pb = nearest_points(poly, mesh.polys[k])
                pts = [((pa.x+pb.x)/2, (pa.y+pb.y)/2)]
            point = max(pts, key=lambda p: abs(at(mesh.planes[i], *p)-at(mesh.planes[k], *p)))
            h0, h1 = at(mesh.planes[i], *point), at(mesh.planes[k], *point)
            delta = float(abs(h1-h0))
            if delta <= reporting_floor:
                continue
            key = (*pair, math.floor(point[0]/2), math.floor(point[1]/2))
            if key in contacts and contacts[key]['step_m'] >= delta:
                continue
            contacts[key] = {'surfaces': list(pair), 'classification': relationship(mesh.metadata[owner], mesh.metadata[other]),
                             'contact': 'overlap' if contact.area > 1e-8 else 'edge',
                             'step_m': round(delta, 4), 'world': world((*point, min(h0, h1))),
                             'beamng': [round(point[0], 3), round(point[1], 3), round(min(h0, h1), 3)]}
    records = sorted(contacts.values(), key=lambda r: (-r['step_m'], r['surfaces'], r['world']))
    changes, profile_changes, steep, surface_steep, crossfalls = [], [], [], [], []
    cross_missing, cross_samples, cross_missing_examples = 0, 0, []
    lane_surface_errors = []
    for lane in index.get('lanes', []):
        sampled = list(stations([xyz(p) for p in lane['points']]))
        grades = [(b[1][2]-a[1][2])/(b[0]-a[0]) for a, b in zip(sampled, sampled[1:])]
        limit = .12 if lane.get('service') else .06
        # Absolute grade is independent of a grade change: a long steep hill
        # must be reported even though it is perfectly smooth.
        for (station, p), grade in zip(sampled, grades):
            if abs(grade) > limit:
                steep.append({'lane': lane['id'], 'grade': round(grade, 6),
                              'limit': limit, 'station_m': round(station, 3), 'world': world(p)})
        for i, (a, b) in enumerate(zip(grades, grades[1:])):
            if abs(b-a) > .02:
                p = sampled[i+1][1]
                profile_changes.append({'lane': lane['id'], 'internal': bool(lane.get('internal')),
                                'change': round(abs(b-a), 6), 'world': world(p), 'beamng': list(p)})
        surface_samples = []
        own = ('junction:'+lane.get('edge', lane['id'].rsplit('_', 1)[0])[1:].rsplit('_', 1)[0]
               if lane.get('internal') else 'lane:'+lane['id'])
        for _, p in sampled:
            hits = mesh.hits(*p[:2])
            if index.get('road_elevation'):
                meta = mesh.metadata.get(own, {})
                hits = [(h,sid) for h,sid in hits if sid == own or relationship(meta,mesh.metadata[sid]) == 'connected']
            error = min((abs(h-p[2]) for h, _ in hits), default=999.)
            preferred = [h for h,sid in hits if sid == own] or [h for h,_ in hits]
            h = min(preferred, key=lambda h: abs(h-p[2])) if preferred else None
            surface_samples.append((*p[:2], h))
            if error > .05:
                lane_surface_errors.append({'lane': lane['id'], 'error_m': round(error, 4), 'world': world(p)})
        for i,(a,b) in enumerate(zip(surface_samples,surface_samples[1:])):
            if a[2] is None or b[2] is None:
                continue
            grade = (b[2]-a[2])/(sampled[i+1][0]-sampled[i][0])
            if abs(grade) > limit:
                surface_steep.append({'lane':lane['id'], 'grade':round(grade,6), 'limit':limit,
                                      'station_m':round(sampled[i][0],3), 'world':world(a)})
        for a,b,c in zip(surface_samples,surface_samples[1:],surface_samples[2:]):
            if any(p[2] is None for p in (a,b,c)):
                continue
            delta = abs((c[2]-b[2])/2-(b[2]-a[2])/2)
            if delta > .02:
                changes.append({'lane':lane['id'], 'internal':bool(lane.get('internal')), 'change':round(delta,6),
                                'world':world(b), 'beamng':list(b)})
        if index.get('road_elevation'):
            meta = mesh.metadata.get(own, {})
            for i, (_, p) in enumerate(sampled):
                a, b = sampled[max(0,i-1)][1], sampled[min(len(sampled)-1,i+1)][1]
                length = math.dist(a[:2], b[:2])
                if length < 1e-9:
                    continue
                half = lane.get('width', 3.2)*.49
                nx, ny = -(b[1]-a[1])/length, (b[0]-a[0])/length
                heights = []
                for sign in (-1, 0, 1):
                    hits = mesh.hits(p[0]+sign*nx*half, p[1]+sign*ny*half)
                    valid = [(z,sid) for z,sid in hits if sid == own or relationship(meta,mesh.metadata[sid]) == 'connected']
                    heights.append(min((z for z,_ in valid), key=lambda z: abs(z-p[2]), default=None))
                cross_samples += 1
                if None in heights:
                    cross_missing += 1
                    if len(cross_missing_examples) < 100:
                        cross_missing_examples.append({'lane':lane['id'], 'world':world(p),
                            'missing_offsets_m':[round(offset,3) for offset,h in zip((-half,0.,half),heights) if h is None]})
                else:
                    slope = (heights[2]-heights[0])/(2*half)
                    if abs(slope) > .06:
                        crossfalls.append({'lane':lane['id'], 'grade':round(slope,6), 'world':world(p)})
    groups = {}
    for category in ('connected', 'grade_separated', 'ambiguous'):
        subset = [r for r in records if r['classification'] == category]
        groups[category] = {'contacts': len(subset), **{f'over_{cm}cm': int(sum(r['step_m'] > cm/100 for r in subset)) for cm in (10, 30, 60)},
                            'max_m': max((r['step_m'] for r in subset), default=0.)}
    regressions = classify_regressions(index.get('id'), mesh, records)
    return {'version': 2, 'provenance': 'generated geometry; not surveyed Kyiv road heights',
            'contact_reporting_floor_m': reporting_floor,
            'method': 'exact triangle contacts, maximum affine height difference; deduplicated per surface pair / 2 m cell',
            'coordinates': 'world=[east,up,south]; beamng=[east,north,up], before export vertical_offset',
            'triangles': len(mesh.polys), 'steps': groups,
            'smooth': {'spacing_m': 2, 'over_2pct': len(changes), 'over_5pct': int(sum(r['change'] > .05 for r in changes)),
                       'worst': sorted(changes, key=lambda r: -r['change'])[:100], 'all': changes},
            'profile_smooth': {'spacing_m': 2, 'over_2pct':len(profile_changes),
                               'over_5pct':int(sum(r['change'] > .05 for r in profile_changes))},
            'absolute_grade': {'provenance':'generated; thresholds are warnings, not surveyed limits',
                               'limits':{'default':.06,'service':.12}, 'over_limit':len(surface_steep),
                               'worst':sorted(surface_steep,key=lambda r:-abs(r['grade']))[:100]},
            'profile_grade': {'over_limit':len(steep),'worst':sorted(steep,key=lambda r:-abs(r['grade']))[:100]},
            'cross_section': {'samples':cross_samples, 'missing_surface':cross_missing,
                              'missing_examples':cross_missing_examples,
                              'over_6pct':len(crossfalls), 'worst':sorted(crossfalls,key=lambda r:-abs(r['grade']))[:100],
                              'all':crossfalls},
            'lane_surface_errors': {'over_5cm': len(lane_surface_errors), 'worst': sorted(lane_surface_errors, key=lambda r: -r['error_m'])[:100]},
            'acceptance': 'blocked' if groups['connected']['over_60cm'] else 'pending',
            'worst': records[:100], 'contacts': records, 'regression_sites': regressions}


def classify_regressions(map_id, mesh, records):
    registry = Path(__file__).resolve().parents[1]/'resources/surface_regressions.json'
    if not registry.exists():
        return []
    sites = json.loads(registry.read_text(encoding='utf8'))['maps'].get(map_id, [])
    result = []
    for site in sites:
        point = site['beamng_xy']
        nearby = [r for r in records if math.dist(r['beamng'][:2], point) <= 40]
        confirmed = [r for r in nearby if r['classification'] == 'connected' and r['step_m'] > .05]
        unknown = [r for r in nearby if r['classification'] == 'ambiguous' and r['step_m'] > .05]
        separated = [r for r in nearby if r['classification'] == 'grade_separated']
        coverage = len(mesh.tree.query(Point(point).buffer(40))) > 0
        status = ('confirmed_defect' if confirmed else 'ambiguous' if unknown else 'grade_separated' if separated
                  else 'below_5cm' if coverage else 'outside_coverage')
        result.append({**site, 'classification': status, 'confirmed_max_m': max((r['step_m'] for r in confirmed), default=0.),
                       'worst_contacts': nearby[:5]})
    return result


def audit_folder(folder):
    folder = Path(folder)
    index = json.loads((folder/'index.json').read_text(encoding='utf8'))
    tiles = (json.loads(p.read_text(encoding='utf8')) for p in sorted((folder/'tiles').glob('*.json')))
    return audit(index, tiles, *source_metadata(folder))


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('world', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    report = audit_folder(args.world)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps({k: report[k] for k in ('triangles', 'steps', 'acceptance')}))


if __name__ == '__main__':
    main()
