"""Replay source elevation from an offline world; measure profiles inside its bbox.

Outputs are derived profiles, not surveyed elevations or engine acceptance.
"""
import argparse
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from akadem_maps.context import BuildContext, read_json, write_json
from akadem_maps.core import prepare, road_elevation


def metrics(profiles):
    lengths, grades, changes = [], [], []
    ascent = descent = 0.
    for points in profiles.values():
        p = np.asarray(points)
        if len(p) < 3:
            continue
        ds = np.linalg.norm(np.diff(p[:, :2], axis=0), axis=1)
        s = np.r_[0., np.cumsum(ds)]
        # Compare at the same physical spacing, not at arbitrary source knots.
        stations = np.arange(0., s[-1], 2.)
        if len(stations) < 3:
            continue
        dz = np.diff(np.interp(stations, s, p[:, 2]))
        g = dz/2.
        lengths.extend([2.]*len(g))
        grades.extend(abs(g))
        changes.extend(abs(np.diff(g)))
        ascent += float(np.maximum(dz, 0).sum())
        descent += float(np.maximum(-dz, 0).sum())
    length = sum(lengths)
    if not lengths:
        return {'length_m': 0.}
    return {'sample_step_m': 2., 'length_m': length, 'ascent_m': ascent, 'descent_m': descent,
            'grade_rms': float(np.sqrt(np.average(np.square(grades), weights=lengths))),
            'grade_p95': float(np.percentile(grades, 95)),
            'grade_variation_per_km': sum(changes)/max(length/1000, 1e-9),
            'grade_breaks_over_2pp': int(sum(c > .02 for c in changes))}


def main():
    import sumolib
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--world', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    cfg = read_json(args.world/'config.json')
    context = BuildContext(args.output, args.world/'inputs/raw', args.world, offline=True)
    terrain = prepare.Terrain(cfg, context)
    base = terrain.sample(*cfg['center'])
    net = sumolib.net.readNet(str(args.world/'network.net.xml'))
    root = ET.parse(args.world/'corrected.osm').getroot()
    nodes = {n.get('id'): (float(n.get('lon')), float(n.get('lat'))) for n in root.findall('node')}
    tags = lambda w: {t.get('k'): t.get('v') for t in w.findall('tag')}
    sample = lambda x, y: terrain.sample(*net.convertXY2LonLat(x, y))-base
    profiles, ground, report = road_elevation.ground_profiles(
        root, nodes, tags, prepare.drivable, net.convertLonLat2XY, sample)
    heights, refs, node_report = prepare.road_node_heights(
        root, nodes, tags, lambda lon, lat: terrain.sample(lon, lat)-base,
        ground_override=ground, crest=True, dense_pairs=True)
    structures = {w.get('id') for w in root.findall('way') if prepare.structure_level(tags(w)) != 0}
    final = road_elevation.constrained_profiles(profiles, heights, structures)
    way_tags = {w.get('id'): tags(w) for w in root.findall('way')}
    road_elevation.deck_clearance(final, refs,
        {w: prepare.surface_audit.structure(way_tags[w]) for w in final},
        prepare.BRIDGE_CLEARANCE['road'], prepare.MAX_RAMP_GRADE['default'])
    west, south, east, north = cfg['bbox']
    saved = {}
    for wid, p in profiles.items():
        if wid in structures:
            continue
        # Keep contiguous station runs; never bridge excursions outside the bbox.
        run = []
        runs = []
        for point in p['points']:
            lon, lat = net.convertXY2LonLat(*point[:2])
            if west <= lon <= east and south <= lat <= north:
                run.append(point)
            elif run:
                runs.append(run)
                run = []
        if run:
            runs.append(run)
        for i, run in enumerate(runs):
            if len(run) < 3:
                continue
            # Final profiles contain inserted OSM knots: retain those for diagnostics.
            fp = np.asarray(final[wid])
            start = int(np.argmin(np.linalg.norm(fp[:, :2]-np.array(run[0][:2]), axis=1)))
            end = len(fp)-1-int(np.argmin(np.linalg.norm(fp[::-1, :2]-np.array(run[-1][:2]), axis=1)))
            saved[f'{wid}:{i}'] = {'tags': way_tags[wid], 'raw': [(x,y,sample(x,y)) for x,y,z in run],
                                  'filtered': run, 'final': final[wid][start:end+1]}
    summary = {stage: metrics({k:p[stage] for k,p in saved.items()}) for stage in ('raw','filtered','final')}
    write_json(args.output/'profiles.json', saved)
    write_json(args.output/'summary.json', summary)
    write_json(args.output/'filter.json', report)
    write_json(args.output/'nodes.json', node_report)
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
