#!/usr/bin/env python3
"""Load-time / memory / FPS benchmark and side-by-side screenshots of BeamNG export variants.

    .venv/Scripts/python.exe tools/beamng_bench.py out/livo-variants/livo_*.zip --map kyiv_livoberezhna_1km --out out/bench/livo

Each ZIP gets its own isolated user directory under --out (never the normal BeamNG profile),
with only that ZIP and the bench extension (tools/beamng_bench.lua) mounted. Every variant is
launched twice: 'cold' (fresh profile: the game converts every .dae to its .cdae cache) and
'warm' (same profile, cache present). Load time is wall clock from process start until the
extension reports the level ready, so it includes the constant game start-up. Memory is the
game process's private bytes / working set, sampled every 0.5 s. Views are the same free-camera
points for every variant (spawn, junction, street, kerb, low and high overview), from the map's
snapshot. Output: results.json, results.md and one comparison sheet per view.
"""
import argparse
import ctypes
from ctypes import wintypes
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
EXE = Path(r'C:\Program Files (x86)\Steam\steamapps\common\BeamNG.drive\Bin64\BeamNG.drive.x64.exe')


class _Memory(ctypes.Structure):
    _fields_ = [('cb', wintypes.DWORD), ('PageFaultCount', wintypes.DWORD),
                ('PeakWorkingSetSize', ctypes.c_size_t), ('WorkingSetSize', ctypes.c_size_t),
                ('QuotaPeakPagedPoolUsage', ctypes.c_size_t), ('QuotaPagedPoolUsage', ctypes.c_size_t),
                ('QuotaPeakNonPagedPoolUsage', ctypes.c_size_t), ('QuotaNonPagedPoolUsage', ctypes.c_size_t),
                ('PagefileUsage', ctypes.c_size_t), ('PeakPagefileUsage', ctypes.c_size_t),
                ('PrivateUsage', ctypes.c_size_t)]


def memory(pid):
    """(private bytes, working set) of a running process, or None."""
    handle = ctypes.windll.kernel32.OpenProcess(0x1000 | 0x0010, False, pid)
    if not handle:
        return None
    try:
        info = _Memory()
        info.cb = ctypes.sizeof(info)
        if not ctypes.windll.psapi.GetProcessMemoryInfo(handle, ctypes.byref(info), info.cb):
            return None
        return info.PrivateUsage, info.WorkingSetSize
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)


def views(map_id):
    """Shared camera points: the QA views plus a kerb close-up and a low overview."""
    from prepare_beamng_qa import views as qa_views
    from beamng_geometry import beam_point
    data = ROOT / 'game/data' / map_id
    index = json.loads((data / 'index.json').read_text(encoding='utf8'))
    result = qa_views(index, {'bounds': _bounds(index)})
    # Kerb: the at-grade sidewalk station nearest the widest lane's middle; the camera stands on
    # the road side 2.5 m off the kerb at eye height and looks 12 m along it.
    widest = max(index['lanes'], key=lambda v: (v['width'], len(v['points'])))
    lane = [beam_point(p) for p in widest['points']]
    road = lane[len(lane)//2]
    best = None
    for tile in sorted((data / 'tiles').glob('*.json')):
        for walk in json.loads(tile.read_text(encoding='utf8')).get('sidewalks', []):
            pts = [beam_point(p) for p in walk['points']]
            for k in range(len(pts)-1):
                gap = math.dist(pts[k][:2], road[:2])
                if abs(pts[k][2]-road[2]) < .5 and (best is None or gap < best[0]):
                    best = (gap, pts[k], pts[k+1])
    if best:
        _, s, t = best
        along = (t[0]-s[0], t[1]-s[1])
        n = math.hypot(*along) or 1
        along = (along[0]/n, along[1]/n)
        side = (road[0]-s[0], road[1]-s[1])
        n = math.hypot(*side) or 1
        side = (side[0]/n, side[1]/n)
        result.insert(3, {'name': 'kerb', 'pos': [s[0]+side[0]*2.5, s[1]+side[1]*2.5, s[2]+1.2],
                          'look': [s[0]+along[0]*12, s[1]+along[1]*12, s[2]]})
    # Low overview above the tallest buildings (~85 m), oblique over the spawn.
    spawn = beam_point(index['spawn']['position'])
    result.insert(4, {'name': 'low_overview', 'pos': [spawn[0]-220, spawn[1]-260, spawn[2]+160],
                      'look': [spawn[0]+60, spawn[1]+60, spawn[2]]})
    return result


def _bounds(index):
    from beamng_geometry import beam_point
    pts = [beam_point(p) for lane in index['lanes'] for p in lane['points']]
    return [min(p[0] for p in pts), min(p[1] for p in pts), max(p[0] for p in pts), max(p[1] for p in pts)]


def stage(zip_path, user, cam, args):
    with zipfile.ZipFile(zip_path) as z:
        level = sorted({n.split('/')[1] for n in z.namelist() if n.startswith('levels/')})[0]
    profile = user / 'current'
    (profile / 'mods/unpacked/kyiv_bench/lua/ge/extensions').mkdir(parents=True)
    shutil.copy2(zip_path, profile / 'mods' / zip_path.name)
    shutil.copy2(ROOT / 'tools/beamng_bench.lua', profile / 'mods/unpacked/kyiv_bench/lua/ge/extensions/kyivbench.lua')
    (profile / 'kyiv-bench-input.json').write_text(json.dumps({
        'level': level, 'views': cam, 'timeout': args.timeout, 'settleSeconds': args.settle,
        'streamSeconds': args.stream, 'measureSeconds': args.measure}), encoding='utf8')
    (profile / 'settings').mkdir()
    (profile / 'settings/settings.json').write_text(json.dumps({
        'GraphicDisplayResolutions': args.resolution, 'GraphicFullscreen': False,
        'GraphicOverallQuality': args.quality, 'AudioMasterVol': 0,
        'fpsLimitBackgroundEnabled': False, 'PostFXMotionBlurEnabled': False}), encoding='utf8')
    return level


def run(user, level, label, timeout):
    profile = user / 'current'
    result_path = profile / 'kyiv-bench-result.json'
    result_path.unlink(missing_ok=True)
    shots = profile / 'screenshots'
    if shots.exists():
        shutil.rmtree(shots)
    cmd = [str(EXE), '-userpath', str(user), '-level', level, '-onLevelLoad_ext', 'kyivbench', '-nosteam']
    started = time.perf_counter()
    proc = subprocess.Popen(cmd, cwd=str(EXE.parent))
    load_s = None
    samples = []
    status = None
    while proc.poll() is None:
        now = time.perf_counter()-started
        m = memory(proc.pid)
        if m:
            samples.append((round(now, 2), m[0], m[1]))
        if load_s is None and result_path.exists():
            try:
                status = json.loads(result_path.read_text(encoding='utf8')).get('status')
            except (json.JSONDecodeError, OSError):
                status = None
            if status in ('level_loaded', 'complete'):
                load_s = now
        if now > timeout:
            proc.kill()
            break
        time.sleep(.5)
    total = time.perf_counter()-started
    result = json.loads(result_path.read_text(encoding='utf8')) if result_path.exists() else {'status': 'no_result'}
    at_load = next((s for s in samples if load_s is not None and s[0] >= load_s), samples[-1] if samples else None)
    out = user.parent / label
    out.mkdir(parents=True, exist_ok=True)
    for png in sorted(profile.rglob('bench-*.png')):
        shutil.copy2(png, out / png.name)
    log = profile / 'beamng.log'
    if log.exists():
        shutil.copy2(log, out / 'beamng.log')
    return {**log_metrics(out / 'beamng.log'),
            'status': result.get('status'), 'exit_code': proc.returncode, 'load_seconds': load_s and round(load_s, 1),
            'total_seconds': round(total, 1),
            'private_mb_at_load': at_load and round(at_load[1]/2**20), 'working_set_mb_at_load': at_load and round(at_load[2]/2**20),
            'peak_private_mb': samples and round(max(s[1] for s in samples)/2**20),
            'peak_working_set_mb': samples and round(max(s[2] for s in samples)/2**20),
            'objects': result.get('objects'), 'counts': result.get('counts'), 'views': result.get('views', {}),
            'screenshots': str(out)}


def log_metrics(path):
    """The game's own level-load breakdown and static collision size from beamng.log."""
    text = Path(path).read_text(encoding='utf8', errors='replace') if Path(path).exists() else ''
    out = {}
    m = re.search(r'Level loaded in ([\d.]+)s: (.*)', text)
    if m:
        out['level_load_s'] = float(m.group(1))
        out['load_parts_s'] = {k: float(v) for k, v in re.findall(r'([\w.]+) ([\d.]+)s', m.group(2))}
    m = re.search(r'Physics collision reloaded in [\d.]+s \((\d+) instances generated in [\d.]+s, using ([\d.]+)mb\)', text)
    if m:
        out['collision_instances'], out['collision_mb'] = int(m.group(1)), float(m.group(2))
    out['collada_imports'] = text.count('Importing COLLADA')
    return out


def sheets(results, cam, out):
    from PIL import Image, ImageDraw, ImageFont
    names = list(results)
    try:
        font = ImageFont.truetype('arial.ttf', 26)
    except OSError:
        font = ImageFont.load_default()
    made = []
    for v in cam:
        tiles = []
        for name in names:
            runs = [results[name][k] for k in ('warm', 'cold') if k in results[name]]
            shot = next((Path(r['screenshots']) / f"bench-{v['name']}.png" for r in runs
                         if (Path(r['screenshots']) / f"bench-{v['name']}.png").exists()), None)
            tiles.append((name, Image.open(shot).convert('RGB') if shot else None))
        w, h = 960, 540
        cols = 2 if len(tiles) > 2 else len(tiles)
        rows = math.ceil(len(tiles)/cols)
        sheet = Image.new('RGB', (cols*w, rows*h), (30, 30, 30))
        draw = ImageDraw.Draw(sheet)
        for k, (name, img) in enumerate(tiles):
            x, y = (k % cols)*w, (k//cols)*h
            if img:
                sheet.paste(img.resize((w, h)), (x, y))
            # Best FPS over the runs: outside load (other GPU work) only ever lowers it.
            fps = max((r['views'].get(v['name'], {}).get('fps', 0) for r in results[name].values()), default=0)
            label = f"{name}  best {fps:.0f} fps" if fps else f'{name}  (no shot)'
            draw.rectangle([x, y, x+12+draw.textlength(label, font=font)+12, y+40], fill=(0, 0, 0))
            draw.text((x+12, y+6), label, fill=(255, 255, 255), font=font)
        path = out / f"compare-{v['name']}.jpg"
        sheet.save(path, quality=88)
        made.append(path)
    return made


def report(results, cam, out):
    lines = ['| variant | level load cold s (objects) | level load warm s (objects) | DAE imports cold | '
             'start-to-ready warm s | private MB at load | peak private MB | collision MB | '
             + ' | '.join(f"{v['name']} fps" for v in cam) + ' |',
             '|' + '---|'*(8+len(cam))]
    for name, r in results.items():
        c = r.get('cold') or r.get('warm')
        w = r.get('warm') or c
        for run in (c, w):
            run.update({k: v for k, v in log_metrics(Path(run['screenshots']) / 'beamng.log').items() if k not in run})
        part = lambda run: f"{run.get('level_load_s')} ({run.get('load_parts_s', {}).get('objects')})"
        lines.append(f"| {name} | {part(c)} | {part(w)} | {c.get('collada_imports')} | {w['load_seconds']} | "
                     f"{w['private_mb_at_load']} | {max(c['peak_private_mb'] or 0, w['peak_private_mb'] or 0)} | "
                     f"{w.get('collision_mb')} | "
                     + ' | '.join(f"{w['views'].get(v['name'], {}).get('fps', 0):.0f}" for v in cam) + ' |')
    (out / 'results.md').write_text('\n'.join(lines)+'\n', encoding='utf8')
    return '\n'.join(lines)


def main():
    p = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    p.add_argument('zips', type=Path, nargs='+')
    p.add_argument('--map', required=True, help='installed map id with the same snapshot (camera points)')
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--resolution', default='1920 1080')
    p.add_argument('--quality', default='Normal')
    p.add_argument('--settle', type=float, default=8)
    p.add_argument('--stream', type=float, default=4)
    p.add_argument('--measure', type=float, default=4)
    p.add_argument('--timeout', type=float, default=1200)
    p.add_argument('--runs', default='cold,warm')
    p.add_argument('--report-only', action='store_true', help='rebuild results.md and sheets from --out/results.json')
    args = p.parse_args()
    if args.report_only:
        data = json.loads((args.out / 'results.json').read_text(encoding='utf8'))
        print(report(data['results'], data['views'], args.out))
        for path in sheets(data['results'], data['views'], args.out):
            print(path)
        return
    if ' ' in str(args.out.resolve()):
        raise SystemExit('Use an output path without spaces (BeamNG -userpath limitation)')
    if args.out.exists():
        raise SystemExit(f'{args.out} exists; use a fresh folder')
    cam = views(args.map)
    args.out.mkdir(parents=True)
    results = {}
    for zip_path in args.zips:
        name = zip_path.stem
        user = (args.out / name / 'profile').resolve()
        level = stage(zip_path, user, cam, args)
        results[name] = {}
        for label in args.runs.split(','):
            print(f'{name} {label} ...', flush=True)
            r = run(user, level, label, args.timeout)
            results[name][label] = r
            print(f"  {r['status']} load {r['load_seconds']} s, total {r['total_seconds']} s, "
                  f"private {r['private_mb_at_load']} MB at load, peak {r['peak_private_mb']} MB", flush=True)
            (args.out / 'results.json').write_text(json.dumps({'views': cam, 'results': results}, indent=2), encoding='utf8')
    print(report(results, cam, args.out))
    for path in sheets(results, cam, args.out):
        print(path)


if __name__ == '__main__':
    main()
