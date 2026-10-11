"""Write a Godot --shots-file from lon/lat camera poses for an installed or built world.

    python tools/shots_file.py WORLD_DIR POSES.json OUT.json

POSES.json: {"shots": [{"name", "lon", "lat", "heading", "height", "pitch"}]}; heading is
clockwise from north, height is metres above the nearest lane point. The world needs
network.net.xml (its SUMO projection) and index.json.
"""
import json
import math
import sys
from pathlib import Path


def main():
    import sumolib
    world, poses, out = (Path(a) for a in sys.argv[1:4])
    index = json.loads((world/'index.json').read_text(encoding='utf-8'))
    net = sumolib.net.readNet(str(world/'network.net.xml'))
    cx, cy = index['offset']
    lanes = [p for lane in index['lanes'] for p in lane['points']]
    shots = []
    for pose in json.loads(poses.read_text(encoding='utf-8'))['shots']:
        x, y = net.convertLonLat2XY(pose['lon'], pose['lat'])
        gx, gz = x-cx, -(y-cy)
        ground = min(lanes, key=lambda p: (p[0]-gx)**2+(p[2]-gz)**2)[1] if lanes else 0.0
        shots.append({'name': pose['name'], 'position': [round(gx, 2), round(ground, 2), round(gz, 2)],
                      'heading': pose['heading'], 'height': pose['height'], 'pitch': pose['pitch']})
    out.write_text(json.dumps({'shots': shots}, ensure_ascii=False, indent=1), encoding='utf-8')
    print(f'{len(shots)} shots -> {out}')


if __name__ == '__main__':
    main()
