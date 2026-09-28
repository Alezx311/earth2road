#!/usr/bin/env python3
"""Download third-party asset packs listed in config/assets.json, verify sha256 and
extract only the listed files. Idempotent: skips packs whose manifest already matches."""
import hashlib
import io
import json
from pathlib import Path
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]

def main():
    cfg = json.loads((ROOT/'config/assets.json').read_text())
    for name, pack in cfg['packs'].items():
        dest = ROOT/pack['dest']
        manifest_path = dest/'manifest.json'
        if manifest_path.exists() and json.loads(manifest_path.read_text()).get('sha256') == pack['sha256']:
            continue
        cache = ROOT/'.cache/downloads'/Path(pack['url']).name
        cache.parent.mkdir(parents=True, exist_ok=True)
        if not cache.exists():
            subprocess.run(['curl', '-fsSL', '--retry', '2', '--max-time', '600', pack['url'], '-o', str(cache)], check=True)
        blob = cache.read_bytes()
        digest = hashlib.sha256(blob).hexdigest()
        if digest != pack['sha256']:
            raise RuntimeError(f'{name}: sha256 {digest} != {pack["sha256"]}')
        dest.mkdir(parents=True, exist_ok=True)
        (dest/'.gdignore').touch()
        files = {}
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            wanted = {pack['extract_prefix']+f: f for f in pack['files']} | {f: f for f in pack.get('keep', [])}
            for entry, out in wanted.items():
                data = z.read(entry)
                target = dest/out
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
                files[out] = hashlib.sha256(data).hexdigest()
        manifest_path.write_text(json.dumps({'pack': pack['name'], 'source': pack['url'], 'license': pack['license'], 'sha256': digest, 'files': files}, indent=2))
        print('assets', name, len(files), 'files')

if __name__ == '__main__':
    main()
