#!/usr/bin/env python3
"""Fetch the pinned CC0 selection; verify upstream MD5 and pinned SHA256.
--lock records SHA256 on the first reviewed download. Every gltf dependency
(buffers/images) must be a manifest-listed local file: path escapes, absolute
paths and remote URLs are rejected; data: URIs are embedded by the format and
skipped. No live API at runtime.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
from urllib.parse import urlparse, unquote

ROOT = Path(__file__).resolve().parents[1]
ASSET_HOST = 'dl.polyhaven.org'


def safe_relative(name: str) -> bool:
    """Local relative gltf dependency: no scheme, no escapes, no separator tricks."""
    if not isinstance(name, str) or not name:
        return False
    if name.startswith(('/', '\\')) or '\\' in name or ':' in name:
        return False
    if urlparse(name).scheme:
        return False
    if '..' in Path(name).parts:
        return False
    return True


def gltf_dependencies(folder: Path, gltf_name: str) -> list:
    """Decoded local dependency names of a gltf (buffers and images).
    data: URIs carry their payload inline and need no file."""
    gltf = json.loads((folder / gltf_name).read_text())
    deps = []
    for buffer in gltf.get('buffers', []):
        uri = buffer.get('uri', '')
        if not uri.startswith('data:'):
            deps.append(unquote(uri))
    for image in gltf.get('images', []):
        uri = image.get('uri', '')
        if not uri.startswith('data:'):
            deps.append(unquote(uri))
    return deps


def validate_gltf_dependencies(folder: Path, gltf_name: str, files_spec: dict) -> list:
    """One problem string per bad dependency; empty list means the gltf is safe to load."""
    problems = []
    try:
        deps = gltf_dependencies(folder, gltf_name)
    except Exception as exc:
        return ['%s: cannot parse gltf: %s' % (gltf_name, exc)]
    for dep in dict.fromkeys(deps):
        if not safe_relative(dep):
            problems.append('%s: rejected dependency %r (escape/absolute/URL)'
                            % (gltf_name, dep))
        elif dep not in files_spec:
            problems.append('%s: dependency %r absent from manifest' % (gltf_name, dep))
        elif not (folder / dep).exists():
            problems.append('%s: dependency %r missing on disk' % (gltf_name, dep))
    return problems


def verify(path: Path, spec: dict) -> None:
    data = path.read_bytes()
    if len(data) != spec['size']:
        raise ValueError(f'{path}: size mismatch')
    if hashlib.md5(data).hexdigest() != spec['md5']:
        raise ValueError(f'{path}: MD5 mismatch')
    if 'sha256' in spec and hashlib.sha256(data).hexdigest() != spec['sha256']:
        raise ValueError(f'{path}: SHA256 mismatch')


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument('--lock', action='store_true')
    a = p.parse_args()
    manifest = ROOT / 'config/visuals/downloads.json'
    cfg = json.loads(manifest.read_text())
    for name, pack in cfg['packs'].items():
        slot = pack.get('slot', '')
        if not isinstance(slot, str) or not slot:
            raise ValueError(f'Pack {name}: missing "slot"')
        folder = ROOT / 'game/assets/visuals' / name
        folder.mkdir(parents=True, exist_ok=True)
        for relative, spec in pack['files'].items():
            path = folder / relative
            if not path.resolve().is_relative_to(folder.resolve()):
                raise ValueError(f'{name}: invalid asset path {relative!r}')
            if not safe_relative(relative):
                raise ValueError(f'{name}: unsafe manifest path {relative!r}')
            if urlparse(spec['url']).hostname != ASSET_HOST:
                raise ValueError(f'{name}: unexpected asset host for {relative}')
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists():
                temp = path.with_suffix(path.suffix + '.part')
                subprocess.run(['curl', '-fL', '--retry', '2', '--max-time', '180',
                                spec['url'], '-o', str(temp)], check=True)
                verify(temp, spec)
                temp.replace(path)  # atomic: same directory, fully verified before rename
            verify(path, spec)
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if a.lock:
                spec['sha256'] = digest
            elif 'sha256' not in spec:
                raise ValueError(f'{name}/{relative}: missing SHA256; use --lock for first reviewed acquisition')
        for relative in pack['files']:
            if relative.endswith('.gltf'):
                problems = validate_gltf_dependencies(folder, relative, pack['files'])
                if problems:
                    raise ValueError('%s: %s' % (name, '; '.join(problems)))
        (folder / 'PROVENANCE.json').write_text(json.dumps(pack, indent=2))
        print(name, 'verified', flush=True)
    if a.lock:
        manifest.write_text(json.dumps(cfg, indent=2) + '\n')


if __name__ == '__main__':
    main()