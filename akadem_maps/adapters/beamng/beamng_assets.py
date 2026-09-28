"""Catalogue of BeamNG stock art referenced by the generated Kyiv level.

Nothing is copied out of the installation. Shapes stay in the game's global
libraries (``/art/shapes`` from content/art_shapes.zip, ``/assets/meshes`` from
content/assets/meshes.zip) and textures in ``/assets/materials``; the material,
forest and prop definitions below are written by this project and only point at
those paths, so the distributed mod holds no redistributed game files.

Texture maps are named with the ``.png`` extension the stock materials use; the
engine resolves the shipped ``.dds`` variant itself.
"""
from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path

TEX = '/assets/materials'
OBJECTS = '/art/shapes/objects'
TREES = '/assets/meshes/foliage/trees_library'
BUSHES = '/assets/meshes/foliage/bushes'


def _pick(key, options):
    """Stable per-key choice so regenerating a tile never reshuffles the city."""
    digest = hashlib.sha256(str(key).encode('utf8')).digest()
    return options[int.from_bytes(digest[:4], 'big') % len(options)]


def _stage(base, normal=None, rough=None, ao=None, opacity=None, detail=None, **extra):
    stage = {'baseColorMap': base}
    for field, value in (('normalMap', normal), ('roughnessMap', rough),
                         ('ambientOcclusionMap', ao), ('opacityMap', opacity),
                         ('detailMap', detail)):
        if value:
            stage[field] = value
    stage.update(extra)
    return stage


def _material(name, stage, **extra):
    return {name: {'name': name, 'mapTo': name, 'class': 'Material', 'version': 1.5,
                   'Stages': [stage, {}, {}, {}], **extra}}


def _tileset(folder, stem, *, maps='b nm r ao', **extra):
    """Standard BeamNG tileable set: <folder>/<stem>_{b,nm,r,ao}."""
    parts = maps.split()
    path = f'{TEX}/{folder}/{stem}'
    return _stage(f'{path}_b.color.png',
                  normal=f'{path}_nm.normal.png' if 'nm' in parts else None,
                  rough=f'{path}_r.data.png' if 'r' in parts else None,
                  ao=f'{path}_ao.data.png' if 'ao' in parts else None,
                  **extra)


# name -> (stage, metres covered by one UV unit, extra material fields)
SURFACES = {
    'kyiv_asphalt': (_tileset('tileable/road/m_road_asphalt_rough_01', 't_road_asphalt_rough_01'),
                     6.0, {'groundType': 'ASPHALT', 'annotation': 'STREET', 'materialTag0': 'RoadAndPath'}),
    'kyiv_asphalt_worn': (_tileset('tileable/road/m_asphalt_new_01', 't_asphalt_02', maps='b nm ao'),
                          8.0, {'groundType': 'ASPHALT', 'annotation': 'STREET', 'materialTag0': 'RoadAndPath'}),
    # Plain scored concrete, not the Italian decorative pavers. The ring sidewalk
    # at the Odesa interchange is large grey slabs (Street View, May 2015).
    'kyiv_concrete': (_tileset('tileable/concrete/sidewalk1', 't_sidewalk1', maps='b nm r'),
                      2.5, {'groundType': 'ASPHALT', 'annotation': 'SIDEWALK'}),
    'kyiv_curb': (_tileset('tileable/concrete/concrete_plain', 't_concrete_plain'),
                  4.0, {'groundType': 'ASPHALT', 'annotation': 'SIDEWALK'}),
    # The /assets/materials/terrain sets are TerrainBlock detail layers and blow out when
    # used as a plain mesh base colour, so mesh ground uses the groundmesh and tileable
    # soil sets instead, held down with baseColorFactor.
    'kyiv_grass': (_stage(f'{TEX}/terrain/grass/groundmesh_grass2/groundmesh_grass_b.color.png',
                          normal=f'{TEX}/terrain/grass/grass_garden/t_grass_long_nm.normal.png',
                          detail=f'{TEX}/terrain/grass/groundmesh_grass2/groundmesh_grass_detail.color.png',
                          detailScale=[9, 9], baseColorFactor=[0.66, 0.72, 0.60, 1],
                          roughnessFactor=0.95),
                   9.0, {'groundType': 'GRASS', 'annotation': 'NATURE'}),
    # Fill ground between the streets is worn lawn in this district, not bare soil:
    # the mown-grass base keeps the dirt only as a detail break-up.
    'kyiv_ground': (_stage(f'{TEX}/terrain/grass/groundmesh_grass2/groundmesh_grass_b.color.png',
                           normal=f'{TEX}/terrain/grass/grass_garden/t_grass_long_nm.normal.png',
                           detail=f'{TEX}/tileable/soil/m_dirt/t_gm_dirt_detail.png',
                           detailScale=[6, 6], baseColorFactor=[0.70, 0.71, 0.56, 1],
                           roughnessFactor=0.95),
                    11.0, {'groundType': 'DIRT', 'annotation': 'NATURE'}),
    'kyiv_gravel': (_stage(f'{TEX}/tileable/road/jri_dirt_mesh/jri_dirt_mesh_d.color.png',
                           normal=f'{TEX}/tileable/road/jri_dirt_mesh/jri_dirt_mesh_n.normal.png',
                           baseColorFactor=[0.78, 0.76, 0.72, 1], roughnessFactor=0.95),
                    4.0, {'groundType': 'GRAVEL', 'annotation': 'NATURE'}),
    'kyiv_metal': (_stage(f'{TEX}/tileable/metal/metal_galvanized/t_metal_galvanized_01_b.color.png',
                          rough=f'{TEX}/tileable/metal/metal_galvanized/t_metal_galvanized_02_r.data.png',
                          metallicMap=f'{TEX}/tileable/metal/metal_galvanized/t_metal_galvanized_02_m.data.png',
                          metallicFactor=1),
                   1.5, {'groundType': 'METAL', 'annotation': 'POLE'}),
}

# Facade palette. Kyiv mass housing is precast panel and silicate brick; plaster and
# painted brick cover the older low-rise, glass the post-2000 commercial infill.
FACADES = {
    'kyiv_fac_panel': (_tileset('tileable/concrete/slabs_brutalist', 't_slabs_brutalist'), 6.0),
    'kyiv_fac_precast': (_tileset('tileable/concrete/concrete_precast1', 't_concrete_precast_01'), 6.0),
    'kyiv_fac_plaster': (_tileset('tileable/plaster/m_plaster_worn_01', 't_plaster_worn_01'), 5.0),
    'kyiv_fac_stucco': (_tileset('tileable/plaster/stucco1_white', 't_stucco1_white'), 5.0),
    'kyiv_fac_brick_red': (_tileset('tileable/brick/brick_plain', 't_bricks_red_01'), 4.0),
    'kyiv_fac_brick_white': (_tileset('tileable/brick/t_brick_white_paint_01', 't_brick_white_paint_01'), 4.0),
    'kyiv_fac_block': (_tileset('tileable/brick/ind_blockwall', 't_concrete_cinderblock_01'), 4.0),
    'kyiv_fac_glass': (_tileset('tileable/glass/modernstripwindow', 't_window_strips_01', maps='b nm r'), 8.0),
    'kyiv_fac_windows': (_tileset('tileable/glass/windows1', 't_bld_ind_windows', maps='b nm r'), 6.0),
}

ROOFS = {
    'kyiv_roof_flat': (_tileset('tileable/roofing/asphalt_roof', 't_asphalt_roof'), 5.0),
    'kyiv_roof_metal': (_stage(f'{TEX}/tileable/metal/si_metal_roof/si_metal_roof_d.color.png',
                               normal=f'{TEX}/tileable/metal/si_metal_roof/si_metal_roof.normal.png'), 3.0),
    'kyiv_roof_tin': (_stage(f'{TEX}/tileable/metal/ind_bld_tin_02/tin-01b_d.dds',
                             normal=f'{TEX}/tileable/metal/ind_bld_tin_02/tin-01b_n.dds'), 4.0),
    'kyiv_roof_slate': (_tileset('tileable/roofing/m_roof_slates_square', 't_roof_slates_square'), 3.0),
}

# Windowed facades are drawn by the exporter: the shared BeamNG tileable sets are
# blank wall surfaces, and a district of 1960s-80s panel blocks reads as a quarry
# without window openings. Key -> (base colour, window colour, style).
PANEL_FACADES = {
    'kyiv_fac_flat_grey': ((0.60, 0.60, 0.58), (0.20, 0.24, 0.27), 'balcony'),
    'kyiv_fac_flat_beige': ((0.72, 0.67, 0.55), (0.19, 0.23, 0.26), 'balcony'),
    'kyiv_fac_flat_cream': ((0.78, 0.76, 0.70), (0.21, 0.25, 0.28), 'plain'),
    'kyiv_fac_flat_brick': ((0.64, 0.50, 0.40), (0.18, 0.22, 0.25), 'plain'),
    'kyiv_fac_flat_silicate': ((0.80, 0.79, 0.74), (0.20, 0.24, 0.27), 'balcony'),
}
PANEL_TILE = 6.0  # metres per texture repeat: two 3 m storeys by two 3 m bays

# Drawn by the exporter. Malls read as a glass grid; big-box retail as pale
# horizontal panels over a glazed ground floor. Neither copies a brand.
DRAWN_FACADES = {
    'kyiv_fac_curtain': 8.0,
    'kyiv_fac_cladding': 6.0,
}


def landmarks():
    """OSM way id -> {name, facade, roof}. Missing file means no pins."""
    path = Path(__file__).resolve().parents[2] / 'resources' / 'landmarks.json'
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding='utf8'))
    return {str(key): value for key, value in data.get('by_id', {}).items()}


LANDMARKS = landmarks()

# Facade/roof choice per OSM building type; first entry is the most common.
BUILDING_STYLE = {
    'apartments': (('kyiv_fac_flat_grey', 'kyiv_fac_flat_beige', 'kyiv_fac_flat_silicate',
                    'kyiv_fac_flat_cream', 'kyiv_fac_flat_brick'), ('kyiv_roof_flat',)),
    'dormitory': (('kyiv_fac_flat_silicate', 'kyiv_fac_flat_grey'), ('kyiv_roof_flat',)),
    'residential': (('kyiv_fac_flat_grey', 'kyiv_fac_flat_beige'), ('kyiv_roof_flat',)),
    'house': (('kyiv_fac_plaster', 'kyiv_fac_brick_red', 'kyiv_fac_stucco'),
              ('kyiv_roof_metal', 'kyiv_roof_slate')),
    'detached': (('kyiv_fac_plaster', 'kyiv_fac_brick_red'), ('kyiv_roof_metal', 'kyiv_roof_slate')),
    'commercial': (('kyiv_fac_glass', 'kyiv_fac_stucco', 'kyiv_fac_precast'), ('kyiv_roof_flat',)),
    'retail': (('kyiv_fac_glass', 'kyiv_fac_stucco'), ('kyiv_roof_flat',)),
    'shop': (('kyiv_fac_glass', 'kyiv_fac_stucco'), ('kyiv_roof_flat',)),
    'kiosk': (('kyiv_fac_glass',), ('kyiv_roof_metal',)),
    'office': (('kyiv_fac_glass', 'kyiv_fac_flat_cream'), ('kyiv_roof_flat',)),
    'industrial': (('kyiv_fac_block', 'kyiv_fac_windows', 'kyiv_fac_precast'), ('kyiv_roof_tin', 'kyiv_roof_metal')),
    'warehouse': (('kyiv_fac_block', 'kyiv_fac_windows'), ('kyiv_roof_metal',)),
    'hangar': (('kyiv_fac_windows',), ('kyiv_roof_metal',)),
    'garages': (('kyiv_fac_block', 'kyiv_fac_brick_white'), ('kyiv_roof_tin',)),
    'garage': (('kyiv_fac_block',), ('kyiv_roof_tin',)),
    'shed': (('kyiv_fac_block',), ('kyiv_roof_tin',)),
    'greenhouse': (('kyiv_fac_glass',), ('kyiv_roof_metal',)),
    'construction': (('kyiv_fac_precast', 'kyiv_fac_block'), ('kyiv_roof_flat',)),
    'school': (('kyiv_fac_flat_cream', 'kyiv_fac_flat_silicate'), ('kyiv_roof_flat',)),
    'kindergarten': (('kyiv_fac_flat_cream', 'kyiv_fac_flat_beige'), ('kyiv_roof_flat',)),
    'university': (('kyiv_fac_flat_cream', 'kyiv_fac_precast'), ('kyiv_roof_flat',)),
    'hospital': (('kyiv_fac_flat_cream', 'kyiv_fac_flat_silicate'), ('kyiv_roof_flat',)),
    'church': (('kyiv_fac_stucco',), ('kyiv_roof_metal',)),
    'chapel': (('kyiv_fac_stucco',), ('kyiv_roof_metal',)),
    'service': (('kyiv_fac_block', 'kyiv_fac_plaster'), ('kyiv_roof_tin',)),
    'guardhouse': (('kyiv_fac_block',), ('kyiv_roof_tin',)),
    'transportation': (('kyiv_fac_precast', 'kyiv_fac_glass'), ('kyiv_roof_flat',)),
    'ruins': (('kyiv_fac_block',), ('kyiv_roof_tin',)),
    'roof': (('kyiv_fac_block',), ('kyiv_roof_metal',)),
}
# Untyped OSM footprints are the largest group, so the default keeps several panel
# skins: the tall-block filter would otherwise collapse them all to one colour.
DEFAULT_STYLE = (('kyiv_fac_plaster', 'kyiv_fac_flat_grey', 'kyiv_fac_flat_beige',
                  'kyiv_fac_brick_white', 'kyiv_fac_flat_cream', 'kyiv_fac_precast',
                  'kyiv_fac_flat_silicate'), ('kyiv_roof_flat',))


def building_style(building):
    """Deterministic facade/roof pair for one OSM footprint.

    A landmark pin (config/landmarks.json) wins over the type palette. The pin
    names the real place and only selects a synthetic facade family.
    """
    pinned = LANDMARKS.get(str(building.get('id') or ''))
    if pinned and pinned.get('facade') in DRAWN_FACADES and pinned.get('roof') in ROOFS:
        return pinned['facade'], pinned['roof']
    facades, roofs = BUILDING_STYLE.get((building.get('building_type') or '').strip(), DEFAULT_STYLE)
    height = float(building.get('height') or 0)
    if height >= 24 and any(f in PANEL_FACADES for f in facades):
        # The tall stock in this district is large-panel; leave it the panel skins.
        facades = tuple(f for f in facades if f in PANEL_FACADES)
    return _pick(('facade', building['id']), facades), _pick(('roof', building['id']), roofs)


# --- vegetation -------------------------------------------------------------
# Forest item -> (shape, radius, wind scale). Birch/aspen, oak and beech carry the
# left bank districts; nothing tropical or coniferous is used.
FOREST_ITEMS = {
    'kyiv_birch_large_a': (f'{TREES}/birch/tree_aspen_large_a.dae', 0.5, 0.4),
    'kyiv_birch_large_b': (f'{TREES}/birch/tree_aspen_large_b.dae', 0.5, 0.4),
    'kyiv_birch_small_a': (f'{TREES}/birch/tree_aspen_small_a.dae', 0.3, 0.5),
    'kyiv_birch_small_b': (f'{TREES}/birch/tree_aspen_small_b.dae', 0.3, 0.5),
    'kyiv_birch_small_d': (f'{TREES}/birch/tree_aspen_small_d.dae', 0.3, 0.5),
    'kyiv_birch_forest_a': (f'{TREES}/birch/tree_aspen_forest_a.dae', 0.4, 0.4),
    'kyiv_birch_forest_b': (f'{TREES}/birch/tree_aspen_forest_b.dae', 0.4, 0.4),
    'kyiv_oak_large_a': (f'{TREES}/oak/tree_oak_large_a.dae', 0.7, 0.3),
    'kyiv_oak_large_b': (f'{TREES}/oak/tree_oak_large_b.dae', 0.7, 0.3),
    'kyiv_oak_large_c': (f'{TREES}/oak/tree_oak_large_c.dae', 0.7, 0.3),
    'kyiv_oak_small_a': (f'{TREES}/oak/tree_oak_sml_a.dae', 0.4, 0.4),
    'kyiv_oak_small_b': (f'{TREES}/oak/tree_oak_sml_b.dae', 0.4, 0.4),
    'kyiv_oak_forest_a': (f'{TREES}/oak/tree_oak_forest_a.dae', 0.6, 0.3),
    'kyiv_oak_forest_b': (f'{TREES}/oak/tree_oak_forest_b.dae', 0.6, 0.3),
    'kyiv_beech_large_c': (f'{TREES}/beech/tree_beech_large_c.dae', 0.6, 0.35),
    'kyiv_beech_small_b': (f'{TREES}/beech/tree_beech_small_b.dae', 0.35, 0.45),
    'kyiv_beech_small_c': (f'{TREES}/beech/tree_beech_small_c.dae', 0.35, 0.45),
    'kyiv_bush': (f'{BUSHES}/generibush.dae', 0.3, 0.6),
    'kyiv_bush_small': (f'{BUSHES}/generibush_small.dae', 0.2, 0.7),
    'kyiv_bush_oak': (f'{TREES}/oak/tree_oak_bush_b.dae', 0.3, 0.5),
    'kyiv_bush_beech': (f'{TREES}/beech/tree_beech_bush_c.dae', 0.3, 0.5),
}

STREET_TREES = ('kyiv_birch_large_a', 'kyiv_birch_large_b', 'kyiv_oak_large_a', 'kyiv_oak_large_b',
                'kyiv_oak_large_c', 'kyiv_beech_large_c', 'kyiv_birch_small_b', 'kyiv_oak_small_a')
WOOD_TREES = ('kyiv_birch_forest_a', 'kyiv_birch_forest_b', 'kyiv_oak_forest_a', 'kyiv_oak_forest_b',
              'kyiv_beech_small_b', 'kyiv_beech_small_c', 'kyiv_birch_small_a', 'kyiv_birch_small_d')
PARK_BUSHES = ('kyiv_bush', 'kyiv_bush_small', 'kyiv_bush_oak', 'kyiv_bush_beech')


def forest_item_data():
    """``art/forest/managedItemData.json`` for the shapes above."""
    result = {}
    for name, (shape, radius, wind) in sorted(FOREST_ITEMS.items()):
        result[name] = {'name': name, 'internalName': name, 'class': 'TSForestItemData',
                        'annotation': 'NATURE', 'shapeFile': shape, 'radius': radius,
                        'windScale': wind, 'branchAmp': 0.5, 'detailAmp': 0.4,
                        'detailFreq': 0.5, 'dampingCoefficient': 4, 'trunkBendScale': 0.05}
    return result


def forest_files(instances):
    """Current forest layout: ``forest/<item>.forest4.json``, one JSON object per line.

    The single-file ``<level>.forest.json`` v2 form still loads, but the engine logs it
    as deprecated and asks for a resave.
    """
    grouped = defaultdict(list)
    for item, x, y, z, yaw, scale in instances:
        cos, sin = math.cos(yaw), math.sin(yaw)
        grouped[item].append({'ctxid': 2, 'type': item,
                              'pos': [round(x, 4), round(y, 4), round(z, 4)],
                              'rotationMatrix': [round(cos, 6), round(-sin, 6), 0,
                                                 round(sin, 6), round(cos, 6), 0, 0, 0, 1],
                              'scale': round(scale, 4)})
    return {f'forest/{item}.forest4.json':
            ''.join(json.dumps(v, sort_keys=True) + '\n' for v in grouped[item])
            for item in sorted(grouped)}


# --- street furniture -------------------------------------------------------
# Shapes from the global /art/shapes library; their materials ship with the game.
PROP_SHAPES = {
    'street_lamp': f'{OBJECTS}/lamp1.dae',            # 7.9 m city pole
    'highway_lamp': f'{OBJECTS}/pole_light_single.dae',  # 13 m mast, arm along +X
    'bus_stop': f'{OBJECTS}/s_busstop_ecu.dae',
    'bus_stop_sign': f'{OBJECTS}/s_sign_busstop.dae',
    'guardrail': f'{OBJECTS}/guardrail1.dae',         # 2.42 m section
    'jersey_barrier': f'{OBJECTS}/jerseybarrier_3m.dae',
    'bollard': f'{OBJECTS}/bollard_yellow.dae',
    'power_pole': '/art/shapes/common/power_lines_procedural/electric_pole_wood_old_01.dae',
    'fence_chainlink': f'{OBJECTS}/s_chainlink_old.dae',  # 2.06 m section along -X
}

TREE_MATERIALS = ('Birch_Bark_01', 'Birch_Branch_01', 'm_ind_birch_leaves_01', 'leaves_strong',
                  'leaves_thin', 'Oak_bark_01', 'Oak_branch_01', 'Oak_branch_02', 'oak_leaves_01',
                  'oak_leaves_02', 'beech_trunk', 'beech_branch_01', 'beech_leaves', 'beech_blocker',
                  'generibush_leaves', 'Moss_01', 'ColorEffectR27G177B88-material')

_LEAF = {'alphaTest': True, 'doubleSided': True, 'subSurface': True, 'subSurfaceIntensity': 1,
         'invertBackFaceNormals': True, 'groundType': 'LEAVES_THIN', 'annotation': 'NATURE',
         'translucentBlendOp': 'None', 'materialTag0': 'vegetation'}
_BARK = {'groundType': 'WOOD', 'annotation': 'NATURE', 'materialTag0': 'vegetation'}
_BRANCH = dict(_LEAF, groundType='WOOD')
_BARK_DETAIL = f'{TEX}/tree/tropical/tro_tree_1_trunk/t_tropical_bark_variation_1_detail.data.png'


def _leafset(folder, stem, base=None, **extra):
    path = f'{TEX}/{folder}/{stem}'
    return _stage(base or f'{path}_b.color.png', normal=f'{path}_nm.normal.png',
                  rough=f'{path}_r.data.png', ao=f'{path}_ao.data.png',
                  opacity=f'{path}_o.data.png', pixelSpecular=True, **extra)


def tree_materials():
    """Definitions for every material the shared foliage meshes bind to.

    ``m_ind_birch_leaves_01`` ships with no definition anywhere in the game, so the
    stock birch meshes would render it untextured; it is rebuilt here from the
    matching ``t_birch_leaves_ind`` base colour and the shared birch maps.
    """
    birch = f'{TEX}/tree/birch/t_birch_leaves'
    result = {}
    result.update(_material('Birch_Bark_01', _stage(
        f'{TEX}/tree/birch/t_birch_bark/t_birch_bark_b.color.png',
        normal=f'{TEX}/tree/birch/t_birch_bark/t_birch_bark_nm.normal.png',
        rough=f'{TEX}/tree/birch/t_birch_bark/t_birch_bark_r.data.png',
        ao=f'{TEX}/tree/birch/t_birch_bark/t_birch_bark_ao.data.png',
        detail=_BARK_DETAIL, detailScale=[0.25, 2]), **_BARK))
    result.update(_material('Birch_Branch_01',
                            _leafset('tree/birch/t_birch_branch', 't_birch_branch'), alphaRef=60, **_BRANCH))
    result.update(_material('m_ind_birch_leaves_01', _stage(
        f'{TEX}/tree/birch/t_birch_leaves_ind/t_birch_leaves_ind_b.color.png',
        normal=f'{birch}/t_birch_leaves_nm.normal.png', rough=f'{birch}/t_birch_leaves_r.data.png',
        ao=f'{birch}/t_birch_leaves_ao.data.png', opacity=f'{birch}/t_birch_leaves_o.data.png',
        pixelSpecular=True), alphaRef=100, **_LEAF))
    result.update(_material('Oak_bark_01', _stage(
        f'{TEX}/tree/oak/t_oak_bark/t_oak_bark_b.color.png',
        normal=f'{TEX}/tree/oak/t_oak_bark/t_oak_bark_nm.normal.png',
        rough=f'{TEX}/tree/oak/t_oak_bark/t_oak_bark_r.data.png',
        ao=f'{TEX}/tree/oak/t_oak_bark/t_oak_bark_ao.data.png',
        detail=_BARK_DETAIL), **_BARK))
    result.update(_material('Oak_branch_01',
                            _leafset('tree/oak/t_oak_branch_01', 't_oak_branch'), alphaRef=50, **_BRANCH))
    result.update(_material('Oak_branch_02',
                            _leafset('tree/oak/t_oak_branch_02', 't_oak_branch_02'), alphaRef=75, **_BRANCH))
    for name, base in (('oak_leaves_01', 't_italy_oak_leaves/t_italy_oak_leaves_b.color.png'),
                       ('oak_leaves_02', 't_italy_oak_leaves_02/t_italy_oak_leaves_02_b.color.png'),
                       ('oak_leaves_03', 't_oak_leaves_03/t_oak_leaves_03_b.color.png')):
        result.update(_material(name, _leafset('tree/oak/t_oak_leaves_01', 't_oak_leaves',
                                               base=f'{TEX}/tree/oak/{base}'), alphaRef=110, **_LEAF))
    # The compiled .cdae the engine actually loads spells the oak and birch leaf
    # materials with an m_ prefix that the source .dae does not use.
    for name, base in (('m_oak_leaves_01', 't_italy_oak_leaves/t_italy_oak_leaves_b.color.png'),
                       ('m_ind_oak_leaves_01', 't_italy_oak_leaves/t_italy_oak_leaves_b.color.png'),
                       ('m_oak_leaves_02', 't_italy_oak_leaves_02/t_italy_oak_leaves_02_b.color.png'),
                       ('m_oak_leaves_03', 't_oak_leaves_03/t_oak_leaves_03_b.color.png')):
        result.update(_material(name, _leafset('tree/oak/t_oak_leaves_01', 't_oak_leaves',
                                               base=f'{TEX}/tree/oak/{base}'), alphaRef=110, **_LEAF))
    result.update(_material('beech_trunk', _stage(
        f'{TEX}/tree/beech/t_beech_trunk/t_beech_bark_b.color.png',
        normal=f'{TEX}/tree/beech/t_beech_trunk/t_beech_bark_nm.normal.png',
        rough=f'{TEX}/tree/beech/t_beech_trunk/t_beech_bark_r.data.png',
        ao=f'{TEX}/tree/beech/t_beech_trunk/t_beech_bark_ao.data.png',
        detail=_BARK_DETAIL), alphaRef=10, alphaTest=True, **_BARK))
    result.update(_material('beech_branch_01',
                            _leafset('tree/beech/t_beech_branch_01', 't_beech_branch'), alphaRef=75, **_BRANCH))
    result.update(_material('beech_leaves',
                            _leafset('tree/beech/t_beech_leaves', 't_beech_leaves'), alphaRef=105, **_LEAF))
    for name in ('beech_blocker', 'm_ind_beech_blocker'):
        result.update(_material(name, _leafset('tree/beech/t_beech_blocker', 't_beech_blocker'),
                                alphaRef=90, **dict(_LEAF, groundType='WOOD')))
    result.update(_material('m_ind_beech_leaves',
                            _leafset('tree/beech/t_beech_leaves', 't_beech_leaves'), alphaRef=105, **_LEAF))
    # Material names are matched case-insensitively, so only one birch-leaf spelling
    # is defined even though the meshes bind three different casings.
    result.update(_material('m_ind_birch_Leaves_01',
                            _leafset('tree/birch/t_birch_leaves', 't_birch_leaves'),
                            alphaRef=100, **_LEAF))
    result.update(_material('generibush_leaves',
                            _leafset('foliage/bush/t_generibush_leaves', 't_generic_bush'),
                            alphaRef=84, **dict(_LEAF, groundType='GRASS')))
    result.update(_material('Moss_01', _leafset('tree/oak/t_moss', 't_moss'),
                            alphaRef=139, **dict(_LEAF, groundType='GRASS')))
    for name in ('leaves_strong', 'leaves_thin'):
        # Collision/sound-only stand-ins; the stock definitions carry no texture either.
        result.update(_material(name, {}, groundType=name, annotation='NATURE'))
    # Blender colour-swatch material left on a few bush meshes; a flat leaf green.
    result.update(_material('ColorEffectR27G177B88-material',
                            {'baseColorFactor': [0.105, 0.694, 0.345, 1], 'roughnessFactor': 0.9},
                            annotation='NATURE'))
    return result


# Names bound inside the stock /assets foliage meshes. The game defines none of them
# globally; every stock level ships its own level-scoped copy, so identical names in
# two installed levels are expected and never override each other.
STOCK_MESH_MATERIALS = frozenset(tree_materials())


def surface_materials():
    """Road, ground and building materials plus the AI-only invisible road."""
    result = {}
    for name, (stage, tile, extra) in SURFACES.items():
        result.update(_material(name, stage, **extra))
    for name, (stage, tile) in {**FACADES, **ROOFS}.items():
        result.update(_material(name, stage, groundType='ASPHALT', annotation='BUILDINGS',
                                materialTag0='building'))
    return result


def uv_scales():
    """Material -> UV units per metre, so the tileable sets keep real-world size."""
    scales = {}
    for name, (_stage_, tile, _extra) in SURFACES.items():
        scales[name] = 1.0 / tile
    for name, (_stage_, tile) in {**FACADES, **ROOFS}.items():
        scales[name] = 1.0 / tile
    for name in PANEL_FACADES:
        scales[name] = 1.0 / PANEL_TILE
    for name, tile in DRAWN_FACADES.items():
        scales[name] = 1.0 / tile
    return scales
