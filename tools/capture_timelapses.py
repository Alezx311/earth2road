"""Capture presentation frames with an owned traffic bridge and a fresh take folder."""
import argparse
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from akadem_maps.runtime import godot_binary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('maps', nargs='+')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--port', type=int, default=8798)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    env = {**os.environ, 'AKADEM_PORT': str(args.port), 'AKADEM_MAP_MENU': '', 'PYTHONUTF8': '1'}
    for mid in args.maps:
        take = output / mid
        if not (ROOT/'game/data'/mid/'index.json').is_file():
            raise ValueError(f'Unknown installed map: {mid}')
        env['AKADEM_MAP'] = mid
        print('CAPTURE_START', mid, flush=True)
        with (output/f'{mid}-bridge.log').open('w', encoding='utf-8') as bridge_log, \
             (output/f'{mid}-godot.log').open('w', encoding='utf-8') as game_log:
            bridge = subprocess.Popen([sys.executable, str(ROOT/'tools/traffic.py'), '--map', mid,
                                       '--port', str(args.port), '--density', '150', '--threads', '2'],
                                      cwd=ROOT, env=env, stdout=bridge_log, stderr=subprocess.STDOUT,
                                      creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            try:
                subprocess.run([str(godot_binary()), '--path', str(ROOT/'game'), '--resolution', '1920x1080',
                                '--', '--timelapse', '--density=150', '--timelapse-cars=50',
                                '--timelapse-overlay=false', f'--timelapse-output={take}'],
                               cwd=ROOT, env=env, stdout=game_log, stderr=subprocess.STDOUT,
                               timeout=1200, check=True)
            finally:
                if bridge.poll() is None:
                    bridge.terminate()
                bridge.wait(timeout=15)
        frames = sorted(take.glob('frame_*.jpg'))
        if len(frames) < 630:
            raise RuntimeError(f'Incomplete capture: {mid}: {len(frames)} frames')
        print('CAPTURE_DONE', mid, len(frames), flush=True)


if __name__ == '__main__':
    main()
