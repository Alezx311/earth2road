#!/usr/bin/env python3
"""Prints run-time estimate coefficients as JSON for the game (akadem_maps/estimates.py).

    .venv/Scripts/python.exe tools/estimate.py
    .venv/Scripts/python.exe tools/estimate.py --calibrate runs.json [more.json ...]

--calibrate fits the density-aware stage coefficients (estimates.STAGE_BASE) from
measured runs: JSON lists of {"mode", "features" (area_probe.probe), "stages"
(pipeline stage -> seconds) or "groups"}. It prints the coefficients and, per run,
the leave-one-out prediction, so the spread used for the displayed range is visible.
"""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from akadem_maps import estimates
from akadem_maps.estimates import read_history, table

TIMINGS = ROOT/'logs/timings.jsonl'


def grouped(run):
    if 'groups' in run:
        return run['groups']
    groups = {}
    for stage, seconds in run['stages'].items():
        group = estimates.stage_group(stage)
        if group:
            groups[group] = groups.get(group, 0.0) + seconds
    return groups


def calibrate(paths):
    runs = []
    for path in paths:
        for run in json.loads(Path(path).read_text(encoding='utf8')):
            if run.get('status', 'completed') == 'completed' and run.get('features', {}).get('basis') != 'area_only':
                runs.append({'id': run['id'], 'mode': run['mode'], 'features': run['features'], 'stages': grouped(run)})
    base, report = {}, []
    for mode in sorted({r['mode'] for r in runs}):
        chosen = [r for r in runs if r['mode'] == mode]
        base[mode] = estimates.fit(chosen, mode)
        for run in chosen:
            rest = [r for r in chosen if r is not run]
            loo = estimates.fit(rest, mode) if rest else base[mode]
            predicted = sum(estimates.predict(run['features'], mode, base={mode: loo}).values())
            actual = sum(run['stages'].values())
            report.append({'id': run['id'], 'mode': mode, 'actual_s': round(actual, 1),
                           'loo_predicted_s': round(predicted, 1), 'ratio': round(actual / max(predicted, 1e-6), 3)})
    return {'stage_base': base, 'leave_one_out': report}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--calibrate', nargs='+', metavar='RUNS_JSON')
    args = parser.parse_args(argv)
    if args.calibrate:
        print(json.dumps(calibrate(args.calibrate), indent=1))
        return 0
    print(json.dumps(table(read_history(TIMINGS))))
    return 0


if __name__ == '__main__':
    sys.exit(main())
