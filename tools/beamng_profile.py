#!/usr/bin/env python3
"""Profile an exported BeamNG level: where triangles, vertices, bytes and scene objects go.

    .venv/Scripts/python.exe tools/beamng_profile.py out/livo-balanced [--area-km2 1] [--json out.json]

Reads the unpacked export (the folder with levels/<id>/, or the level folder itself).
Generated shapes are grouped by name prefix (kyiv_walk → sidewalks, …), then by material,
and split into flat (|nz| ≥ 0.5) and vertical faces, which separates curb/wall sides
from walking/driving surfaces. DAE bytes are split into position, normal, UV and index
text. Scene objects are counted by class and name prefix, plus DecalRoad nodes and
forest instances. Numbers describe the files, not BeamNG's memory or FPS.
"""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import re
import sys

import numpy as np

CATEGORY = {'kyiv_walk': 'sidewalks', 'kyiv_surface': 'surfaces', 'kyiv_ground': 'ground',
            'kyiv_paint': 'markings', 'kyiv_buildings': 'buildings', 'kyiv_signal_mast': 'props',
            'kyiv_signface': 'sign_assets', 'kyiv_signal_head': 'props', 'kyiv_canopy': 'props',
            'kyiv_rail': 'props'}
GEOMETRY = re.compile(r'<geometry id="([^"]+)"[^>]*><mesh>(.*?)</mesh></geometry>', re.S)
SOURCE = re.compile(r'<source id="[^"]+-(pos|normal|uv)"><float_array[^>]*count="(\d+)">(.*?)</float_array>', re.S)
TRIANGLES = re.compile(r'<triangles count="(\d+)" material="([^"]+)">.*?<p>(.*?)</p>', re.S)
NODE = re.compile(r'<node id="[^"]+" name="([^"]+)"><instance_geometry url="#([^"]+)"')


def category(name):
    for prefix in sorted(CATEGORY, key=len, reverse=True):
        if name.startswith(prefix):
            return CATEGORY[prefix]
    return 'other'


def level_dir(path):
    path = Path(path)
    if (path / 'main').is_dir():
        return path
    levels = sorted((path / 'levels').glob('*/main'))
    if len(levels) != 1:
        raise SystemExit(f'Expected one level under {path}/levels, found {len(levels)}')
    return levels[0].parent


def blank():
    return defaultdict(float)


def profile_dae(path, cat, materials, bytes_by_part):
    """Adds per-material numbers; returns this file's totals."""
    text = path.read_text(encoding='utf8')
    names = {gid: name for name, gid in NODE.findall(text)}
    total = blank()
    total['bytes'] = len(text.encode('utf8'))
    for gid, body in GEOMETRY.findall(text):
        collision = names.get(gid, '').startswith('Colmesh')
        sources = {kind: (int(count), data) for kind, count, data in SOURCE.findall(body)}
        for kind, (_, data) in sources.items():
            bytes_by_part[cat][('col_' if collision else '') + kind] += len(data)
        for count, mat, idx in TRIANGLES.findall(body):
            count = int(count)
            bytes_by_part[cat][('col_' if collision else '') + 'index'] += len(idx)
            key = 'collision_triangles' if collision else 'triangles'
            total[key] += count
            if collision:
                materials[cat][mat]['collision_triangles'] += count
                continue
            pos = np.array(sources['pos'][1].split(), dtype=np.float64).reshape(-1, 3)
            tri = np.array(idx.split(), dtype=np.int64).reshape(-1, 3)
            a, b, c = pos[tri[:, 0]], pos[tri[:, 1]], pos[tri[:, 2]]
            cross = np.cross(b - a, c - a)
            length = np.linalg.norm(cross, axis=1)
            area = length / 2
            nz = np.abs(cross[:, 2]) / np.where(length > 0, length, 1)
            vertical = nz < .5
            m = materials[cat][mat]
            m['triangles'] += count
            m['vertices'] += len(pos)
            m['vertical_triangles'] += int(vertical.sum())
            m['flat_area_m2'] += float(area[~vertical].sum())
            m['vertical_area_m2'] += float(area[vertical].sum())
            m['tiny_triangles'] += int((area < .01).sum())
            total['vertices'] += len(pos)
    return total


def scene(level):
    classes, prefixes = Counter(), Counter()
    road_nodes = 0
    collision_types = Counter()
    for items in (level / 'main').rglob('items.level.json'):
        for line in items.read_text(encoding='utf8').splitlines():
            if not line.strip():
                continue
            obj = json.loads(line)
            classes[obj.get('class')] += 1
            name = obj.get('name', '')
            prefixes[re.sub(r'_[0-9a-f]{8,}$', '', name)] += 1
            if obj.get('class') == 'DecalRoad':
                road_nodes += len(obj.get('nodes', []))
            if obj.get('class') == 'TSStatic':
                collision_types[obj.get('collisionType')] += 1
    forest = Counter()
    for f in (level / 'forest').glob('*.forest4.json'):
        forest[f.name.split('.')[0]] = sum(1 for line in f.open(encoding='utf8') if line.strip())
    return {'classes': dict(classes.most_common()), 'name_prefixes': dict(prefixes.most_common(25)),
            'decalroad_nodes': road_nodes, 'tsstatic_collision': dict(collision_types),
            'forest_instances': sum(forest.values()), 'forest_types': len(forest)}


def profile(path):
    level = level_dir(path)
    materials = defaultdict(lambda: defaultdict(blank))
    bytes_by_part = defaultdict(blank)
    categories = defaultdict(blank)
    heaviest = []
    for dae in sorted((level / 'art/shapes').glob('*.dae')):
        cat = category(dae.stem)
        total = profile_dae(dae, cat, materials, bytes_by_part)
        total['objects'] = 1
        for k, v in total.items():
            categories[cat][k] += v
        heaviest.append((total['bytes'], dae.name, cat, int(total['triangles']), int(total['vertices'])))
    heaviest.sort(reverse=True)
    files = sorted(p for p in level.rglob('*') if p.is_file())
    by_ext = Counter()
    for p in files:
        by_ext[p.suffix or p.name] += p.stat().st_size
    return {'level': level.name,
            'categories': {k: {kk: round(vv, 1) for kk, vv in v.items()} for k, v in sorted(categories.items())},
            'materials': {c: {m: {k: round(v, 1) for k, v in d.items()} for m, d in sorted(ms.items(), key=lambda x: -x[1]['triangles'])}
                          for c, ms in materials.items()},
            'dae_text_bytes': {k: {kk: int(vv) for kk, vv in v.items()} for k, v in bytes_by_part.items()},
            'bytes_by_extension': dict(by_ext.most_common()),
            'heaviest': [dict(bytes=b, file=n, category=c, triangles=t, vertices=v) for b, n, c, t, v in heaviest[:20]],
            'scene': scene(level)}


def table(result, area):
    cats = result['categories']
    total_bytes = sum(c['bytes'] for c in cats.values()) or 1
    lines = [f"level {result['level']}  (area {area} km²)", '',
             f"{'category':<12}{'objects':>8}{'tris':>11}{'verts':>11}{'v/t':>6}{'col tris':>11}{'MB':>9}{'%':>6}{'MB/km²':>9}"]
    for name, c in sorted(cats.items(), key=lambda x: -x[1]['bytes']):
        vt = c.get('vertices', 0) / c['triangles'] if c.get('triangles') else 0
        lines.append(f"{name:<12}{int(c['objects']):>8}{int(c.get('triangles', 0)):>11,}{int(c.get('vertices', 0)):>11,}{vt:>6.2f}"
                     f"{int(c.get('collision_triangles', 0)):>11,}{c['bytes']/1e6:>9.1f}{100*c['bytes']/total_bytes:>6.1f}{c['bytes']/1e6/area:>9.1f}")
    lines += ['', 'materials (visual triangles; vertical = |nz| < 0.5):']
    for cat, mats in result['materials'].items():
        for mat, m in list(mats.items())[:6]:
            if not m.get('triangles'):
                continue
            lines.append(f"  {cat:<11}{mat:<34}{int(m['triangles']):>10,} tris  vertical {100*m.get('vertical_triangles', 0)/m['triangles']:>5.1f}%"
                         f"  flat {m.get('flat_area_m2', 0):>10,.0f} m²  vert {m.get('vertical_area_m2', 0):>8,.0f} m²  tiny {int(m.get('tiny_triangles', 0)):>7,}")
    lines += ['', 'DAE text bytes by attribute (MB):']
    for cat, parts in result['dae_text_bytes'].items():
        lines.append(f"  {cat:<11}" + '  '.join(f"{k} {v/1e6:.1f}" for k, v in sorted(parts.items())))
    s = result['scene']
    lines += ['', f"scene: {s['classes']}", f"  DecalRoad nodes {s['decalroad_nodes']:,}; forest {s['forest_instances']:,} instances / {s['forest_types']} types",
              f"  TSStatic collision {s['tsstatic_collision']}", f"  top names {s['name_prefixes']}"]
    lines += ['', 'files by extension (MB): ' + ', '.join(f"{k} {v/1e6:.1f}" for k, v in result['bytes_by_extension'].items())]
    return '\n'.join(lines)


def main(argv=None):
    sys.stdout.reconfigure(encoding='utf-8')
    p = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    p.add_argument('export', type=Path)
    p.add_argument('--area-km2', type=float, default=1.0)
    p.add_argument('--json', type=Path)
    args = p.parse_args(argv)
    result = profile(args.export)
    result['area_km2'] = args.area_km2
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding='utf8')
    print(table(result, args.area_km2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
