#!/usr/bin/env python3
"""Build, export and install a Godot map around a point anywhere on Earth.

A thin wrapper over the existing pipeline (terra-drive build --bbox → export godot →
install --activate) for the in-game location picker (game/scripts/location_picker.gd)
and for the command line:

    .venv/Scripts/python.exe tools/generate_map.py --lat 49.8419 --lon 24.0316 --size-km 1.5 --name "Lviv centre"

Progress goes to --events as JSONL (the akadem_maps.cli event protocol): 'stage' records
carry `phase` (build/export/install), the pipeline `stage` and an overall `progress` 0..1;
the run ends with one 'result' (map id) or one 'error'. The human log goes to --log
(default: stderr). Nothing is installed unless every step succeeded, and an existing map
is never replaced: a taken id gets a numeric suffix."""
import argparse
from contextlib import redirect_stdout
from datetime import datetime
import math
import os
from pathlib import Path
import re
import signal
import sys
import threading
import time
import traceback
import unicodedata

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

KM_PER_DEG_LAT = 110.574
KM_PER_DEG_LON_EQUATOR = 111.320
MIN_SIZE_KM, MAX_SIZE_KM = 0.3, 5.0
# Share of the whole run per phase: the build (download, network, tiles) dominates.
PHASES = {'build': (0.0, 0.8), 'export': (0.8, 0.97), 'install': (0.97, 1.0)}
# Public Overpass servers, tried in order: any one of them is often overloaded (HTTP 504).
# Global, keyless instances from wiki.openstreetmap.org/wiki/Overpass_API (2026-09); kumi is
# no longer listed there but is kept last.
OVERPASS = ['https://overpass-api.de/api/interpreter',
            'https://overpass.private.coffee/api/interpreter',
            'https://overpass.kumi.systems/api/interpreter']
# RAM reserved per query (see prepare.fetch). A 5 km square of central Wrocław (70 MB, 98k
# ways) fit in 256 MiB; busy servers rejected the old 1 GiB with 504/429 while admitting this.
OVERPASS_MAXSIZE = 256 * 1024 * 1024
# Rough rectangle around Ukraine: only a default for the picker's road-sign checkbox.
UKRAINE_BOX = (22.1, 44.3, 40.3, 52.4)


def bbox_around(lat, lon, size_km):
    """[west, south, east, north] of a size_km × size_km square centred on the point."""
    if not (math.isfinite(lat) and math.isfinite(lon) and math.isfinite(size_km)):
        raise ValueError('Coordinates and size must be finite numbers')
    if not MIN_SIZE_KM <= size_km <= MAX_SIZE_KM:
        raise ValueError(f'Area size must be {MIN_SIZE_KM}–{MAX_SIZE_KM} km')
    half = size_km / 2
    dlat = half / KM_PER_DEG_LAT
    if not (-85 < lat - dlat and lat + dlat < 85):
        raise ValueError('Latitude must stay within ±85° (Web Mercator / OSM limit)')
    dlon = half / (KM_PER_DEG_LON_EQUATOR * math.cos(math.radians(lat)))
    west, east = lon - dlon, lon + dlon
    if west < -180 or east > 180:
        raise ValueError('The area crosses the antimeridian (±180° longitude), which is unsupported')
    return [round(west, 6), round(lat - dlat, 6), round(east, 6), round(lat + dlat, 6)]


def in_ukraine_box(lat, lon):
    w, s, e, n = UKRAINE_BOX
    return w <= lon <= e and s <= lat <= n


def slug(name, lat, lon):
    """A valid map id ([a-z0-9_]) from the name, else from the coordinates."""
    text = unicodedata.normalize('NFKD', name or '').encode('ascii', 'ignore').decode().lower()
    text = re.sub('[^a-z0-9]+', '_', text).strip('_')[:40].strip('_')
    if text and not text[0].isdigit():
        return text
    def part(v):  # 'm' marks south/west: '-' is not allowed in a map id
        return ('m' if v < 0 else '') + f'{abs(v):.4f}'.replace('.', '_')
    return f'geo_{part(lat)}_{part(lon)}'


def free_id(base, root=ROOT):
    """base, or base_2, base_3 … — whichever is installed neither in game/data nor data/build."""
    def taken(mid):
        return (root/'game/data'/mid).exists() or (root/'data/build'/mid).exists()
    if not taken(base):
        return base
    n = 2
    while taken(f'{base}_{n}'):
        n += 1
    return f'{base}_{n}'


def output_dirs(mid, root=ROOT, now=None):
    """Fresh world and export folders under out/generated (build steps refuse to overwrite)."""
    base = root/'out/generated'
    world, export = base/mid, base/f'{mid}_godot'
    if world.exists() or export.exists():
        stamp = (now or datetime.now()).strftime('%Y%m%d%H%M%S')
        world, export = base/f'{mid}-{stamp}', base/f'{mid}-{stamp}_godot'
    return world, export


def phase_emitter(events, phase):
    """Maps the pipeline's own progress (0..1 per command) onto the whole run."""
    lo, hi = PHASES[phase]
    def emit(event, **data):
        if event == 'stage':
            fraction = float(data.get('progress') or 0.0)
            events.emit('stage', phase=phase, stage=data.get('stage', phase),
                        progress=round(lo + (hi - lo) * max(0.0, min(1.0, fraction)), 3))
        else:
            # One 'result' per run: a finished step reports as 'step'.
            events.emit('step' if event == 'result' else event, phase=phase, **data)
    return emit


def generate(lat, lon, size_km, name, events, *, mid=None, region_profile=None, root=ROOT, pipeline=None):
    """Runs build → export → install; returns the install result. `pipeline` replaces the
    three steps in tests: {'build': f, 'export': f, 'install': f}."""
    bbox = bbox_around(lat, lon, size_km)
    name = (name or '').strip() or f'{lat:.4f}, {lon:.4f}'
    mid = free_id(mid or slug(name, lat, lon), root)
    if region_profile is None:
        region_profile = 'ukraine' if in_ukraine_box(lat, lon) else 'experimental'
    world, export = output_dirs(mid, root)
    if pipeline is None:
        from akadem_maps.world import build_world
        from akadem_maps.adapters.godot.export import export_world
        from akadem_maps.adapters.godot.install import install_export
        pipeline = {'build': build_world, 'export': export_world, 'install': install_export}
    cfg = {'id': mid, 'name': name, 'bbox': bbox, 'center': [lon, lat], 'region_profile': region_profile,
           'overpass': OVERPASS[0], 'overpass_mirrors': OVERPASS[1:], 'overpass_maxsize': OVERPASS_MAXSIZE,
           'note': f'Generated by the in-game picker: {size_km:g} km square around {lat:.5f}, {lon:.5f}.'}
    events.emit('stage', phase='build', stage='start', progress=0.0, id=mid, bbox=bbox)
    pipeline['build'](cfg, world, config_root=root, emit=phase_emitter(events, 'build'))
    events.emit('stage', phase='export', stage='export', progress=PHASES['export'][0])
    pipeline['export'](world, export, offline=False)
    events.emit('stage', phase='install', stage='install', progress=PHASES['install'][0])
    result = pipeline['install'](export, root, replace=False, activate=True)
    return {'id': mid, 'name': name, 'bbox': bbox, 'region_profile': region_profile,
            'world': str(world), 'export': str(export), 'installed': result.get('installed', [])}


def cancel_on_sigterm():
    """SIGTERM (the game's Cancel, see location_picker.gd) cancels like Ctrl+C: the running
    subprocess (curl, netconvert…) is killed by subprocess.run and nothing is installed."""
    def cancel(signum, frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, cancel)


def watch_parent(parent, poll=1.0, grace=15.0, getppid=os.getppid, stop=None):
    """Cancel the run when `parent` (the game) is gone, e.g. after Ctrl+C in its terminal.

    The game starts the generator in its own session, so the terminal's SIGINT never
    reaches it or its curl. POSIX only: a dead parent shows as a changed getppid()."""
    def run():
        while getppid() == parent:
            time.sleep(poll)
        print(f'Parent process {parent} exited; cancelling', file=sys.stderr, flush=True)
        (stop or (lambda: os.kill(os.getpid(), signal.SIGTERM)))()
        if stop is None:
            time.sleep(grace)
            # Still here (stuck in native code): take the whole process group down.
            if os.getpgrp() == os.getpid():
                os.killpg(os.getpgrp(), signal.SIGKILL)
            os._exit(1)
    thread = threading.Thread(target=run, name='watch-parent', daemon=True)
    thread.start()
    return thread


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    p.add_argument('--lat', type=float, required=True)
    p.add_argument('--lon', type=float, required=True)
    p.add_argument('--size-km', type=float, default=1.5, help=f'square side, {MIN_SIZE_KM}–{MAX_SIZE_KM} km')
    p.add_argument('--name', default='')
    p.add_argument('--id', help='map id (default: from the name)')
    p.add_argument('--region-profile', choices=('ukraine', 'experimental'),
                   help='default: ukraine inside a rough box around Ukraine, else experimental')
    p.add_argument('--events', help='JSONL progress file, or - for stdout')
    p.add_argument('--log', type=Path, help='human-readable log (default: stderr)')
    p.add_argument('--exit-with-parent', action='store_true',
                   help='cancel when the parent process exits')
    p.add_argument('--parent-pid', type=int, help='owning game PID (also across Windows venv launchers)')
    p.add_argument('--cancel-file', type=Path, help='Windows cooperative cancellation request')
    a = p.parse_args(argv)
    if a.log:
        a.log.parent.mkdir(parents=True, exist_ok=True)
        sys.stderr = open(a.log, 'w', encoding='utf-8', buffering=1)
    if os.name != 'nt':
        cancel_on_sigterm()
        if a.exit_with_parent:
            watch_parent(os.getppid())
    from akadem_maps.cli import Events
    events = Events(a.events)
    watcher = None
    try:
        if os.name == 'nt':
            from generator_lifecycle import watch_windows
            watcher = watch_windows((a.parent_pid or os.getppid()) if a.exit_with_parent else 0, a.cancel_file)
        with redirect_stdout(sys.stderr):
            result = generate(a.lat, a.lon, a.size_km, a.name, events, mid=a.id, region_profile=a.region_profile)
        if watcher:
            watcher.set()
        events.emit('result', **result)
        return 0
    except KeyboardInterrupt:
        events.emit('error', code='cancelled', message='Cancelled; nothing was installed')
        return 130
    except Exception as exc:
        traceback.print_exc()
        events.emit('error', code=type(exc).__name__, message=str(exc))
        return 1
    finally:
        if watcher:
            watcher.set()
        events.close()


if __name__ == '__main__':
    sys.exit(main())
