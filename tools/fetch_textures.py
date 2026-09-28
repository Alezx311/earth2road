#!/usr/bin/env python3
"""Download the CC0 texture sets listed in config/textures.json (ambientCG).
Keeps only colour/normal(GL)/roughness maps and records sha256 per file."""
import hashlib
import io
import json
from pathlib import Path
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT/'game/assets/textures'
MAPS = {'Color': 'albedo', 'NormalGL': 'normal', 'Roughness': 'roughness'}

def main():
    cfg = json.loads((ROOT/'config/textures.json').read_text())
    DEST.mkdir(parents=True, exist_ok=True)
    manifest_path = DEST/'manifest.json'
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    for name, asset in cfg['sets'].items():
        folder = DEST/name
        if manifest.get(name, {}).get('asset') == asset and all((folder/f'{m}.jpg').exists() for m in MAPS.values()):
            continue
        url = f"https://ambientcg.com/get?file={asset}_{cfg['resolution']}.zip"
        blob = subprocess.run(['curl', '-fsSL', '--retry', '2', '--max-time', '300', url], check=True, capture_output=True).stdout
        folder.mkdir(exist_ok=True)
        files = {}
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            for entry in z.namelist():
                for key, out in MAPS.items():
                    if entry.endswith(f'_{key}.jpg'):
                        data = z.read(entry)
                        (folder/f'{out}.jpg').write_bytes(data)
                        files[out] = hashlib.sha256(data).hexdigest()
        missing = set(MAPS.values())-set(files)
        if missing:
            raise RuntimeError(f'{asset}: missing maps {missing}')
        manifest[name] = {'asset': asset, 'source': url, 'license': 'CC0-1.0 (ambientCG)', 'zip_sha256': hashlib.sha256(blob).hexdigest(), 'files': files}
        print('texture', name, asset)
    manifest_path.write_text(json.dumps(manifest, indent=2))

if __name__ == '__main__':
    main()
