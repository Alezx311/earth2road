"""Where a map's generated files live. Each config id has its own build, so several maps
(e.g. akadem, focus_metro_mcd, west_kyiv) coexist and one can be run without rebuilding:

    data/build/<id>/     SUMO network, routes, demand, corrected OSM, logs
    game/data/<id>/      index.json + tiles/*.json for Godot

The active map: AKADEM_MAP environment variable, else game/data/active_map (written by
the last tools/prepare.py run), else 'akadem'."""
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ACTIVE = ROOT / 'game/data/active_map'

def map_id(explicit=None):
    if explicit:
        return explicit
    if os.environ.get('AKADEM_MAP'):
        return os.environ['AKADEM_MAP']
    if ACTIVE.exists() and ACTIVE.read_text().strip():
        return ACTIVE.read_text().strip()
    return 'akadem'

def build_dir(mid=None):
    return ROOT / 'data/build' / map_id(mid)

def game_dir(mid=None):
    return ROOT / 'game/data' / map_id(mid)

TILED = ('road_strips', 'markings', 'sidewalks', 'walkingareas', 'junctions', 'buildings', 'greens', 'parking', 'paths', 'trees', 'ground', 'signs', 'fences')

def load_world(mid=None, tiles=False):
    """index.json; with tiles=True the tiled geometry is merged back (tests, tools)."""
    folder = game_dir(mid)
    world = json.loads((folder / 'index.json').read_text(encoding='utf-8'))
    if tiles:
        for key in TILED:
            world[key] = []
        for name in world['tiles']:
            tile = json.loads((folder / 'tiles' / f'{name}.json').read_text(encoding='utf-8'))
            for key in TILED:
                world[key].extend(tile.get(key, []))
    return world
