"""Owned, cancellable BeamNG ZIP export for the in-game map menu."""
import argparse
from contextlib import redirect_stdout
from datetime import datetime, timezone
import os
from pathlib import Path
import re
import shutil
import sys
import time
import traceback
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from akadem_maps.cli import Events
from akadem_maps.context import atomic_directory, read_json, sha256, write_json
from akadem_maps.adapters.beamng.export import validate_export
from akadem_maps.adapters.beamng.beamng_geometry import optimization_mode
from akadem_maps.adapters.beamng.export_beamng import export_map, deterministic_zip
from akadem_maps.estimates import record

TIMINGS = ROOT/'logs/timings.jsonl'


def tile_count(mid, root=ROOT):
    """Export size measure for estimates (akadem_maps/estimates.py)."""
    tiles = Path(root)/'game/data'/mid/'tiles'
    return sum(1 for p in tiles.iterdir() if p.is_file()) if tiles.is_dir() else 0


def export_installed(mid, destination, events, *, root=ROOT, optimization='balanced', texture_style='procedural'):
    """Publish one fresh run directory only after its ZIP passes validation."""
    if not re.fullmatch('[a-z0-9_]+', mid):
        raise ValueError('Invalid map id')
    optimization = optimization_mode(optimization)
    root = Path(root).resolve()
    source = root/'game/data'/mid
    net = root/'data/build'/mid/'network.net.xml'
    for path in (source/'index.json', source/'tiles', net):
        if not path.exists():
            raise FileNotFoundError(f'Missing map data: {path}')
    if sha256(net) != read_json(source/'index.json')['network_sha256']:
        raise ValueError('SUMO network hash differs from world index; regenerate the snapshot')
    destination = Path(destination).expanduser().resolve()
    # Do not put export output inside source data (including through junctions).
    for protected in (root/'game/data', root/'data/build', root/'config'):
        if destination.is_relative_to(protected.resolve()):
            raise ValueError('Choose an output folder outside the map source data')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')
    output = destination/f'{mid}-{stamp}-{uuid.uuid4().hex[:8]}'
    zip_name = f'earth2road_{mid}.zip'
    with atomic_directory(output) as stage:
        report = export_map(mid, stage/'mod', source_root=root, namespace=True,
                            package_zip=False, emit=events.emit, optimization=optimization,
                            texture_style=texture_style)
        level = stage/'mod/levels'/report['level_id']
        info = read_json(level/'info.json')
        index = read_json(source/'index.json')
        info['title'] = index.get('name', mid)
        info['description'] = ('Exported from Earth2Road. Signal timings and generated scenery are synthetic. '
                               + index.get('attribution', ''))
        write_json(level/'info.json', info)
        reports = stage/'reports'
        reports.mkdir()
        shutil.move(str(stage/'mod.performance.json'), str(reports/'performance.json'))
        for name in ('kyiv-manifest.json', 'kyiv-baseline.json', 'placement-corrections.json', 'building-conflicts.json'):
            shutil.move(str(level/name), str(reports/name))
        events.emit('stage', stage='package')
        deterministic_zip(stage/'mod', stage/zip_name)
        events.emit('stage', stage='validate_zip')
        validate_export(stage/zip_name)
        write_json(stage/'artifact.json', {'map': mid, 'level_id': report['level_id'],
                   'zip': zip_name, 'sha256': sha256(stage/zip_name), 'optimization': optimization, 'texture_style': texture_style,
                   'runtime_verified': False})
    return {'id': mid, 'output': str(output), 'zip': str(output/zip_name), 'optimization': optimization, 'texture_style': texture_style,
            'runtime_verified': False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--map', required=True)
    parser.add_argument('--destination', type=Path, required=True)
    parser.add_argument('--events', required=True)
    parser.add_argument('--log', type=Path, required=True)
    parser.add_argument('--parent-pid', type=int, required=True)
    parser.add_argument('--cancel-file', type=Path, required=True)
    parser.add_argument('--optimization', type=optimization_mode, default='balanced', help='legacy, balanced, compact, or balanced+writer/kerbs/terrain')
    parser.add_argument('--texture-style', default='procedural', help='facade textures: an id from config/visuals/texture_styles.json')
    args = parser.parse_args(argv)
    args.log.parent.mkdir(parents=True, exist_ok=True)
    watcher = None
    with args.log.open('w', encoding='utf8', buffering=1) as log:
        from contextlib import redirect_stderr
        with redirect_stderr(log), redirect_stdout(log):
            events = Events(args.events)
            try:
                if os.name == 'nt':
                    from generator_lifecycle import watch_windows
                    watcher = watch_windows(args.parent_pid, args.cancel_file)
                else:
                    from generate_map import cancel_on_sigterm, watch_parent
                    cancel_on_sigterm()
                    watch_parent(os.getppid())
                if args.cancel_file.exists():
                    raise KeyboardInterrupt
                started = time.monotonic()
                result = export_installed(args.map, args.destination, events, optimization=args.optimization,
                                          texture_style=args.texture_style)
                tiles = tile_count(args.map)
                if tiles:
                    record(TIMINGS, 'export', result['optimization'], tiles, time.monotonic() - started, id=args.map)
                if watcher:
                    watcher.set()
                events.emit('result', **result)
                return 0
            except KeyboardInterrupt:
                events.emit('error', code='cancelled', message='Export cancelled')
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
