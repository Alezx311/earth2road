"""Opt-in, engine-neutral neighbourhood appearance. All profile values are hypotheses.

Coordinates in Field are world X/Z metres. OSM facts never come from a profile.
The compact-support kernel blends distributions, not independently chosen buildings.
"""
from collections import Counter
import copy
import hashlib
import math
import re

from shapely.geometry import Polygon

FAMILIES = ('historic', 'brick', 'panel', 'modern', 'industrial')
MATERIALS = ('plaster', 'brick', 'concrete', 'glass', 'metal', 'stone')
VISUAL_FAMILY = dict(zip(FAMILIES, ('public', 'brick', 'panel', 'modern', 'public')))
COLORS = {'cream': '#ded7c5', 'yellow': '#d7be83', 'pale_green': '#afbeaa',
          'brick': '#896b54', 'grey': '#aaa9a4', 'white': '#deded7',
          'beige': '#c9c1ae', 'brown': '#896b54', 'red': '#a7624b', 'black': '#454849'}


def unit(seed, key, property_name):
    digest = hashlib.sha256(f'{seed}|{key}|{property_name}'.encode()).digest()
    return int.from_bytes(digest[:8], 'big') / 2**64


def colour(value):
    value = str(value).strip().lower()
    return value if re.fullmatch(r'#[0-9a-f]{6}', value) else COLORS.get(value)


def validate(document):
    if not isinstance(document, dict) or document.get('version') != 1:
        raise ValueError('Local Visual DNA requires version 1')
    profiles = document.get('profiles')
    if not isinstance(profiles, dict) or not profiles:
        raise ValueError('Local Visual DNA requires profiles')
    for pid, p in profiles.items():
        if not isinstance(p, dict) or not p.get('provenance'):
            raise ValueError(f'DNA profile {pid}: provenance is required')
        for key, allowed in (('architecture', FAMILIES), ('materials', MATERIALS),
                             ('roofs', ('flat', 'gabled')), ('colors', None), ('floors', None)):
            weights = p.get(key)
            if not isinstance(weights, dict) or not weights:
                raise ValueError(f'DNA profile {pid}: missing distribution {key}')
            for value, weight in weights.items():
                if isinstance(weight, bool) or not isinstance(weight, (int, float)) or not math.isfinite(weight) or weight < 0:
                    raise ValueError(f'DNA profile {pid}: invalid weight in {key}')
                if allowed and value not in allowed:
                    raise ValueError(f'DNA profile {pid}: unsupported {key} {value}')
                if key == 'colors' and not colour(value):
                    raise ValueError(f'DNA profile {pid}: invalid colour {value}')
                if key == 'floors' and (not str(value).isdigit() or not 1 <= int(value) <= 60):
                    raise ValueError(f'DNA profile {pid}: invalid floors {value}')
            if sum(weights.values()) <= 0:
                raise ValueError(f'DNA profile {pid}: empty probability mass in {key}')
        density = p.get('vegetation_density', 1)
        if isinstance(density, bool) or not isinstance(density, (int, float)) or not math.isfinite(density) or not 0 <= density <= 3:
            raise ValueError(f'DNA profile {pid}: vegetation_density must be 0..3')
    if not isinstance(document.get('anchors', []), list):
        raise ValueError('DNA anchors must be a list')
    seen = set()
    for a in document.get('anchors', []):
        if not isinstance(a, dict):
            raise ValueError('DNA anchor must be an object')
        if not isinstance(a.get('id'), str) or not a['id'] or a['id'] in seen:
            raise ValueError('DNA anchors require unique nonempty IDs')
        seen.add(a['id'])
        if a.get('profile') not in profiles or not a.get('provenance'):
            raise ValueError(f'DNA anchor {a["id"]}: profile and provenance required')
        for key, lo, hi in (('lon', -180, 180), ('lat', -85, 85), ('radius_m', 1, 10000)):
            v = a.get(key)
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or not lo <= v <= hi:
                raise ValueError(f'DNA anchor {a["id"]}: invalid {key}')
    return document


class Field:
    def __init__(self, document, to_world, seed):
        self.document = copy.deepcopy(validate(document))
        self.seed = seed
        self.anchors = [dict(a, position=list(to_world(a['lon'], a['lat'])))
                        for a in sorted(self.document.get('anchors', []), key=lambda a: a['id'])]
        self.counts = Counter()

    def weights(self, x, z):
        result = []
        for a in self.anchors:
            d = math.dist((x, z), (a['position'][0], a['position'][2])) / a['radius_m']
            if d < 1:
                result.append((a, (1-d*d)**2))
        total = sum(w for _, w in result)
        return [(a, w/total) for a, w in result] if total else []

    def sample(self, x, z):
        weights = self.weights(x, z)
        if not weights:
            return None
        result = {k: Counter() for k in ('architecture', 'materials', 'colors', 'floors', 'roofs')}
        result['vegetation_density'] = 0.0
        result['strength'] = min(1.0, sum((1-(math.dist((x,z), (a['position'][0],a['position'][2]))/a['radius_m'])**2)**2
                                        for a, _ in weights))
        result['influences'] = [{'id': a['id'], 'weight': round(w, 6)} for a, w in weights]
        for a, w in weights:
            p = self.document['profiles'][a['profile']]
            for key in ('architecture', 'materials', 'colors', 'floors', 'roofs'):
                total = sum(p[key].values())
                for v, n in p[key].items():
                    result[key][v] += w*n/total
            result['vegetation_density'] += w*p.get('vegetation_density', 1)
        return result

    def density(self, x, z):
        sample = self.sample(x, z)
        return 1+(sample['vegetation_density']-1)*sample['strength'] if sample else 1.0

    def pick(self, distribution, key, property_name):
        target = unit(self.seed, key, property_name) * sum(distribution.values())
        for value, weight in sorted(distribution.items()):
            target -= weight
            if target < 0:
                return value
        return sorted(distribution)[-1]

    def apply(self, b, tags):
        poly = Polygon([(p[0], p[2]) for p in b['points']])
        sample = self.sample(poly.centroid.x, poly.centroid.y)
        if not sample:
            return
        key = str(b['id'])
        # Fade the chance of applying grammar to the legacy default at coverage edges.
        if unit(self.seed, key, 'coverage') >= sample['strength']:
            return
        origin = {k: 'synthetic:local_visual_dna' for k in ('architecture', 'material', 'color', 'roof', 'levels')}
        family = self.pick(sample['architecture'], key, 'architecture')
        material = self.pick(sample['materials'], key, 'material')
        # A specific OSM use remains a constraint on the synthetic grammar.
        if b.get('building_type') in ('industrial', 'warehouse', 'hangar', 'garages', 'garage', 'shed'):
            family = 'industrial'
            origin['architecture'] = 'derived:osm_building_type'
        observed_material = tags.get('building:material')
        if observed_material:
            material = observed_material
            origin['material'] = 'osm'
            observed_family = {'brick': 'brick', 'concrete': 'panel', 'concrete_panels': 'panel',
                               'glass': 'modern', 'metal': 'industrial'}.get(material)
            if observed_family:
                family = observed_family
                origin['architecture'] = 'derived:osm_material'
        color = colour(self.pick(sample['colors'], key, 'color'))
        if tags.get('building:colour') or tags.get('building:color'):
            observed_color = tags.get('building:colour', tags.get('building:color'))
            color = colour(observed_color)
            origin['color'] = 'osm' if color else 'unsupported:osm'
        shape = tags.get('roof:shape') or self.pick(sample['roofs'], key, 'roof')
        if 'roof:shape' in tags:
            origin['roof'] = 'osm'
        if b['height_source'] == 'assumed':
            floors = int(self.pick(sample['floors'], key, 'floors'))
            if b.get('building_type') in ('garage', 'garages', 'shed'):
                floors = 1
            b.update(levels=floors, height=float(floors*3), height_source='synthetic:local_visual_dna')
        else:
            origin['levels'] = 'osm' if 'building:levels' in tags else 'derived:height'
            if 'height' in tags and 'building:levels' not in tags:
                b['levels'] = max(1, round(b['height']/3))
        origin['height'] = 'osm' if 'height' in tags else ('derived:osm_levels' if 'building:levels' in tags else b['height_source'])
        b['local_style'] = {'version': 1, 'architecture': family, 'material': material,
                            'color': color, 'roof': shape, 'provenance': origin,
                            'influences': sample['influences']}
        if observed_color := tags.get('building:colour', tags.get('building:color')):
            b['local_style']['observed_color'] = observed_color
        b['visual_family'] = VISUAL_FAMILY[family]
        b['visual_source'] = 'local_visual_dna; see local_style.provenance'
        self.counts['styled_buildings'] += 1

    def report(self):
        return {'version': 1, 'seed': self.seed, 'profiles': self.document['profiles'],
                'visual_anchors': self.anchors, 'counts': dict(self.counts),
                'provenance': 'Manual hypotheses; not photo analysis or surveyed building appearance.'}


def roof(b):
    """Reuse the exact-footprint gable solver without rural decoration or height overrides."""
    style = b.get('local_style')
    if not style:
        return
    style = b['local_style'] = copy.deepcopy(style)
    shape = style['roof']
    if shape == 'flat':
        return
    poly = Polygon([(p[0], p[2]) for p in b['points']])
    if shape != 'gabled' or not poly.is_valid or poly.area < 8 or len(b['points']) > 12 or b.get('base', 0):
        style['roof_fallback'] = 'flat: unsupported shape, footprint or raised passage'
        return
    from . import rural
    temp = copy.deepcopy(b)
    floor = min(p[1] for p in b['points'])
    temp['points'] = [[p[0], floor, p[2]] for p in b['points']]
    temp['height_source'] = 'dna_roof'  # no rural small-building height override
    rural.roof(temp, {'roof:shape': 'gabled'})
    for key in ('wall_height', 'floor_height', 'roof_triangles', 'roof_gables', 'roof_shape_rendered'):
        if key in temp:
            b[key] = temp[key]
    if 'roof_triangles' not in b:
        style['roof_fallback'] = 'flat: degenerate roof span'
    b['roof_material'] = 'roof_metal'


def material_key(style):
    """A shared material per grammar/material/palette combination, never per building."""
    token = hashlib.sha256(str(style['material']).encode()).hexdigest()[:8]
    return f'kyiv_dna_fac_{style["architecture"]}_{token}_{(style.get("color") or "#b5b2aa")[1:]}'


def facade_pixels(style, size=256):
    """Original procedural artwork; one 6 m repeat, no downloaded imagery."""
    color = style.get('color') or '#b5b2aa'
    base = tuple(int(color[i:i+2], 16) for i in (1, 3, 5))
    family, material = style['architecture'], style['material']
    pixels = []
    for y in range(size):
        v = (y % (size//2))/(size//2)
        for x in range(size):
            u = (x % (size//2))/(size//2)
            grain = 1 + ((x*13+y*7)%11-5)/160
            c = tuple(int(k*grain) for k in base)
            if material == 'brick' and (y % 9 == 0 or (x+(y//9%2)*12)%24 == 0):
                c = tuple(int(k*.75) for k in base)
            if family == 'panel' and (v < .025 or u < .02):
                c = tuple(int(k*.8) for k in base)
            lo, hi = (.24, .64) if family == 'historic' else ((.08, .92) if family in ('modern','industrial') else (.18,.82))
            top, bottom = (.15, .78) if family == 'historic' else ((.27, .65) if family == 'industrial' else (.22,.72))
            if lo <= u <= hi and top <= v <= bottom:
                edge = min(u-lo, hi-u, v-top, bottom-v)
                frame = edge < .035 or abs(u-(lo+hi)/2) < .012
                c = (228, 224, 211) if frame else (74, 91, 100)
            if family == 'historic' and (v > .91 or (lo-.05 < u < hi+.05 and bottom < v < bottom+.035)):
                c = (233, 226, 208)
            pixels.extend(max(0, min(255, k)) for k in c)
    return pixels
