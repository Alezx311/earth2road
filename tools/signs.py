"""Compatibility entry point; implementation lives in akadem_maps.

Run directly to recompute the signs of an already-built legacy game/data map:
    .venv/bin/python tools/signs.py --map west_kyiv
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
if __name__ == "__main__":
    import argparse
    import json
    import math
    import sumolib
    import paths
    from akadem_maps.core import signs

    def rebuild(map_id):
        """Standalone: recompute the signs of an already-built map and patch its tiles."""
        build, game = paths.build_dir(map_id), paths.game_dir(map_id)
        index = json.loads((game / 'index.json').read_text())
        # Same read as tools/prepare.py, so the standalone result matches the pipeline exactly.
        net = sumolib.net.readNet(str(build / 'network.net.xml'), withInternal=True, withPrograms=True)
        world = paths.load_world(map_id, tiles=True)
        osm = signs.osm_facts(build / 'corrected.osm', net, index['offset'])
        counts = {}
        records = signs.derive(net, world['lanes'], osm, counts)
        ox, oy = index['offset']
        index['tls'] = signs.traffic_lights(net, lambda x, y: [round(x - ox, 3), 0.0, round(-(y - oy), 3)])

        size = float(index['tile_size'])
        buckets = {}
        for record in records:
            name = '%d_%d' % (math.floor(record['position'][0] / size), math.floor(record['position'][2] / size))
            buckets.setdefault(name, []).append(record)
        for name in index['tiles']:
            path = game / 'tiles' / f'{name}.json'
            tile = json.loads(path.read_text())
            tile['signs'] = buckets.get(name, [])
            path.write_text(json.dumps(tile, separators=(',', ':')))
        index.pop('signs', None)
        (game / 'index.json').write_text(json.dumps(index, separators=(',', ':')))

        audit_path = build / 'audit.json'
        if audit_path.exists():
            audit = json.loads(audit_path.read_text())
            audit['signs'] = counts
            audit['traffic_light_programs'] = len(index['tls'])
            note = ('Road signs are derived from the SUMO network and OSM tags; Kyiv OSM has almost '
                    'no traffic_sign nodes. Each record carries provenance = osm | derived. Signal '
                    'phase programs are netconvert defaults, not observed Kyiv timings.')
            if note not in audit.get('assumptions', []):
                audit.setdefault('assumptions', []).append(note)
            audit_path.write_text(json.dumps(audit, indent=2))
        outside = len(buckets) - len([n for n in buckets if n in index['tiles']])
        print(json.dumps({'map': paths.map_id(map_id), 'signs': counts,
                          'traffic_lights': len(index['tls']),
                          'signs_outside_known_tiles': outside}, indent=2))

    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--map', help='map id (default: AKADEM_MAP or the last prepared map)')
    rebuild(p.parse_args().map)
else:
    from akadem_maps.core import signs as implementation
    sys.modules[__name__] = implementation
