"""Repeatable spawn + ten western vehicle sites, with connected forward drive paths.

--pois instead makes one case per quick-travel point (tools/pois.py) plus the default spawn."""
import argparse
import json
import math
from pathlib import Path
import xml.etree.ElementTree as ET

from beamng_geometry import beam_point
from beamng_road_audit import stations

ROOT = Path(__file__).resolve().parents[1]


def drive_path(lane_id, point, lanes, connections, distance=90):
    """Follow passenger-lane connections, including the junction's internal lanes."""
    result = [list(point)]
    seen = set()
    current = lane_id
    while current in lanes and current not in seen:
        seen.add(current)
        points = [beam_point(p) for p in lanes[current]['points']]
        if len(seen) == 1:
            segment = min(range(len(points)-1), key=lambda i: segment_distance(point, points[i], points[i+1]))
            points = points[segment+1:]
        for p in points:
            if math.dist(result[-1], p) > .01:
                result.append(list(p))
            if sum(math.dist(a, b) for a, b in zip(result, result[1:])) >= distance:
                return result
        options = [x for x in connections.get(current, []) if x in lanes and x not in seen]
        if not options:
            break
        direction = [result[-1][k]-result[-2][k] for k in (0, 1)] if len(result)>1 else [0, 1]
        def turn(target):
            pts = [beam_point(p) for p in lanes[target]['points']]
            d = [pts[-1][k]-pts[0][k] for k in (0, 1)]
            return -sum(a*b for a,b in zip(direction,d))/max(math.hypot(*d), 1e-6), target
        current = min(options, key=turn)
    return result


def segment_distance(p, a, b):
    dx, dy = b[0]-a[0], b[1]-a[1]
    t = max(0, min(1, ((p[0]-a[0])*dx+(p[1]-a[1])*dy)/max(dx*dx+dy*dy, 1e-12)))
    return math.hypot(p[0]-a[0]-t*dx, p[1]-a[1]-t*dy)


def western_cases(index, net, count=10):
    lanes = {l['id']: l for l in index['lanes'] if len(l['points']) > 1}
    connections = {}
    for c in net.findall('connection'):
        # Dead-end turnarounds are tighter than a car can follow at the map border.
        if c.get('dir') == 't':
            continue
        src = c.get('from')+'_'+c.get('fromLane')
        target = c.get('via') or c.get('to')+'_'+c.get('toLane')
        connections.setdefault(src, []).append(target)
    spawn = list(beam_point(index['spawn']['position']))

    def case(lane, p, direction, category):
        return dict(lane=lane['id'], point=list(p), direction=direction, width=lane['width'],
                    category=category, path=drive_path(lane['id'], p, lanes, connections))

    lane = lanes[index['spawn']['lane']]
    pts = [beam_point(p) for p in lane['points']]
    i = min(range(len(pts)-1), key=lambda i: segment_distance(spawn,pts[i],pts[i+1]))
    length = math.dist(pts[i][:2],pts[i+1][:2])
    selected = [case(lane, spawn, [(pts[i+1][k]-pts[i][k])/length for k in (0,1)]+[0], 'spawn')]
    candidates = []
    for lane in lanes.values():
        if lane.get('internal'):
            continue
        samples = list(stations([beam_point(p) for p in lane['points']], 25))
        # Skip the lane's first station: at a dead end on the map border the AI
        # start nudges the car ~2 m backwards, off the road cap.
        for p, direction in samples[1:-1]:
            if p[0] < spawn[0]-20:
                candidates.append((lane, p, direction))
    # Begin close to the reported trouble, then maximize spatial coverage westward.
    while len(selected) <= count and candidates:
        if len(selected) == 1:
            item = min(candidates, key=lambda c: math.dist(c[1][:2], [spawn[0]-80,spawn[1]]))
        else:
            item = max(candidates, key=lambda c: min(math.dist(c[1][:2], s['point'][:2]) for s in selected))
        candidates.remove(item)
        c = case(*item, 'west')
        if sum(math.dist(a,b) for a,b in zip(c['path'],c['path'][1:])) < 35:
            continue
        selected.append(c)
        candidates = [v for v in candidates if math.dist(v[1][:2],c['point'][:2]) >= 50]
    if len(selected) != count+1:
        raise ValueError(f'Only {len(selected)-1} suitable western sites; expected {count}')
    for i,c in enumerate(selected):
        c['name'] = f'{i:03d}_{c["category"]}'
    return selected


def connection_table(net):
    connections = {}
    for c in net.findall('connection'):
        if c.get('dir') == 't':
            continue
        src = c.get('from')+'_'+c.get('fromLane')
        connections.setdefault(src, []).append(c.get('via') or c.get('to')+'_'+c.get('toLane'))
    return connections


def poi_cases(index, net):
    """The exact default spawn and every quick-travel point, each driven forward 90 m."""
    lanes = {l['id']: l for l in index['lanes'] if len(l['points']) > 1}
    connections = connection_table(net)
    cases = []
    for name, record in [('spawn', index['spawn'])] + [(v['id'], v) for v in index.get('pois', [])]:
        lane = lanes[record['lane']]
        p = list(beam_point(record['position']))
        pts = [beam_point(q) for q in lane['points']]
        i = min(range(len(pts)-1), key=lambda i: segment_distance(p, pts[i], pts[i+1]))
        length = max(math.dist(pts[i][:2], pts[i+1][:2]), 1e-6)
        cases.append(dict(name=f'{len(cases):03d}_{name}', lane=lane['id'], point=p, width=lane['width'],
                          direction=[(pts[i+1][k]-pts[i][k])/length for k in (0, 1)]+[0], category='poi',
                          title=record.get('title', 'Start'),
                          path=drive_path(lane['id'], p, lanes, connections)))
    return cases


def suite(mid, pois=False, world=None):
    folder = Path(world) if world else ROOT/'game/data'/mid
    build = Path(world) if world else ROOT/'data/build'/mid
    index = json.loads((folder/'index.json').read_text(encoding='utf8'))
    net = ET.parse(build/'network.net.xml').getroot()
    if pois:
        return {'map': mid, 'cases': poi_cases(index, net),
                'note': 'Default spawn plus every quick-travel point. Synthetic QA routes.'}
    cases = western_cases(index,net)
    return {'map':mid, 'cases':cases, 'note':'Exact default spawn plus 10 distinct sites west of spawn. Synthetic QA routes.'}


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--map', required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--pois', action='store_true', help='Cases at the quick-travel points instead of the west')
    p.add_argument('--world', type=Path, help='World v2 folder instead of game/data + data/build')
    args=p.parse_args()
    data=suite(args.map, args.pois, args.world)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf8')
    print(f'{args.map}: {len(data["cases"])} cases')
