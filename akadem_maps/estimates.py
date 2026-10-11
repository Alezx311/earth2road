"""Rough run-time estimates for map builds and BeamNG exports, shown in the game UI.

Model: minutes = overhead + rate × size, as a [low, high] range. Size is km² for a build
and the number of world tiles for an export. Base rates come from measured runs on this
project (2026-09-28 … 2026-10-06, one desktop):

build legacy  Poltava region 3×3 km 3 min (rural); Khreshchatyk 2 km 5.6 min (with Godot
              export); Bilychi 4×4 km 14.6 min; Manhattan 4×4 km 26 min.
build v2      Podil 2×2 km 12–20 min; Bilychi 4×4 km 68 min; Khreshchatyk 2 km 44 min.
export        compact: 64 tiles 2.6 min (rural), 111 tiles 7 min, 112 tiles with Local Visual
              DNA 18 min; pre-optimization (balanced) 331 tiles 52 min.

Every finished run is appended to logs/timings.jsonl; once two runs of a mode exist their
per-unit rates replace the base rates.

This area-only model is the fallback (and the BeamNG export estimate). The picker's build
estimate is density-aware: see build_estimate below, fed by akadem_maps/area_probe.py."""
import json
from pathlib import Path
from statistics import median

# kind -> mode -> (overhead_low, overhead_high, rate_low, rate_high), minutes.
BASE = {
    'build': {
        'legacy': (0.5, 2.0, 0.3, 1.6),
        'v2': (2.0, 6.0, 3.5, 11.0),
    },
    'export': {
        'compact': (0.5, 2.0, 0.04, 0.17),
        'balanced': (0.5, 2.0, 0.06, 0.25),
    },
}
HISTORY_RUNS = 8
MIN_RUNS = 2


def base_mode(kind, mode):
    """BeamNG modes other than compact share the balanced (full-detail) base."""
    if kind == 'export' and mode != 'compact':
        return 'balanced'
    return mode


def read_history(path):
    runs = []
    try:
        lines = Path(path).read_text(encoding='utf8').splitlines()
    except (FileNotFoundError, UnicodeDecodeError):
        return runs
    for line in lines:
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if (isinstance(record, dict) and record.get('kind') in BASE and isinstance(record.get('mode'), str)
                and isinstance(record.get('size'), (int, float)) and record['size'] > 0
                and isinstance(record.get('seconds'), (int, float)) and record['seconds'] > 0):
            runs.append(record)
    return runs


def coefficients(kind, mode, history=()):
    """(overhead_low, overhead_high, rate_low, rate_high) and the number of runs behind it."""
    o_lo, o_hi, r_lo, r_hi = BASE[kind][base_mode(kind, mode)]
    rates = [max(0.0, r['seconds'] / 60 - o_lo) / r['size']
             for r in history if r['kind'] == kind and r['mode'] == mode][-HISTORY_RUNS:]
    if len(rates) < MIN_RUNS:
        return (o_lo, o_hi, r_lo, r_hi), 0
    mid = median(rates)
    return (o_lo, o_hi, min(min(rates), mid * 0.8), max(max(rates), mid * 1.25)), len(rates)


def estimate(kind, mode, size, history=()):
    """[low, high] minutes for one run of `size` (km² or tiles)."""
    (o_lo, o_hi, r_lo, r_hi), _ = coefficients(kind, mode, history)
    return [o_lo + r_lo * size, o_hi + r_hi * size]


def table(history=()):
    """All coefficients for the game, which multiplies by the size itself."""
    out = {}
    for kind, modes in BASE.items():
        names = list(modes) if kind == 'build' else list(modes) + sorted(
            {r['mode'] for r in history if r['kind'] == 'export'} - set(modes))
        for mode in names:
            (o_lo, o_hi, r_lo, r_hi), runs = coefficients(kind, mode, history)
            out.setdefault(kind, {})[mode] = {'overhead': [o_lo, o_hi], 'rate': [r_lo, r_hi], 'runs': runs}
    return out


def record(path, kind, mode, size, seconds, **extra):
    """Appends one finished run; a failed write never fails the run itself."""
    try:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('a', encoding='utf8') as f:
            f.write(json.dumps({'kind': kind, 'mode': mode, 'size': round(size, 3),
                                'seconds': round(seconds, 1), **extra}) + '\n')
    except OSError:
        pass


# --- Density-aware build estimate (2026-10-11) --------------------------------------
#
# Before a build, akadem_maps/area_probe.py counts what the area contains (roads, road
# nodes, buildings, missing DEM tiles, whether OSM is already local). Each group of
# pipeline stages costs a nonnegative combination of those counts; the coefficients
# were fitted with tools/estimate.py --calibrate on measured runs of one desktop (see
# STAGE_BASE). A machine's own finished runs then scale each group by the median ratio
# actual / predicted, so a faster or slower computer converges to its own times.

# Pipeline stage names (build events, Godot export/install) -> estimate group.
STAGE_GROUPS = {
    'download': ('sources', 'geometry', 'terrain'),
    'roads': ('network', 'road_geometry', 'roads'),
    'buildings': ('buildings',),
    'scenery': ('setup', 'start', 'ground', 'landcover', 'trees', 'signs', 'tiles', 'surface_audit', 'provenance'),
    'export': ('export', 'install', 'godot_export_and_demand'),
}
GROUP_ORDER = tuple(STAGE_GROUPS)
TERMS = {
    'download': ('const', 'osm_fetch', 'osm_fetch_knodes', 'dem_missing'),
    'roads': ('const', 'knodes', 'road_km'),
    'buildings': ('const', 'kbuildings'),
    'scenery': ('const', 'area_km2', 'road_km', 'kbuildings'),
    'export': ('const', 'knodes', 'kbuildings'),
}
# Seconds per unit of each term: tools/estimate.py --calibrate on 13 runs (2026-10-11,
# Ryzen 16 threads, BeamNG running alongside): Kyiv centre 250/500 m, Vynohradar 1-1.5 km,
# Poltava fields 1.5-3 km, Detroit 1-1.5 km, Singapore 1-4 km (out/calibration, ignored).
# Only two of them downloaded OSM, so 'download' is set by hand to match those two
# (Vynohradar 15.5 s, Singapore 4 km 29 s); network speed dominates it anyway.
STAGE_BASE = {
    'legacy': {
        'download': {'const': 1.0, 'osm_fetch': 8.0, 'osm_fetch_knodes': 1.5, 'dem_missing': 1.5},
        'roads': {'const': 0.0, 'knodes': 22.616, 'road_km': 0.386},
        'buildings': {'const': 0.611, 'kbuildings': 13.043},
        'scenery': {'const': 0.0, 'area_km2': 0.0, 'road_km': 0.431, 'kbuildings': 38.561},
        'export': {'const': 0.128, 'knodes': 2.336, 'kbuildings': 0.0},
    },
    'v2': {
        'download': {'const': 1.0, 'osm_fetch': 8.0, 'osm_fetch_knodes': 1.5, 'dem_missing': 1.5},
        'roads': {'const': 3.753, 'knodes': 21.263, 'road_km': 3.997},
        'buildings': {'const': 0.929, 'kbuildings': 19.392},
        'scenery': {'const': 0.031, 'area_km2': 0.0, 'road_km': 1.78, 'kbuildings': 15.492},
        'export': {'const': 0.353, 'knodes': 2.134, 'kbuildings': 2.169},
    },
}
# Road nodes per km² when nothing but the area is known: open country .. dense centre.
AREA_ONLY_KNODES_PER_KM2 = (0.3, 8.0)
BUILDINGS_PER_ROAD_NODE = 0.6
# Road length per node when a server returned counts without length (calibration areas:
# 12 m in a city centre .. 52 m in fields).
KM_PER_ROAD_NODE = 0.025
# Leave-one-out actual / predicted of those runs spans 0.40-1.91; this range holds 12
# of 13. Wide on purpose: it narrows only from this machine's own builds.
BASE_SPREAD = (0.55, 1.9)
MACHINE_SPREAD_RUNS = 5
FACTOR_LIMITS = (0.3, 4.0)


def stage_group(stage):
    for group, stages in STAGE_GROUPS.items():
        if stage in stages:
            return group
    return None


def term_values(features):
    fetch = 0.0 if features.get('osm_ready') else 1.0
    knodes = features.get('road_nodes', 0) / 1000
    return {'const': 1.0, 'osm_fetch': fetch, 'osm_fetch_knodes': fetch * knodes,
            'dem_missing': float(features.get('dem_missing', 0)), 'knodes': knodes,
            'road_km': float(features.get('road_km', features.get('road_nodes', 0) * KM_PER_ROAD_NODE)),
            'kbuildings': features.get('buildings', 0) / 1000,
            'area_km2': float(features.get('area_km2', 0))}


def predict(features, mode, factors=None, base=None):
    """Expected seconds per group for counted features (no range)."""
    base = base or STAGE_BASE
    coefficients = base[mode if mode in base else 'legacy']
    values = term_values(features)
    stages = {}
    for group in GROUP_ORDER:
        seconds = sum(coefficients[group].get(term, 0.0) * values[term] for term in TERMS[group])
        stages[group] = seconds * (factors or {}).get(group, 1.0)
    return stages


def stage_seconds(rows):
    """Seconds per group from progress events: generator logs (ISO 'time') or probe
    events ('elapsed_s'). The interval of a stage ends at the next stage or result."""
    from datetime import datetime
    def at(row):
        if 'elapsed_s' in row:
            return float(row['elapsed_s'])
        return datetime.fromisoformat(row['time']).timestamp()
    marks = [r for r in rows if r.get('event') in ('stage', 'result') and ('time' in r or 'elapsed_s' in r)]
    seconds = {}
    for a, b in zip(marks, marks[1:]):
        group = stage_group(a.get('stage'))
        if a.get('event') == 'stage' and group:
            seconds[group] = seconds.get(group, 0.0) + max(0.0, at(b) - at(a))
    return seconds


def _counted_runs(history, mode):
    return [run for run in history if run.get('kind') == 'build' and run.get('mode') == mode
            and isinstance(run.get('features'), dict) and isinstance(run.get('stages'), dict)
            and run['features'].get('basis', 'area_only') != 'area_only']


def machine_factors(history, mode, base=None):
    """Per-group median actual / predicted over this machine's recent runs with counted
    features, and their total ratios (for the range)."""
    runs = _counted_runs(history, mode)[-HISTORY_RUNS:]
    ratios, totals = {}, []
    for run in runs:
        expected = predict(run['features'], mode, base=base)
        for group, actual in run['stages'].items():
            if expected.get(group, 0) > 1.0 and actual > 0:
                ratios.setdefault(group, []).append(actual / expected[group])
        total = sum(expected.values())
        if total > 0:
            totals.append(sum(run['stages'].values()) / total)
    factors = {g: min(FACTOR_LIMITS[1], max(FACTOR_LIMITS[0], median(r)))
               for g, r in ratios.items() if len(r) >= MIN_RUNS}
    return factors, totals


def build_estimate(features, mode, history=(), base=None):
    """What the picker shows: expected seconds, an honest [low, high], seconds per group.

    With counted features the range is the calibration spread, replaced by this
    machine's own spread after MACHINE_SPREAD_RUNS runs. With area only, the range spans open
    country to a dense centre and `basis` says so."""
    factors, totals = machine_factors(history, mode, base)
    basis = features.get('basis', 'area_only')
    if basis == 'area_only':
        area = float(features.get('area_km2', 0))
        cases = []
        for density in AREA_ONLY_KNODES_PER_KM2:
            nodes = density * 1000 * area
            guess = {**features, 'road_nodes': nodes, 'roads': nodes / 4,
                     'buildings': nodes * BUILDINGS_PER_ROAD_NODE}
            cases.append(predict(guess, mode, factors, base))
        stages = {g: (cases[0][g] + cases[1][g]) / 2 for g in GROUP_ORDER}
        low, high = sum(cases[0].values()) * BASE_SPREAD[0], sum(cases[1].values()) * BASE_SPREAD[1]
    else:
        stages = predict(features, mode, factors, base)
        spread = BASE_SPREAD
        if len(totals) >= MACHINE_SPREAD_RUNS:
            # This machine's own scatter around its corrected prediction, never under ±20 %.
            mid = median(totals)
            spread = (min(0.8, min(totals) / mid * 0.95), max(1.25, max(totals) / mid * 1.05))
        total = sum(stages.values())
        low, high = total * spread[0], total * spread[1]
    expected = sum(stages.values())
    return {'expected_s': round(expected, 1), 'seconds': [round(min(low, expected), 1), round(max(high, expected), 1)],
            'stages': {g: round(s, 2) for g, s in stages.items()}, 'basis': basis, 'mode': mode,
            'machine_runs': len(totals), 'stage_groups': {g: list(s) for g, s in STAGE_GROUPS.items()}}


def nnls(a, b, iterations=200):
    """Lawson-Hanson nonnegative least squares (no SciPy dependency)."""
    import numpy as np
    a, b = np.asarray(a, float), np.asarray(b, float)
    n = a.shape[1]
    passive = np.zeros(n, bool)
    x = np.zeros(n)
    for _ in range(iterations):
        w = a.T @ (b - a @ x)
        if passive.all() or np.max(np.where(passive, -np.inf, w)) <= 1e-10:
            break
        passive[np.argmax(np.where(passive, -np.inf, w))] = True
        while True:
            z = np.zeros(n)
            z[passive] = np.linalg.lstsq(a[:, passive], b, rcond=None)[0]
            if (z[passive] > 0).all():
                x = z
                break
            mask = passive & (z <= 0)
            alpha = np.min(x[mask] / (x[mask] - z[mask]))
            x = x + alpha * (z - x)
            passive &= x > 1e-12
    return x


def fit(runs, mode):
    """Coefficients per group from runs [{'mode', 'features', 'stages'}], NNLS on
    relative error so a 30 s and a 30 min run weigh alike."""
    chosen = [r for r in runs if r.get('mode') == mode]
    result = {}
    for group in GROUP_ORDER:
        rows, targets = [], []
        for run in chosen:
            actual = run['stages'].get(group, 0.0)
            values = term_values(run['features'])
            scale = 1.0 / max(5.0, actual)
            rows.append([values[t] * scale for t in TERMS[group]])
            targets.append(actual * scale)
        x = nnls(rows, targets) if rows else [0.0] * len(TERMS[group])
        result[group] = {t: round(float(v), 6) for t, v in zip(TERMS[group], x)}
    return result
