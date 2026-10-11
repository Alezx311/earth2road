"""Resolve playtest defect notes (F9 in the game) against the map's SUMO network.

Reads logs/defects/<map>/defects.jsonl and prints, per note, lon/lat of the marked point
and the nearest edges and junction, so a defect can be traced back to the generator.
Writes the same as defects.resolved.json next to the input.

    python tools/defects.py [--map ID] [--radius 25]
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import paths


def resolve(net, record, radius):
    point = record.get('target') or record.get('car') or record['camera']
    x, y = point['sumo_xy']
    lon, lat = net.convertXY2LonLat(x, y)
    edges = sorted(net.getNeighboringEdges(x, y, radius, includeJunctions=False), key=lambda e: e[1])
    nodes = sorted(((n, ((n.getCoord()[0] - x) ** 2 + (n.getCoord()[1] - y) ** 2) ** 0.5) for n in net.getNodes()),
                   key=lambda n: n[1])
    out = {
        'n': record['n'], 'note': record.get('note', ''), 'screenshot': record['screenshot'],
        'point': 'target' if 'target' in record else ('car' if 'car' in record else 'camera'),
        'lonlat': [round(lon, 7), round(lat, 7)], 'sumo_xy': [x, y], 'godot': point['position'],
        'osm': f'https://www.openstreetmap.org/?mlat={lat:.6f}&mlon={lon:.6f}#map=19/{lat:.6f}/{lon:.6f}',
        'edges': [{'id': e.getID(), 'name': e.getName(), 'type': e.getType(), 'lanes': e.getLaneNumber(),
                   'distance_m': round(d, 1)} for e, d in edges[:4]],
    }
    if nodes:
        node, d = nodes[0]
        out['junction'] = {'id': node.getID(), 'type': node.getType(), 'distance_m': round(d, 1),
                           'edges': len(node.getIncoming()) + len(node.getOutgoing())}
    return out


def main():
    import sumolib
    sys.stdout.reconfigure(encoding='utf-8')
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--map', help='map id (default: every map with notes)')
    ap.add_argument('--radius', type=float, default=25.0, help='edge search radius, m')
    args = ap.parse_args()
    root = paths.ROOT / 'logs/defects'
    maps = [args.map] if args.map else sorted(p.name for p in root.iterdir() if p.is_dir()) if root.exists() else []
    for mid in maps:
        notes = root / mid / 'defects.jsonl'
        if not notes.exists():
            continue
        net = sumolib.net.readNet(str(paths.build_dir(mid) / 'network.net.xml'), withInternal=False)
        records = [json.loads(line) for line in notes.read_text(encoding='utf-8').splitlines() if line.strip()]
        resolved = [resolve(net, r, args.radius) for r in records]
        (root / mid / 'defects.resolved.json').write_text(json.dumps(resolved, ensure_ascii=False, indent=1),
                                                          encoding='utf-8')
        print(f'== {mid}: {len(resolved)} notes')
        for r in resolved:
            edge = r['edges'][0] if r['edges'] else None
            where = f"{edge['id']} '{edge['name']}' {edge['type']} {edge['distance_m']} m" if edge else 'no edge'
            j = r.get('junction', {})
            print(f"#{r['n']} {r['lonlat'][1]:.6f},{r['lonlat'][0]:.6f} [{r['point']}] {where}; "
                  f"junction {j.get('id')} {j.get('distance_m')} m — {r['note']}")


if __name__ == '__main__':
    main()
