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
per-unit rates replace the base rates. Density (lanes, buildings) is unknown before a build,
so ranges stay wide: a dense centre lands near the top."""
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
