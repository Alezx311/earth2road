"""Capture a BeamNG take in a fresh isolated profile and preserve runtime evidence."""
import argparse
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from akadem_maps.adapters.beamng.beamng_geometry import beam_point


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--map', required=True)
    p.add_argument('--export', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--exe', type=Path, default=Path(r'C:\Program Files (x86)\Steam\steamapps\common\BeamNG.drive\Bin64\BeamNG.drive.x64.exe'))
    args = p.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    artifact = read(args.export/'artifact.json')
    manifest = read(args.export/'reports/kyiv-manifest.json')
    index = read(ROOT/'game/data'/args.map/'index.json')
    dz = manifest.get('vertical_offset', 0)
    def point(v):
        x, y, z = beam_point(v)
        return [x, y, z+dz]
    lane = next(v for v in index['lanes'] if v['id'] == index['spawn']['lane'])
    spawn = point(index['spawn']['position'])
    points = [point(v) for v in lane['points']]
    nearest = min(range(len(points)), key=lambda i: math.dist(points[i], spawn))
    path = [spawn]+points[nearest+1:]
    profile = output/'user/current'
    ext = profile/'mods/unpacked/earth2road_capture/lua/ge/extensions'
    ext.mkdir(parents=True)
    shutil.copy2(args.export/artifact['zip'], profile/'mods'/artifact['zip'])
    shutil.copy2(ROOT/'tools/beamng_promo.lua', ext/'earth2roadpromo.lua')
    config = {'level': artifact['level_id'], 'path': path, 'frames': 360,
              'samples': [point(l['points'][len(l['points'])//2]) for l in index['lanes'][::max(1, len(index['lanes'])//300)]],
              'overview': {'pos': [spawn[0]-160, spawn[1]-180, spawn[2]+160], 'look': spawn}}
    (profile/'earth2road-input.json').write_text(json.dumps(config), encoding='utf-8')
    (profile/'settings').mkdir()
    (profile/'settings/settings.json').write_text(json.dumps({
        'GraphicDisplayResolutions': '1920 1080', 'GraphicFullscreen': False,
        'GraphicOverallQuality': 'Normal', 'AudioMasterVol': 0,
        'fpsLimitBackgroundEnabled': False, 'PostFXMotionBlurEnabled': False}), encoding='utf-8')
    print('BEAMNG_START', args.map, flush=True)
    proc = subprocess.Popen([str(args.exe), '-userpath', str(output/'user'), '-level', artifact['level_id'],
                             '-onLevelLoad_ext', 'earth2roadpromo', '-nosteam'], cwd=args.exe.parent)
    try:
        proc.wait(timeout=1500)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        raise
    result = read(profile/'earth2road-result.json')
    result['process_exit_code'] = proc.returncode
    result['map'] = args.map
    result['artifact_sha256'] = artifact['sha256']
    frames = list((profile/'screenshots/promo').glob('frame_*.jpg'))
    result['saved_frames'] = len(frames)
    (output/'result.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print('BEAMNG_DONE', args.map, result['status'], len(frames), flush=True)
    if result['status'] != 'complete' or len(frames) != 360 or proc.returncode:
        raise RuntimeError('Incomplete take; inspect result and engine log')


if __name__ == '__main__':
    main()
