"""Build seam-crossing drive cases, compare audits, and classify old regressions.

All paths extend on both sides of the target; reverse cases deliberately test
the same surface in reverse in an isolated profile. They are not traffic routes.
"""
import argparse
from collections import Counter
import json
import math
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from akadem_maps.core.surface_audit import stations, xyz

SITES = {
    'ring_beresteiskyi': [('beresteiska', (1932, 1921)), ('beresteiska_east', (1996, 1906)),
                         ('nyvky', (539, 2063)), ('nyvky_west', (410, 2049)),
                         ('ring_exit', (-1276, -2969)), ('povitrianykh_syl', (5751, 831))],
    'akadem': [('akadem_041', (212.132, 984.431)), ('akadem_042', (-557.657, -1106.246))]}


def read(path):
    return json.loads(Path(path).read_text(encoding='utf8'))


def drive_cases(folder):
    folder = Path(folder)
    index = read(folder/'index.json')
    net = ET.parse(folder/'network.net.xml').getroot()
    lanes = {r['id']: r for r in index['lanes']}
    by_index = {(e.get('id'), l.get('index')): l.get('id') for e in net.findall('edge') for l in e.findall('lane')}
    paths = []
    for conn in net.findall('connection'):
        if conn.get('from', '').startswith(':'):
            continue
        start, end = (by_index.get((conn.get(k), conn.get(k+'Lane'))) for k in ('from', 'to'))
        if start not in lanes or end not in lanes:
            continue
        chain = [start]
        via = conn.get('via')
        while via and via not in chain and via in lanes:
            chain.append(via)
            following = [c for c in net.findall('connection') if c.get('from') == lanes[via]['edge']
                         and c.get('to') == conn.get('to') and c.get('toLane') == conn.get('toLane')]
            via = following[0].get('via') if following else None
        chain.append(end)
        points = []
        for lid in chain:
            segment = [xyz(p) for p in lanes[lid]['points']]
            points += segment[1:] if points and math.dist(points[-1][:2], segment[0][:2]) < .05 else segment
        if len(points) < 2:
            continue
        sampled = list(stations(points, 2))
        if len(sampled) >= 15:
            paths.append((chain, sampled))
    cases = []
    for name, target in SITES.get(index['id'], []):
        candidates = []
        for chain, samples in paths:
            i = min(range(len(samples)), key=lambda j: math.dist(samples[j][1][:2], target))
            distance = math.dist(samples[i][1][:2], target)
            if distance <= 25 and i >= 5 and len(samples)-i >= 6:
                a, c, b = samples[max(0,i-8)][1], samples[i][1], samples[min(len(samples)-1,i+8)][1]
                u, v = (c[0]-a[0],c[1]-a[1]), (b[0]-c[0],b[1]-c[1])
                turn = abs(u[0]*v[1]-u[1]*v[0])/(math.hypot(*u)*math.hypot(*v) or 1)
                candidates.append((distance, -turn, chain, samples, i))
        selected = []
        for preference in ('through', 'turn'):
            ordered = sorted(candidates, key=lambda c: (c[0], c[1]) if preference=='through' else (c[1], c[0]))
            if not ordered:
                raise ValueError(f'No continuous traversable path at {name}')
            item = next((c for c in ordered if c[2] not in [x[2] for x in selected]), ordered[0])
            selected.append(item)
            _, _, chain, samples, at = item
            path = [list(p) for _,p in samples[max(0,at-22):min(len(samples),at+23)]]
            for reverse in (False, True):
                route = list(reversed(path)) if reverse else path
                dx,dy = route[1][0]-route[0][0], route[1][1]-route[0][1]
                length = math.hypot(dx,dy)
                cases.append({'name': f'{name}_{preference}_{"reverse" if reverse else "forward"}',
                              'lane':chain[-1] if reverse else chain[0], 'category':'seam_traversal',
                              'point': route[0].copy(), 'direction':[dx/length,dy/length,0],
                              'width':min(lanes[l]['width'] for l in chain), 'path':route,
                              'target_xy': list(target), 'required_target_radius':8,
                              'source_lanes':chain, 'diagnostic_reverse':reverse})
    return {'map':index['id'],'cases':cases, 'note':'Must cross target; placement alone is not acceptance.'}


def compare(before, after):
    old, new = read(before), read(after)
    # Match grade-change locations spatially on the same lane, including internals.
    prior = {}
    for r in old['smooth']['all']:
        prior.setdefault(r['lane'], []).append(r)
    regressions = []
    for r in new['smooth']['all']:
        previous = max((p['change'] for p in prior.get(r['lane'], [])
                        if math.dist(p['beamng'][:2],r['beamng'][:2]) <= 3), default=0)
        if r['change'] > .05 and r['change'] > previous+.005:
            regressions.append({**r, 'baseline_change':previous})
    return {'before': old['steps'], 'after':new['steps'], 'new_grade_breaks_over_5pct':len(regressions),
            'grade_regressions':regressions, 'regression_site_classes':dict(Counter(r['classification'] for r in new.get('regression_sites',[]))),
            'acceptance':'pending', 'technical_gate': 'failed' if regressions or new['steps']['connected']['over_60cm'] else 'passed'}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    sub=p.add_subparsers(dest='command',required=True)
    d=sub.add_parser('drives');d.add_argument('world',type=Path);d.add_argument('output',type=Path)
    c=sub.add_parser('compare');c.add_argument('before',type=Path);c.add_argument('after',type=Path);c.add_argument('output',type=Path)
    args=p.parse_args()
    result=drive_cases(args.world) if args.command=='drives' else compare(args.before,args.after)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(args.output)


if __name__=='__main__':
    main()
