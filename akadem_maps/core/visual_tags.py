"""Facade family of a building for game/visuals/tile.gd, from OSM tags only.

Buildings without a telling tag stay unclassified (visual_source "synthetic"): the game then
picks a family from the OSM id, so no detail is claimed that OSM does not state.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MATERIAL_FAMILY = {'brick': 'brick', 'glass': 'modern', 'concrete': 'panel', 'concrete_panels': 'panel'}


def overrides(path=ROOT/'config/visuals/style.json'):
    """Manual per-OSM-id corrections backed by a dated reference, e.g. {"123": {"family": "modern", "source": "photo 2026"}}."""
    return json.loads(Path(path).read_text()).get('overrides', {}) if Path(path).exists() else {}


def classify(way_id, tags, manual):
    out = {'building_type': tags.get('building', '')}
    family = MATERIAL_FAMILY.get(tags.get('building:material', ''))
    if family:
        out['visual_family'] = family
    out['visual_source'] = 'osm' if family else 'synthetic'
    fix = manual.get(str(way_id), {})
    if 'family' in fix:
        out['visual_family'] = fix['family']
        out['visual_source'] = fix.get('source', 'manual synthetic override')
    return out
