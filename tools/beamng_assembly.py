"""Presentation-only BeamNG assembly capture. Never edits the source export or user profile.

prepare copies an existing export into a fresh isolated profile and partitions its
indexed COLLADA triangles, preserving original positions, normals and UV strings.
The 8 m cells group triangles by centroid; long triangles are deliberately not cut.
capture launches only that profile; encode creates a captioned silent MP4.
"""
import argparse
from collections import defaultdict
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
NS = 'http://www.collada.org/2005/11/COLLADASchema'
ET.register_namespace('', NS)
Q = lambda s: '{' + NS + '}' + s


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def partition_dae(path, classify):
    """Return documents by classifier key, preserving every indexed corner exactly.

Only accepts the single-index triangle format emitted by our exporter. Fail closed
on a different format instead of silently corrupting an arbitrary user mesh.
"""
    root = ET.parse(path).getroot()
    geometries = root.find(Q('library_geometries'))
    selections = defaultdict(dict)
    total = 0
    for geo in geometries:
        mesh = geo.find(Q('mesh'))
        triangles = mesh.find(Q('triangles'))
        if triangles is None or len(mesh.findall(Q('triangles'))) != 1:
            raise ValueError('Expected one triangle list per geometry')
        if any(int(i.get('offset', '0')) != 0 for i in triangles.findall(Q('input'))):
            raise ValueError('Expected shared vertex/normal/UV indices')
        sources = {s.get('id'): s for s in mesh.findall(Q('source'))}
        pos_id = mesh.find(Q('vertices')).find(Q('input')).get('source')[1:]
        pos = list(map(float, sources[pos_id].find(Q('float_array')).text.split()))
        indices = list(map(int, triangles.find(Q('p')).text.split()))
        if len(indices) != int(triangles.get('count')) * 3:
            raise ValueError('Invalid triangle count')
        material = triangles.get('material')
        buckets = defaultdict(list)
        for i in range(0, len(indices), 3):
            tri = indices[i:i+3]
            center = [sum(pos[v*3+k] for v in tri)/3 for k in range(3)]
            buckets[classify(material, center)].extend(tri)
        for key, ids in buckets.items():
            selections[key][geo.get('id')] = ids
        total += len(indices)//3
    outputs = {}
    for key, chosen in selections.items():
        doc = deepcopy(root)
        lib = doc.find(Q('library_geometries'))
        for geo in list(lib):
            if geo.get('id') not in chosen:
                lib.remove(geo)
                continue
            indices = chosen[geo.get('id')]
            used = sorted(set(indices))
            remap = {old: new for new, old in enumerate(used)}
            mesh = geo.find(Q('mesh'))
            for source in mesh.findall(Q('source')):
                accessor = source.find(Q('technique_common')).find(Q('accessor'))
                stride = int(accessor.get('stride'))
                array = source.find(Q('float_array'))
                values = array.text.split()
                kept = [v for i in used for v in values[i*stride:(i+1)*stride]]
                if len(kept) != len(used)*stride:
                    raise ValueError('Source array and triangle indices disagree')
                array.text = ' '.join(kept)
                array.set('count', str(len(kept)))
                accessor.set('count', str(len(used)))
            triangles = mesh.find(Q('triangles'))
            triangles.set('count', str(len(indices)//3))
            triangles.find(Q('p')).text = ' '.join(str(remap[i]) for i in indices)
        for parent in doc.iter(Q('node')):
            for child in list(parent):
                inst = child.find(Q('instance_geometry'))
                if inst is not None and inst.get('url')[1:] not in chosen:
                    parent.remove(child)
        outputs[key] = ET.tostring(doc, encoding='utf-8', xml_declaration=True)
    assert sum(len(ids)//3 for c in selections.values() for ids in c.values()) == total
    return outputs, total


def prepare(args):
    from shapely.geometry import MultiPoint, Point, Polygon
    out = args.output.resolve()
    if out.exists():
        raise FileExistsError('Choose a fresh output directory')
    source = args.export.resolve()
    artifact = read(source/'artifact.json')
    if hashlib.sha256((source/artifact['zip']).read_bytes()).hexdigest() != artifact['sha256']:
        raise ValueError('Export ZIP hash differs from artifact.json')
    scene = read(args.scene)
    world = args.world.resolve()
    idx = read(world/'index.json')
    level_id = artifact['level_id']
    # This is a visual replay of this exact world, not a re-export of today's code.
    if not args.static:
        report = read(world/'roadgen_report.json')
        if report != read(source/'reports/roadgen_report.json'):
            raise ValueError('World and export roadgen reports differ')
        junction = next(j for j in report['junctions'] if j['id'] == scene['junction'])
        if junction['status'] != 'v2':
            raise ValueError('Selected junction does not use v2 geometry')
        ox, oy = idx['offset']
        core = MultiPoint([(p[0]-ox, p[1]-oy) for s in junction['sockets'] for p in s['inner']]).convex_hull
        transitions = [Polygon([(p[0]-ox, p[1]-oy) for p in s['inner']+list(reversed(s['outer']))]) for s in junction['sockets']]
    profile = out/'user/current'
    mod = profile/'mods/unpacked/earth2road_assembly'
    shutil.copytree(source/'mod', mod)
    level = mod/'levels'/level_id
    cx, cy, cz = scene['center']
    radius = scene['radius']
    animated, audit = [], {'input_triangles': 0, 'partitioned_objects': 0, 'parts': 0}
    for items in sorted(level.glob('main/**/items.level.json')):
        objects = [json.loads(line) for line in items.read_text(encoding='utf-8').splitlines() if line.strip()]
        result = []
        for obj in objects:
            name = obj.get('name', '')
            position = obj.get('position', [0, 0, 0])
            split = not args.static and obj.get('class') == 'TSStatic' and any(k in name for k in ('__kyiv_surface_', '__kyiv_walk_', '__kyiv_paint_'))
            if split:
                if obj.get('rotationMatrix') != [1, 0, 0, 0, 1, 0, 0, 0, 1] or obj.get('scale') != [1, 1, 1]:
                    raise ValueError('Capture partition expects unrotated, unit-scale export chunks')
                dae = mod/obj['shapeName'].lstrip('/')
                def classify(mat, p):
                    x, y = p[0]+position[0], p[1]+position[1]
                    if math.hypot(x-cx, y-cy) > radius:
                        return ('static', 0, 0)
                    if 'paint' in mat:
                        stage = 'marks'
                    elif any(v in mat for v in ('concrete', 'curb')):
                        stage = 'walks'
                    elif 'asphalt' in mat:
                        point = Point(x, y)
                        if core.covers(point):
                            return ('core', 0, 0)
                        stage = 'transitions' if any(p.covers(point) for p in transitions) else 'roads'
                    else:
                        return ('static', 0, 0)
                    return (stage, math.floor(x/8), math.floor(y/8))
                parts, count = partition_dae(dae, classify)
                if set(parts) == {('static', 0, 0)}:
                    result.append(obj)
                    continue
                audit['input_triangles'] += count
                audit['partitioned_objects'] += 1
                for n, (key, data) in enumerate(sorted(parts.items())):
                    replacement = deepcopy(obj)
                    replacement.pop('persistentId', None)
                    replacement['name'] = name + f'_assembly_{n}'
                    relative = f'art/shapes/assembly/{replacement["name"]}.dae'
                    target = level/relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(data)
                    replacement['shapeName'] = f'/levels/{level_id}/{relative}'
                    replacement['collisionType'] = 'None'
                    result.append(replacement)
                    audit['parts'] += 1
                    if key[0] != 'static':
                        center = [cx, cy] if key[0] == 'core' else [(key[1]+.5)*8, (key[2]+.5)*8]
                        animated.append({'name': replacement['name'], 'stage': key[0], 'position': position, 'center': center})
            else:
                result.append(obj)
                if not args.static and obj.get('class') == 'TSStatic' and math.hypot(position[0]-cx, position[1]-cy) < radius+150:
                    stage = 'buildings' if '__kyiv_buildings_' in name else 'props'
                    animated.append({'name': name, 'stage': stage, 'position': position, 'center': position[:2]})
        items.write_text('\n'.join(json.dumps(o) for o in result)+ ('\n' if result else ''), encoding='utf-8')
    ext = mod/'lua/ge/extensions'
    ext.mkdir(parents=True)
    shutil.copy2(ROOT/'tools/beamng_assembly.lua', ext/'earth2roadassembly.lua')
    cfg = {**scene, 'level': level_id, 'parts': animated, 'fps': 30, 'frames': 750}
    write(profile/'earth2road-assembly.json', cfg)
    (profile/'settings').mkdir(parents=True)
    write(profile/'settings/settings.json', {'GraphicDisplayResolutions': '1920 1080', 'GraphicFullscreen': False,
          'GraphicOverallQuality': 'Normal', 'AudioMasterVol': 0, 'fpsLimitBackgroundEnabled': False,
          'PostFXMotionBlurEnabled': False})
    audit.update(source_export=str(source), source_world=str(world), artifact_sha256=artifact['sha256'],
                 junction=scene.get('junction'), animated=len(animated), scene=scene,
                 note='Presentation only. Exact original indexed corners; cells group triangle centroids, not physical construction units.')
    write(out/'preparation.json', audit)
    print(json.dumps(audit, ensure_ascii=False), flush=True)


def capture(args):
    out = args.output.resolve()
    profile = out/'user/current'
    cfg = read(profile/'earth2road-assembly.json')
    if not 1 <= args.frames <= 750:
        raise ValueError('frames must be between 1 and 750')
    if args.sample_times and any(not math.isfinite(t) or not 0 <= t <= 25 for t in args.sample_times):
        raise ValueError('sample times must be finite seconds from 0 to 25')
    if (profile/'screenshots/assembly').exists():
        raise FileExistsError('Capture already exists; prepare a fresh take')
    cfg['frames'] = args.frames
    cfg['sample_times'] = args.sample_times
    write(profile/'earth2road-assembly.json', cfg)
    exe = args.exe.resolve()
    # Windows startup flags keep the helper hidden; only this owned process is terminated.
    startup = subprocess.STARTUPINFO() if sys.platform == 'win32' else None
    if startup:
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = 0
    process = subprocess.Popen([str(exe), '-userpath', str(out/'user'), '-level', cfg['level'],
                               '-onLevelLoad_ext', 'earth2roadassembly', '-nosteam'], cwd=exe.parent, startupinfo=startup)
    print('BEAMNG_PID', process.pid, flush=True)
    try:
        process.wait(timeout=1800)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
        raise
    result = read(profile/'earth2road-assembly-result.json')
    result['exit_code'] = process.returncode
    result['saved_frames'] = len(list((profile/'screenshots/assembly').glob('frame_*.jpg')))
    write(out/'result.json', result)
    print(json.dumps(result), flush=True)
    expected = len(args.sample_times) if args.sample_times else args.frames
    if process.returncode or result.get('status') != 'complete' or result['saved_frames'] != expected:
        raise RuntimeError('Incomplete capture; see result and isolated engine log')


def encode(args):
    import imageio_ffmpeg
    from PIL import Image, ImageDraw, ImageFont
    out = args.output.resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        raise FileExistsError(out)
    missing = [n for n in range(750) if not (args.input/f'frame_{n:04d}.jpg').is_file()]
    if missing:
        raise ValueError(f'Incomplete 750-frame take; first missing frame: {missing[0]}')
    font = lambda size: ImageFont.truetype('C:/Windows/Fonts/segoeui.ttf', size)
    stages = [('roads', 0, 6, 'Вулиця з маленьких елементів' if args.kind == 'street' else 'Як збирається перехрестя'),
              ('approach', 6, 10, 'Дорожні смуги стають на місце'),
              ('core', 10, 15, 'Під’їзди → переходи → ядро перехрестя'),
              ('walks', 15, 19, 'Бордюри, тротуари та розмітка'),
              ('finish', 19, 25, 'Готова вулиця · Біличі, Київ')]
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    command = [ffmpeg, '-v', 'error', '-framerate', '30', '-i', str(args.input/'frame_%04d.jpg')]
    labels = []
    for name, a, b, title in stages:
        png = out.parent/f'{args.kind}-{name}.png'
        overlay = Image.new('RGBA', (1920, 1080))
        d = ImageDraw.Draw(overlay)
        d.rounded_rectangle((38, 30, 450, 92), radius=12, fill=(11, 21, 29, 220))
        d.text((58, 39), 'Earth2Road  /  BeamNG.drive', font=font(27), fill='#e0f3ea')
        d.rectangle((0, 915, 1920, 1080), fill=(11, 21, 29, 218))
        d.rectangle((54, 940, 60, 1021), fill='#78ebbf')
        d.text((82, 932), title, font=font(40), fill='white')
        d.text((84, 990), 'Візуалізація складання згенерованої карти; не час генерації.', font=font(25), fill='#d2dfe0')
        d.text((84, 1041), '© OpenStreetMap contributors · ODbL  |  Terrain: Mapzen  |  Прототип, 06.10.2026', font=font(18), fill='#afc1c3')
        overlay.save(png)
        command += ['-i', str(png)]
        labels.append((a, b))
    filters = []
    previous = '0:v'
    for i, (a, b) in enumerate(labels, 1):
        filters.append(f'[{previous}][{i}:v]overlay=enable=\'gte(t,{a})*lt(t,{b})\'[v{i}]')
        previous = f'v{i}'
    command += ['-filter_complex', ';'.join(filters), '-map', f'[{previous}]', '-an', '-t', '25',
                '-c:v', 'libx264', '-preset', 'medium', '-crf', '19', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', str(out)]
    subprocess.run(command, check=True)
    print(out)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='command', required=True)
    prep = sub.add_parser('prepare')
    for flag in ('world', 'export', 'scene', 'output'):
        prep.add_argument('--'+flag, type=Path, required=True)
    prep.add_argument('--static', action='store_true', help='Unmodified export for control screenshots')
    cap = sub.add_parser('capture')
    cap.add_argument('--output', type=Path, required=True)
    cap.add_argument('--frames', type=int, default=750)
    cap.add_argument('--sample-times', type=float, nargs='+')
    cap.add_argument('--exe', type=Path, default=Path(r'C:\Program Files (x86)\Steam\steamapps\common\BeamNG.drive\Bin64\BeamNG.drive.x64.exe'))
    enc = sub.add_parser('encode')
    enc.add_argument('--input', type=Path, required=True)
    enc.add_argument('--output', type=Path, required=True)
    enc.add_argument('--kind', choices=('junction', 'street'), required=True)
    args = p.parse_args()
    {'prepare': prepare, 'capture': capture, 'encode': encode}[args.command](args)


if __name__ == '__main__':
    main()
