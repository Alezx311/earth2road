"""Record actual Godot gameplay and the location/export UI in an isolated take."""
import argparse
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from akadem_maps.runtime import godot_binary


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    env = {**os.environ, 'AKADEM_PORT': '8798', 'AKADEM_MAP': 'kyiv_maidan',
           'AKADEM_MAP_MENU': '', 'PYTHONUTF8': '1'}
    with (output/'bridge.log').open('w', encoding='utf-8') as log:
        bridge = subprocess.Popen([sys.executable, str(ROOT/'tools/traffic.py'), '--port', '8798',
                                   '--map', 'kyiv_maidan', '--density', '120'], cwd=ROOT, env=env,
                                  stdout=log, stderr=subprocess.STDOUT,
                                  creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        try:
            with (output/'godot.log').open('w', encoding='utf-8') as game_log:
                subprocess.run([str(godot_binary()), '--path', str(ROOT/'game'), '--resolution', '1920x1080',
                                '--script', 'res://scripts/capture_promo.gd', '--', '--density=120',
                                f'--capture-output={output}'], cwd=ROOT, env=env, timeout=300, check=True,
                               stdout=game_log, stderr=subprocess.STDOUT)
        finally:
            if bridge.poll() is None:
                bridge.terminate()
            bridge.wait(timeout=15)
    for name, expected in [('godot-drive', 240), ('picker', 150), ('export', 150)]:
        count = len(list((output/name).glob('*.jpg')))
        if count != expected:
            raise RuntimeError(f'Incomplete capture {name}: {count}')
    print('GODOT_PROMO_COMPLETE', output)


if __name__ == '__main__':
    main()
