#!/usr/bin/env python3
"""Generate adjacent v2 windows in both orders, compare with a monolithic world.

The MIT fixture has straight roads, junctions, an analytic sloping DEM and a
bridge over another road. Nothing in this lab is observed OSM or surveyed terrain.
"""
import argparse
import copy
import json
import math
from pathlib import Path
import shutil
import sys
import time
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from akadem_maps.context import read_json, sha256, write_json
from akadem_maps.streaming_probe import compare_surfaces
from akadem_maps.world import build_world


def inputs_at(output):
    from PIL import Image
    target = output / 'inputs'
    shutil.copytree(ROOT / 'examples/tiny/inputs', target)
    source = target / 'raw/tiny.osm'
    osm = ET.parse(source).getroot()
    # Replace central north-south road by separate approaches and a raised deck.
    osm.remove(next(w for w in osm.findall('way') if w.get('id') == '105'))
    for nid, lat in [('20', 50.452), ('21', 50.456)]:
        ET.SubElement(osm, 'node', id=nid, lon='30.356', lat=str(lat))
    for wid, a, b, bridge in [('301', '2', '20', False), ('302', '20', '21', True), ('303', '21', '8', False)]:
        way = ET.SubElement(osm, 'way', id=wid)
        for node in (a, b):
            ET.SubElement(way, 'nd', ref=node)
        for k, v in [('highway', 'residential'), ('lanes', '2'), ('maxspeed', '30')]:
            ET.SubElement(way, 'tag', k=k, v=v)
        if bridge:
            ET.SubElement(way, 'tag', k='bridge', v='yes')
            ET.SubElement(way, 'tag', k='layer', v='1')
    ET.ElementTree(osm).write(source, encoding='utf8')
    for path in (target / 'raw/terrain').rglob('*.png'):
        zoom, tx, ty = int(path.parts[-3]), int(path.parts[-2]), int(path.stem)
        image = Image.new('RGB', (256, 256))
        pixels = []
        for y in range(256):
            lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (ty + y / 255) / 2**zoom))))
            for x in range(256):
                lon = (tx + x / 255) / 2**zoom * 360 - 180
                height = 100 + (lon - 30.356) * 2000 + (lat - 50.454) * 1200
                value = round((height + 32768) * 256)
                pixels.append((value >> 16, (value >> 8) & 255, value & 255))
        image.putdata(pixels)
        image.save(path)
    write_json(target / 'manifest.json', {'files': {p.relative_to(target).as_posix(): sha256(p)
               for p in target.rglob('*') if p.is_file() and p.name != 'manifest.json'},
               'license': 'MIT', 'provenance': 'Synthetic roads, bridge and analytic DEM'})
    return target


def run(output):
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    inputs = inputs_at(output)
    base = read_json(ROOT / 'examples/tiny/config.json')
    base.update(road_geometry={'mode': 'v2'}, osm_file='tiny.osm')
    specs = {'whole': ([30.348, 50.448, 30.364, 50.46], [30.356, 50.454]),
             'west': ([30.348, 50.448, 30.358, 50.46], [30.353, 50.454]),
             'east': ([30.354, 50.448, 30.364, 50.46], [30.359, 50.454])}
    builds = {}
    for label, name in [('whole', 'whole'), ('west_first', 'west'), ('east_second', 'east'),
                        ('east_first', 'east'), ('west_second', 'west')]:
        cfg = copy.deepcopy(base)
        # Same id/config across orders: only output location changes.
        cfg.update(id=name, name='Synthetic streaming ' + name, bbox=specs[name][0], center=specs[name][1])
        start = time.perf_counter()
        print(label + ': building', flush=True)
        build_world(cfg, output / label, inputs=inputs, offline=True)
        builds[label] = {'elapsed_s': time.perf_counter() - start}
        write_json(output / 'progress.json', builds)
    band = [30.3545, 50.449, 30.3575, 50.459]
    comparisons = {}
    for name in ('west', 'east'):
        first, second = output / (name + '_first'), output / (name + '_second')
        hashes = lambda root: {p.relative_to(root).as_posix(): sha256(p)
                               for p in [root / 'index.json', root / 'network.net.xml', *sorted((root / 'tiles').glob('*.json'))]}
        a, b = hashes(first), hashes(second)
        comparisons[name + '_order'] = {'passed': a == b, 'files_compared': len(a),
            'differing_files': [k for k in sorted(set(a) | set(b)) if a.get(k) != b.get(k)]}
        comparisons[name + '_whole'] = compare_surfaces(output / 'whole', first, bbox=band, step=4.)
    comparisons['west_east_overlap'] = compare_surfaces(output / 'west_first', output / 'east_first', bbox=band, step=4.)
    result = {'synthetic': True, 'builds': builds, 'comparisons': comparisons,
              'passed': all(r['passed'] for r in comparisons.values()), 'runtime_verified': False}
    write_json(output / 'report.json', result)
    print(json.dumps({k: {f: v for f, v in r.items() if f != 'examples'} for k, r in comparisons.items()}, indent=2))
    return result['passed']


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    raise SystemExit(0 if run(parser.parse_args().output) else 1)
