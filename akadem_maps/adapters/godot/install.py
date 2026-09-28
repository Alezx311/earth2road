"""Explicit installation of a Godot export into a game checkout.

Existing maps are never overwritten implicitly: ``replace`` moves the previous copy to
``.cache/replaced/`` first, and ``active_map`` changes only with ``activate``.
"""
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import re
import shutil
import uuid

from akadem_maps.context import read_json


def _sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def install_export(export, root, *, replace=False, activate=False):
    export, root = Path(export).resolve(), Path(root).resolve()
    info = read_json(export/'godot-export.json')
    mid = info['id']
    if not re.fullmatch('[a-z0-9_]+', mid):
        raise ValueError('Invalid map id in Godot export')
    pairs = [(export/'game/data'/mid, root/'game/data'/mid), (export/'data/build'/mid, root/'data/build'/mid)]
    for source, _ in pairs:
        if not source.is_dir():
            raise ValueError(f'Incomplete Godot export: {source.relative_to(export)}')
    index = read_json(pairs[0][0]/'index.json')
    if _sha256(pairs[1][0]/'network.net.xml') != index['network_sha256']:
        raise ValueError('Godot export network differs from its index')
    if not (root/'game/project.godot').is_file():
        raise ValueError(f'Not a game checkout (missing game/project.godot): {root}')
    existing = [dest for _, dest in pairs if dest.exists()]
    if existing and not replace:
        raise FileExistsError(f'Map {mid} is already installed; pass --replace to back it up and replace it')
    # Stage next to each destination first, so a failed copy leaves the old map intact.
    staged = []
    try:
        for source, dest in pairs:
            dest.parent.mkdir(parents=True, exist_ok=True)
            stage = dest.parent/f'.{mid}.install-{uuid.uuid4().hex}'
            shutil.copytree(source, stage)
            staged.append((stage, dest))
        backup = None
        if existing:
            backup = root/'.cache/replaced'/f"{mid}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
            for dest in existing:
                target = backup/dest.relative_to(root)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(dest), str(target))
        for stage, dest in staged:
            stage.rename(dest)
        staged = []
    finally:
        for stage, _ in staged:
            shutil.rmtree(stage, ignore_errors=True)
    source_roadworks = export/'data/raw/roadworks.geojson'
    if source_roadworks.exists() and not (root/'data/raw/roadworks.geojson').exists():
        (root/'data/raw').mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_roadworks, root/'data/raw/roadworks.geojson')
    if activate:
        (root/'game/data/active_map').write_text(mid+'\n', encoding='utf8')
    return {'id': mid, 'installed': [str(dest) for _, dest in pairs], 'replaced_backup': str(backup) if backup else None,
            'activated': bool(activate)}
