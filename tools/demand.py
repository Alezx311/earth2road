"""Compatibility entry point; implementation lives in akadem_maps.adapters.godot.demand.

Run directly to rebuild data/build/<id>/demand.json of a legacy build (no netconvert):
    .venv/bin/python tools/demand.py --config config/akadem.json
"""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
if __name__ == "__main__":
    import argparse
    import json
    import xml.etree.ElementTree as ET
    import sumolib
    from akadem_maps.context import BuildContext
    from akadem_maps.adapters.godot import demand
    parser = argparse.ArgumentParser(description='Rebuild data/build/<id>/demand.json from the current build (no netconvert).')
    parser.add_argument('--config', default='config/akadem.json')
    parser.add_argument('--counts', help='observed counts JSON (default config/counts.json)')
    args = parser.parse_args()
    cfg = json.loads((ROOT / args.config).read_text(encoding='utf8'))
    build = ROOT / 'data/build' / cfg['id']
    context = BuildContext(build, ROOT / 'data/raw', ROOT)
    net = sumolib.net.readNet(str(build / 'network.net.xml'))
    root = ET.parse(build / 'corrected.osm').getroot()
    print(json.dumps(demand.build(cfg, root, net, cfg['seed'], args.counts, context=context), ensure_ascii=False, indent=2))
else:
    from akadem_maps.adapters.godot import demand as implementation
    sys.modules[__name__] = implementation
