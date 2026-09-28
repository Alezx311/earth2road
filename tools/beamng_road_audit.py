"""Deterministic road survey: exact triangle heights and spatially spread drive sites."""
import argparse
from collections import defaultdict, Counter
import json
import math
from pathlib import Path
import xml.etree.ElementTree as ET

from beamng_geometry import beam_point
from export_beamng import tile_meshes

ROOT = Path(__file__).resolve().parents[1]


class SurfaceIndex:
    def __init__(self, tiles, cell=20):
        self.cell = cell
        self.grid = defaultdict(list)
        for tile in tiles:
            mesh, _ = tile_meshes(tile)
            for mat, faces in mesh.faces.items():
                for a, b, c in faces:
                    den = (b[1]-c[1])*(a[0]-c[0])+(c[0]-b[0])*(a[1]-c[1])
                    if abs(den) < 1e-9:
                        continue
                    tri = (a, b, c, den, mat)
                    for ix in range(math.floor(min(a[0], b[0], c[0])/cell), math.floor(max(a[0], b[0], c[0])/cell)+1):
                        for iy in range(math.floor(min(a[1], b[1], c[1])/cell), math.floor(max(a[1], b[1], c[1])/cell)+1):
                            self.grid[ix, iy].append(tri)

    def heights(self, x, y):
        result = []
        for a, b, c, den, mat in self.grid.get((math.floor(x/self.cell), math.floor(y/self.cell)), ()):
            u = ((b[1]-c[1])*(x-c[0])+(c[0]-b[0])*(y-c[1]))/den
            v = ((c[1]-a[1])*(x-c[0])+(a[0]-c[0])*(y-c[1]))/den
            if min(u, v, 1-u-v) >= -1e-7:
                result.append((u*a[2]+v*b[2]+(1-u-v)*c[2], mat))
        return result


def stations(points, spacing=10):
    """Distance-spaced points, including endpoints, with a forward unit tangent."""
    carry = 0.0
    for a, b in zip(points, points[1:]):
        d = math.dist(a[:2], b[:2])
        if d < 1e-6:
            continue
        direction = [(b[0]-a[0])/d, (b[1]-a[1])/d, 0]
        while carry < d:
            yield [a[k]+(b[k]-a[k])*carry/d for k in range(3)], direction
            carry += spacing
        carry -= d
    if len(points) > 1:
        yield list(points[-1]), direction


def survey(mid, count=40, world=None):
    # A world v2 folder holds index, tiles, network and corrected OSM together.
    folder = Path(world) if world else ROOT/'game/data'/mid
    build = Path(world) if world else ROOT/'data/build'/mid
    index = json.loads((folder/'index.json').read_text(encoding='utf8'))
    tiles = [json.loads(p.read_text(encoding='utf8')) for p in sorted((folder/'tiles').glob('*.json'))]
    surface = SurfaceIndex(tiles)
    net = ET.parse(build/'network.net.xml').getroot()
    edges = {e.get('id'): e for e in net.findall('edge')}
    lanes = [l for l in index['lanes'] if not l.get('internal')]
    candidates, errors, counts = [], [], Counter()
    spawn = beam_point(index['spawn']['position'])
    for lane in lanes:
        pts = [beam_point(p) for p in lane['points']]
        samples = list(stations(pts))
        if not samples:
            continue
        edge = edges.get(lane['edge'])
        kind = edge.get('type', '') if edge is not None else ''
        for p, direction in samples:
            hits = surface.heights(*p[:2])
            road = [z for z, mat in hits if mat == 'kyiv_asphalt']
            delta = min((abs(z-p[2]) for z in road), default=999)
            obstruction = [(z, m) for z, m in hits if .08 < z-p[2] < 3]
            counts['samples'] += 1
            if delta > .02 or obstruction:
                errors.append({'lane': lane['id'], 'point': p, 'road_error': round(delta, 4),
                               'overlays': obstruction})
        p, direction = samples[min(len(samples)-1, max(0, len(samples)//3))]
        bridge = any(mat == 'kyiv_asphalt' and abs(z-p[2]) < .1 for z, mat in surface.heights(*p[:2])) and p[2] > 3
        candidates.append({'lane': lane['id'], 'edge': lane['edge'], 'point': p, 'direction': direction,
                           'width': lane['width'], 'kind': kind,
                           'path': [pt for pt, _ in samples], 'category': 'elevated' if bridge else kind})
    chosen = []
    def add(c, category=None):
        c = dict(c)
        if category:
            c['category'] = category
        if not any(c['lane'] == x['lane'] for x in chosen):
            chosen.append(c)
    add(min(candidates, key=lambda c: math.dist(c['point'], spawn)), 'spawn')
    for offset in (80, 180, 350, 600, 900):
        target = [spawn[0]-offset, spawn[1], spawn[2]]
        add(min(candidates, key=lambda c: math.dist(c['point'][:2], target[:2])), 'west')
    # Explicit bridge strips, including approach/end stations, rather than a height guess.
    bridge_sites = []
    for tile in tiles:
        for strip in tile.get('road_strips', []):
            if strip.get('bridge'):
                pts = [beam_point(p) for p in strip['points']]
                for p in (pts[0], pts[len(pts)//2], pts[-1]):
                    if all(math.dist(p, q) > 65 for q in bridge_sites):
                        bridge_sites.append(p)
                        add(min(candidates, key=lambda c: math.dist(c['point'], p)), 'bridge')
    for kind in sorted({c['kind'] for c in candidates}):
        add(min((c for c in candidates if c['kind'] == kind), key=lambda c: c['width']), 'narrow_'+kind)
    for error in sorted(errors, key=lambda e: max(e['road_error'], max((z-e['point'][2] for z, _ in e['overlays']), default=0)), reverse=True)[:8]:
        add(next(c for c in candidates if c['lane'] == error['lane']), 'surface_anomaly')
    while len(chosen) < count:
        remaining = [c for c in candidates if c['lane'] not in {x['lane'] for x in chosen}]
        if not remaining:
            break
        add(max(remaining, key=lambda c: min(math.dist(c['point'][:2], x['point'][:2]) for x in chosen)), 'coverage')
    for i, c in enumerate(chosen):
        c['name'] = f'{i:03d}_{c["category"].replace("highway.", "")}'
        # Drive from the selected station onward, not from the beginning of the lane.
        start = min(range(len(c['path'])), key=lambda n: math.dist(c['path'][n], c['point']))
        c['path'] = c['path'][start:]
    narrow=[]
    osm=ET.parse(build/'corrected.osm').getroot()
    facts={w.get('id'):{t.get('k'):t.get('v') for t in w.findall('tag')} for w in osm.findall('way')}
    for lane in lanes:
        if lane['width'] >= 2.5:
            continue
        edge=edges.get(lane['edge'])
        if edge is None: continue
        element=next((l for l in edge.findall('lane') if l.get('id')==lane['id']),None)
        orig=next((p.get('value') for p in element.findall('param') if p.get('key')=='origId'),'') if element is not None else ''
        tags=facts.get(orig,{})
        narrow.append({'lane':lane['id'],'width':lane['width'],'osm_way':orig,
                       'name':tags.get('name'),'osm_lanes':tags.get('lanes'),'osm_width':tags.get('width'),
                       'note':'Shared narrow carriageway: do not assume a full lane per direction.'})
    return {'map': mid, 'cases': chosen, 'counts': dict(counts), 'anomalies': errors,
            'narrow_lanes':narrow,
            'widths': dict(Counter((str(l['width']) for l in lanes))),
            'note': 'Offline triangle audit; does not establish in-game collision correctness.'}


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--map', default='akadem')
    p.add_argument('--count', type=int, default=40)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--world', type=Path, help='World v2 folder instead of game/data + data/build')
    args = p.parse_args()
    report = survey(args.map, args.count, args.world)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps({'cases': len(report['cases']), 'anomalies': len(report['anomalies']), **report['counts'], 'widths': report['widths']}))
