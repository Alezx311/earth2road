#!/usr/bin/env python3
"""Permanently deletes an installed map, for the in-game map menu (game/scripts/map_menu.gd).

    .venv/Scripts/python.exe tools/maps.py delete --id lviv_2 [--current kyiv_maidan]
        [--mods-dir <BeamNG mods>] [--exports-dir out/beamng]

Removes the Godot install (game/data/<id>, data/build/<id>), the generator outputs
(out/generated/<id>[-stamp][_godot][.logs]), the legacy OSM input cache that would keep the
id taken (generate_map.free_id), BeamNG ZIPs exported for this id (run folders whose
artifact.json names it) and earth2road_<id>.zip / akadem_drive_<id>.zip in the BeamNG mods
folder. Verified OSM snapshots are keyed by coverage, not map id, and are kept. A junction
or symlink is unlinked, never followed. Prints one JSON line: {"deleted": [...], "failed": [...]}
(the rest is still removed when one path fails) or {"error": "..."}."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import stat
import sys

ROOT = Path(__file__).resolve().parents[1]
GENERATED_RE = r'{mid}(-\d{{14}})?(_godot)?(\.logs)?'
EXPORT_RE = r'{mid}-\d{{8}}-\d{{6}}-[0-9a-f]{{8}}'


def mod_names(mid):
    return [f'earth2road_{mid}.zip', f'akadem_drive_{mid}.zip']


def is_link(path):
    return path.is_symlink() or (hasattr(os.path, 'isjunction') and os.path.isjunction(path))


def targets(mid, root=ROOT, mods_dir=None, exports_dir=None):
    """Every path delete() would remove, existing ones only."""
    root = Path(root)
    found = [root/'game/data'/mid, root/'data/build'/mid, root/'out/generated/.akadem-inputs'/f'{mid}.osm']
    generated = root/'out/generated'
    if generated.is_dir():
        pattern = re.compile(GENERATED_RE.format(mid=re.escape(mid)))
        found += sorted(p for p in generated.iterdir() if pattern.fullmatch(p.name))
    if exports_dir and Path(exports_dir).is_dir():
        pattern = re.compile(EXPORT_RE.format(mid=re.escape(mid)))
        for run in sorted(Path(exports_dir).iterdir()):
            if pattern.fullmatch(run.name) and run.is_dir() and not is_link(run):
                try:
                    if json.loads((run/'artifact.json').read_text(encoding='utf8')).get('map') == mid:
                        found.append(run)
                except (OSError, ValueError):
                    pass
    if mods_dir:
        found += [Path(mods_dir)/name for name in mod_names(mid)]
    return [p for p in found if p.exists() or is_link(p)]


def remove(path):
    if is_link(path) or not path.is_dir():
        try:
            path.unlink()
        except PermissionError:
            os.chmod(path, stat.S_IWRITE)
            path.unlink()
        return
    def writable(func, p, _exc):
        os.chmod(p, stat.S_IWRITE)
        func(p)
    shutil.rmtree(path, onexc=writable) if sys.version_info >= (3, 12) else shutil.rmtree(path, onerror=writable)


def delete(mid, root=ROOT, *, current='', mods_dir=None, exports_dir=None):
    if not re.fullmatch('[a-z0-9_]+', mid or ''):
        raise ValueError('Invalid map id')
    if mid == current:
        raise ValueError('The map is loaded; switch to another map first')
    root = Path(root)
    if not (root/'game/project.godot').is_file():
        raise ValueError(f'Not a game checkout (missing game/project.godot): {root}')
    deleted, failed = [], []
    for path in targets(mid, root, mods_dir, exports_dir):
        # Keep going: a ZIP held open by a running BeamNG must not leave the rest behind.
        try:
            remove(path)
            deleted.append(str(path))
        except OSError as exc:
            failed.append({'path': str(path), 'message': str(exc)})
    active = root/'game/data/active_map'
    if active.is_file() and active.read_text(encoding='utf8').strip() == mid:
        active.unlink()
        deleted.append(str(active))
    return {'id': mid, 'deleted': deleted, 'failed': failed}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    sub = p.add_subparsers(dest='command', required=True)
    d = sub.add_parser('delete')
    d.add_argument('--id', required=True)
    d.add_argument('--current', default='')
    d.add_argument('--mods-dir', type=Path)
    d.add_argument('--exports-dir', type=Path)
    a = p.parse_args(argv)
    try:
        result = delete(a.id, current=a.current, mods_dir=a.mods_dir, exports_dir=a.exports_dir)
    except (OSError, ValueError) as exc:
        print(json.dumps({'error': str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 1 if result['failed'] else 0


if __name__ == '__main__':
    sys.exit(main())
