#!/usr/bin/env python3
"""Reproducible native BeamNG level from an existing Akadem world snapshot.

Python standard library only. Never writes into the game installation/user profile.
Visible dressing (materials, vegetation, street furniture) references the game's
shared /art and /assets libraries; see beamng_assets.py.
"""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path
import random
import re
import shutil
import struct
import tempfile
import uuid
import time
import zipfile
import zlib
from shapely.geometry import Point, Polygon

from akadem_maps.adapters.beamng.beamng_assets import (DRAWN_FACADES, FOREST_ITEMS, LANDMARKS, PANEL_FACADES, PANEL_TILE, PARK_BUSHES,
                           PROP_SHAPES, ROOFS, STREET_TREES, WOOD_TREES, building_style,
                           forest_files, forest_item_data, surface_materials, tree_materials,
                           uv_scales)
from akadem_maps.adapters.beamng.beamng_geometry import Mesh, beam_point, features, optimization_mode, cross, dashed, normal, sub, triangulate
from akadem_maps.adapters.beamng.beamng_network import road_height_audit, road_network, signals, stable_id
from akadem_maps.adapters.beamng.beamng_terrain import GroundTerrain, write_substrate

ROOT = Path(__file__).resolve().parents[3]
VERSION = 2
SURFACE_CELL = 250.0         # spatial culling granularity; visible collision is triangular
# Raising the whole level was tried against the "car in the air" report and measured in
# game: it closes the last three surface probes but stops the engine drawing the ground,
# the asphalt and the lower half of every building. Default back to the snapshot datum;
# --vertical-offset still shifts everything together (see docs/DECISIONS.md).
VERTICAL_OFFSET = 0.0
LAMP_SPACING = 34.0          # metres between street lights on a lit road
LAMP_MIN_DRIVABILITY = 0.7   # residential and above are lit; service alleys are not
GUARDRAIL_SECTION = 2.42     # length of art/shapes/objects/guardrail1.dae
SIGN_PLATE_HEIGHT = 2.3      # tools/signs.py places sign records at the plate centre
SIGN_KINDS = ('oneway', 'speed_limit', 'give_way', 'priority_road')


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + '\n',
                    encoding='utf8')


def sha(path):
    with open(path, 'rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def seeded(*parts):
    return random.Random(int.from_bytes(hashlib.sha256('/'.join(map(str, parts)).encode('utf8')).digest()[:8], 'big'))


def scene_object(name, kind, parent='KyivGenerated', **values):
    return {'name': name, 'class': kind, '__parent': parent,
            'persistentId': str(uuid.uuid5(uuid.NAMESPACE_URL, 'akadem-beamng/' + name)), **values}


def write_items(path, objects):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(''.join(json.dumps(v, ensure_ascii=False, sort_keys=True, allow_nan=False) + '\n'
                            for v in sorted(objects, key=lambda v: v['name'])), encoding='utf8')


def png(path, width, height, pixels, alpha=False):
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff)
    stride = 4 if alpha else 3
    raw = b''.join(b'\0' + bytes(pixels[y * width * stride:(y + 1) * width * stride]) for y in range(height))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b'\x89PNG\r\n\x1a\n' +
                     chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 6 if alpha else 2, 0, 0, 0)) +
                     chunk(b'IDAT', zlib.compress(raw, 9)) + chunk(b'IEND', b''))


# --- procedural textures ----------------------------------------------------
# Road signs and signal lenses have no stock BeamNG equivalent (the game ships US and
# Italian sign sets, and its trafficlight_city1 head binds a material the install does
# not define), so these few small textures are authored here.

DIGITS = {  # 3x5 bitmap, one string per row: the posted limits plus the plate band
    '0': ('111', '101', '101', '101', '111'), '1': ('010', '110', '010', '010', '111'),
    '2': ('111', '001', '111', '100', '111'), '3': ('111', '001', '111', '001', '111'),
    '4': ('101', '101', '111', '001', '001'), '5': ('111', '100', '111', '001', '111'),
    '6': ('111', '100', '111', '101', '111'), '7': ('111', '001', '010', '010', '010'),
    '8': ('111', '101', '111', '101', '111'), '9': ('111', '101', '111', '001', '111'),
    'U': ('101', '101', '101', '101', '111'), 'A': ('111', '101', '111', '101', '101')}
SIZE = 128
RED = (200, 25, 30)
WHITE = (245, 245, 242)
YELLOW = (250, 195, 20)
BLUE = (20, 70, 150)
BACK = (150, 152, 150)


def _blank():
    return [[(0, 0, 0, 0)] * SIZE for _ in range(SIZE)]


def _fill(canvas, inside, color):
    for y in range(SIZE):
        for x in range(SIZE):
            if inside((x + .5) / SIZE * 2 - 1, 1 - (y + .5) / SIZE * 2):
                canvas[y][x] = color + (255,)


def _digits(canvas, text, color):
    scale = 9 if len(text) < 3 else 7
    width = len(text) * 4 * scale - scale
    x0 = (SIZE - width) // 2
    y0 = (SIZE - 5 * scale) // 2
    for i, ch in enumerate(text):
        for row, bits in enumerate(DIGITS[ch]):
            for col, bit in enumerate(bits):
                if bit == '1':
                    for dy in range(scale):
                        for dx in range(scale):
                            canvas[y0 + row * scale + dy][x0 + (i * 4 + col) * scale + dx] = color + (255,)


def _flat(canvas, color):
    result = _blank()
    for y in range(SIZE):
        for x in range(SIZE):
            if canvas[y][x][3]:
                result[y][x] = color + (255,)
    return result


def _emit(level, name, canvas):
    pixels = [v for row in canvas for px in row for v in px]
    png(level / f'art/kyiv/{name}.png', SIZE, SIZE, pixels, alpha=True)


def sign_faces():
    """kind/value -> (front canvas, shape id). Vienna Convention shapes, as used in Ukraine."""
    circle = lambda u, v: u * u + v * v <= .9 ** 2
    faces = {}

    disc = _blank()
    _fill(disc, circle, RED)
    _fill(disc, lambda u, v: u * u + v * v <= .72 ** 2, WHITE)
    for value in ('40', '50', '60', '70', '80'):
        canvas = [row[:] for row in disc]
        _digits(canvas, value, (25, 25, 25))
        faces[('speed_limit', value)] = (canvas, 'round')

    triangle = _blank()
    inside = lambda u, v: v <= .88 and v >= -.92 and abs(u) <= (.88 - v) * .58
    _fill(triangle, inside, RED)
    _fill(triangle, lambda u, v: v <= .62 and v >= -.66 and abs(u) <= (.62 - v) * .58, WHITE)
    faces[('give_way', None)] = (triangle, 'tri')

    diamond = _blank()
    _fill(diamond, lambda u, v: abs(u) + abs(v) <= .95, (30, 30, 30))
    _fill(diamond, lambda u, v: abs(u) + abs(v) <= .88, WHITE)
    _fill(diamond, lambda u, v: abs(u) + abs(v) <= .70, YELLOW)
    faces[('priority_road', None)] = (diamond, 'diamond')

    oneway = _blank()
    _fill(oneway, lambda u, v: abs(u) <= .95 and abs(v) <= .62, BLUE)
    _fill(oneway, lambda u, v: abs(v) <= .13 and -.55 <= u <= .35, WHITE)
    _fill(oneway, lambda u, v: .20 <= u <= .68 and abs(v) <= (.68 - u) * .85, WHITE)
    faces[('oneway', None)] = (oneway, 'wide')
    return faces


def sign_materials(level, level_id, used):
    """One material per distinct sign face plus one grey back per outline."""
    materials, plates = {}, {}
    faces = sign_faces()
    backs = {}
    for key in sorted(used, key=lambda k: (k[0], k[1] or '')):
        if key not in faces:
            continue
        canvas, shape = faces[key]
        name = 'kyiv_sign_' + key[0] + ('_' + key[1] if key[1] else '')
        _emit(level, name, canvas)
        materials.update(_sign_material(name, level_id))
        if shape not in backs:
            backs[shape] = 'kyiv_sign_back_' + shape
            _emit(level, backs[shape], _flat(canvas, BACK))
            materials.update(_sign_material(backs[shape], level_id))
        plates[key] = (name, backs[shape], shape)
    return materials, plates


def _sign_material(name, level_id):
    return {name: {'name': name, 'mapTo': name, 'class': 'Material', 'version': 1.5,
                   'Stages': [{'baseColorMap': f'/levels/{level_id}/art/kyiv/{name}.png',
                               'opacityMap': f'/levels/{level_id}/art/kyiv/{name}.png',
                               'roughnessFactor': 0.55}, {}, {}, {}],
                   'alphaTest': True, 'alphaRef': 96, 'translucentBlendOp': 'None',
                   'annotation': 'TRAFFIC_SIGNS', 'materialTag0': 'Miscellaneous'}}


def fixture_materials(level, level_id):
    """Signal lenses, signal housing, lane paint and the AI-only invisible road."""
    # D3D11 will not sample below 16×16; a 4×4 map becomes the orange NO TEXTURE.
    png(level / 'art/kyiv/invisible.png', 16, 16, [0] * (16 * 16 * 4), alpha=True)
    materials = {'kyiv_road_invisible': {
        'name': 'kyiv_road_invisible', 'mapTo': 'kyiv_road_invisible', 'class': 'Material', 'version': 1.5,
        'Stages': [{'baseColorMap': f'/levels/{level_id}/art/kyiv/invisible.png',
                    'opacityMap': f'/levels/{level_id}/art/kyiv/invisible.png'}, {}, {}, {}],
        'alphaTest': True, 'alphaRef': 200, 'castShadows': False,
        'annotation': 'STREET', 'materialTag0': 'RoadAndPath'}}
    materials['kyiv_paint'] = {
        'name': 'kyiv_paint', 'mapTo': 'kyiv_paint', 'class': 'Material', 'version': 1.5,
        'Stages': [{'baseColorFactor': [0.92, 0.92, 0.88, 1], 'roughnessFactor': 0.62,
                    'metallicFactor': 0}, {}, {}, {}],
        'groundType': 'ASPHALT', 'annotation': 'STREET', 'materialTag0': 'RoadAndPath'}
    materials['kyiv_signal_housing'] = {
        'name': 'kyiv_signal_housing', 'mapTo': 'kyiv_signal_housing', 'class': 'Material', 'version': 1.5,
        'Stages': [{'baseColorFactor': [0.09, 0.1, 0.1, 1], 'roughnessFactor': 0.6}, {}, {}, {}],
        'annotation': 'TRAFFIC_SIGNALS', 'materialTag0': 'Miscellaneous'}
    # The shader picks instanceColor, instanceColor1 or instanceColor2 by the red, green
    # and blue channel of colorPaletteMap, which is how core_trafficSignals drives three
    # lamps through one object. A flat single-channel palette per lens selects one slot.
    lenses = (('red', 0, (0.55, 0.05, 0.05)), ('amber', 1, (0.6, 0.35, 0.02)), ('green', 2, (0.05, 0.5, 0.15)))
    for name, slot, tint in lenses:
        channel = [0, 0, 0, 255]
        channel[slot] = 255
        png(level / f'art/kyiv/palette_{name}.png', 16, 16, channel * (16 * 16), alpha=True)
        key = 'kyiv_lens_' + name
        materials[key] = {
            'name': key, 'mapTo': key, 'class': 'Material', 'version': 1.5,
            'Stages': [{'baseColorFactor': list(tint) + [1], 'roughnessFactor': 0.25,
                        'colorPaletteMap': f'/levels/{level_id}/art/kyiv/palette_{name}.png',
                        'emissive': True, 'emissiveFactor': [1, 1, 1], 'emissiveIntensityNits': 4000,
                        'instanceEmissive': True}, {}, {}, {}],
            'annotation': 'TRAFFIC_SIGNALS', 'materialTag0': 'Miscellaneous'}
    return materials


# --- geometry ---------------------------------------------------------------

def building_mesh(building, facade, roof):
    mesh = Mesh()
    pts = [beam_point(p) for p in building['points']]
    floor = min(p[2] for p in pts)
    if building.get('local_style'):
        floor = float(building.get('floor_height', floor))
    top = floor + float(building.get('wall_height', building['height']) if building.get('local_style') else building['height'])
    base = float(building.get('base', 0))
    bottom = floor + base if base > 0 else floor - 1
    roof_faces = building.get('roof_triangles') if building.get('local_style') else None
    for tri in roof_faces or []:
        mesh.tri(roof, *(beam_point(p) for p in tri), up=True)
    for tri in building.get('roof_gables', []) if roof_faces else []:
        vertices = [beam_point(p) for p in tri]
        mesh.tri(facade, *vertices)
        mesh.tri(facade, *reversed(vertices))
    for a, b, c in triangulate([(p[0], p[1], top) for p in pts]):
        if not roof_faces:
            mesh.tri(roof, a, b, c, True)
        if base > 0:
            # Raised part (passage, S3DB min_height): close its underside.
            mesh.tri(facade, (a[0], a[1], bottom), (c[0], c[1], bottom), (b[0], b[1], bottom))
    if sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(pts, pts[1:] + pts[:1])) < 0:
        pts.reverse()
    for a, b in zip(pts, pts[1:] + pts[:1]):
        mesh.wall((a[0], a[1], floor), (b[0], b[1], floor), bottom - floor, top - floor, facade)
    return mesh


# Landcover kinds with their own surface (playtest 2026-10-06, notes 5 and 9); others are grass.
COVER_MATERIALS = {'water': 'kyiv_water', 'pitch': 'kyiv_pitch', 'track': 'kyiv_track'}


def tile_meshes(tile, sidewalks=True, ground=True):
    surface, paint = Mesh(), Mesh()
    for tri in tile.get('ground', []) if ground else []:
        surface.tri('kyiv_ground', *(beam_point(p) for p in tri), up=True)
    for tri in tile.get('parking', []):
        surface.tri('kyiv_asphalt_worn', *(beam_point(p) for p in tri), up=True)
    for green in tile.get('greens', []):
        material = COVER_MATERIALS.get(green.get('kind'), 'kyiv_grass')
        for tri in green['triangles']:
            surface.tri(material, *(beam_point(p) for p in tri), up=True)
    for road in tile.get('road_strips', []):
        if 'triangles' in road:
            for tri in road['triangles']:
                surface.tri('kyiv_asphalt', *(beam_point(p) for p in tri), up=True)
            if road.get('bridge'):
                from .beamng_geometry import ribbon
                left, right = ribbon([beam_point(p) for p in road['points']], road['width'])
                for a, b in zip(left, left[1:]):
                    surface.wall(b, a, -1.2, 0, 'kyiv_asphalt')
                for a, b in zip(right, right[1:]):
                    surface.wall(a, b, -1.2, 0, 'kyiv_asphalt')
        else:
            surface.strip([beam_point(p) for p in road['points']], road['width'], 'kyiv_asphalt',
                          sides=road.get('bridge', False), depth=1.2, centre_seam=True)
    for j in tile.get('junctions', []):
        for tri in j['triangles']:
            surface.tri('kyiv_asphalt', *(beam_point(p) for p in tri), up=True)
    for walk in tile.get('sidewalks', []) if sidewalks else []:
        surface.strip([beam_point(p) for p in walk['points']], walk['width'], 'kyiv_concrete', .035, True, .035)
    for area in tile.get('walkingareas', []) if sidewalks else []:
        for tri in area['triangles']:
            surface.tri('kyiv_concrete', *((p[0], -p[2], p[1] + .035) for p in tri), up=True)
        for ring in area.get('rings', []):
            points = [beam_point(p) for p in ring]
            for a, b in zip(points, points[1:] + points[:1]):
                surface.wall(a, b, 0, .035, 'kyiv_curb')
    for fence in tile.get('fences', []):
        # Setback/OSM fences, both faces (the Godot game draws them the same way).
        points = [beam_point(p) for p in fence['points']]
        for a, b in zip(points, points[1:]):
            surface.wall(a, b, -0.1, float(fence.get('height', 1.2)), 'kyiv_fac_block')
            surface.wall(b, a, -0.1, float(fence.get('height', 1.2)), 'kyiv_fac_block')
    for path in tile.get('paths', []):
        paint.strip([beam_point(p) for p in path['points']], path['width'], 'kyiv_gravel', .02)
    for mark in tile.get('markings', []):
        for part in dashed([beam_point(p) for p in mark['points']], mark.get('dash', [])):
            paint.strip(part, mark['width'], 'kyiv_paint', .025)
    return surface, paint


SIGNAL_HEAD_HEIGHT = 5.4     # head centre above the lane; its bottom clears 4.8 m
SIGNAL_ARM_RISE = 0.75       # arm above the head centre
SIGNAL_POST_GAP = 0.9        # post centre beyond the outer lane edge
SIGNAL_POST_SHIFTS = (0.0, 0.5, 1.0, 2.0, 3.0, 4.0, 6.0, 8.0, 12.0)
SIGNAL_SETBACK = 1.0         # heads and post sit this far before the stop line


def signal_mesh():
    """Three-lens head, no post: it hangs from a mast arm (signal_masts). Lenses face
    local -X; each lens carries its own instance colour slot. Origin at the head centre."""
    mesh = Mesh()
    mesh.box((0, 0, 0), (.20, .30, 1.10), 'kyiv_signal_housing')
    mesh.box((0, 0, .60), (.06, .06, .12), 'kyiv_metal')           # hanger to the arm
    for z, lens in ((.38, 'red'), (0.0, 'amber'), (-.38, 'green')):
        mesh.box((-.11, 0, z), (.05, .24, .24), 'kyiv_lens_' + lens)
        mesh.box((-.18, 0, z + .17), (.14, .28, .03), 'kyiv_signal_housing')  # visor
    return mesh


def beam_box(mesh, a, b, width, height, material):
    """Box of width x height (metres) whose axis runs from point a to point b."""
    ax = normal(sub(b, a))
    side = normal((-ax[1], ax[0], 0)) if abs(ax[2]) < .99 else (1.0, 0.0, 0.0)
    up = cross(ax, side)
    corners = [tuple(p[k] + side[k] * sx * width / 2 + up[k] * sz * height / 2 for k in range(3))
               for p in (a, b) for sx, sz in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
    for i, j, k, l in [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]:
        mesh.tri(material, corners[i], corners[j], corners[k])
        mesh.tri(material, corners[i], corners[k], corners[l])


def signal_masts(sig, lanes, corridors, counts):
    """Roadside post + arm per signalled approach; every lane's head hangs over its lane.

    One head per controlled lane used to stand 2.3 m right of that lane's centre, which
    on a multi-lane approach is the middle of the neighbouring lane. Now the post stands
    beyond the outer lane edge (checked against all pavement, shifted outward until clear)
    and heads hang at SIGNAL_HEAD_HEIGHT under an arm across the approach.
    Returns [(edge, post (x, y, z), arm top z, post clear, [(instance, head (x, y, z), dir)])]."""
    lane_of = {stable_id('kyiv_signal', lid): lid for lid in lanes}
    by_edge = defaultdict(list)
    for s in sig['instances']:
        lane_id = lane_of.get(s['name'])
        if lane_id is not None:
            by_edge[lanes[lane_id]['edge']].append((s, lane_id))
    index_of = lambda lid: int(lid.rsplit('_', 1)[1])
    result = []
    for edge, items in sorted(by_edge.items()):
        edge_lanes = sorted((l for l in lanes.values() if l['edge'] == edge), key=lambda l: index_of(l['id']))
        ends = {l['id']: [beam_point(p) for p in l['points'][-2:]] for l in edge_lanes}
        outer = edge_lanes[0]
        (px, py, _pz), (ex, ey, ez) = ends[outer['id']]
        length = math.hypot(ex - px, ey - py) or 1.0
        d = ((ex - px) / length, (ey - py) / length)
        right = (d[1], -d[0])
        stop = (ex - d[0] * SIGNAL_SETBACK, ey - d[1] * SIGNAL_SETBACK)
        post, clear = None, False
        for shift in SIGNAL_POST_SHIFTS:
            off = outer['width'] / 2 + SIGNAL_POST_GAP + shift
            spot = (stop[0] + right[0] * off, stop[1] + right[1] * off, ez)
            if not corridors.pavement.intersects(Point(spot[:2]).buffer(.12), ez-.65, ez+SIGNAL_HEAD_HEIGHT+.75, margin=.3):
                post, clear = spot, True
                break
        if post is None:
            # Opposite shoulder is a valid cantilever location too. Never leave
            # a visible pole on the road with its collision disabled.
            opposite=edge_lanes[-1]
            (_ax,_ay,_az),(lx,ly,lz)=ends[opposite['id']]
            for shift in SIGNAL_POST_SHIFTS:
                off=opposite['width']/2+SIGNAL_POST_GAP+shift
                spot=(lx-d[0]*SIGNAL_SETBACK-right[0]*off,
                      ly-d[1]*SIGNAL_SETBACK-right[1]*off,lz)
                if not corridors.pavement.intersects(Point(spot[:2]).buffer(.12),lz-.65,lz+SIGNAL_HEAD_HEIGHT+.75,margin=.3):
                    post,clear=spot,True
                    counts['signal_posts_opposite_shoulder']+=1
                    break
        if post is None:
            off = outer['width'] / 2 + SIGNAL_POST_GAP
            post = (stop[0] + right[0] * off, stop[1] + right[1] * off, ez)
            counts['signal_posts_on_pavement'] += 1
        heads = []
        for s, lane_id in items:
            lx, ly, lz = ends[lane_id][-1]
            # Project the lane's stop point onto the arm line (from the post towards -right).
            t = (lx - post[0]) * -right[0] + (ly - post[1]) * -right[1]
            heads.append((s, (post[0] - right[0] * t, post[1] - right[1] * t, lz + SIGNAL_HEAD_HEIGHT), d))
        top = max(h[1][2] for h in heads) + SIGNAL_ARM_RISE
        result.append((edge, post, top, clear, heads))
        counts['signal_masts'] += 1
    return result


def sign_mesh(front, back, shape):
    """Post plus one plate; the plate texture carries the outline through its alpha."""
    mesh = Mesh()
    width = 1.0 if shape == 'wide' else 0.72
    height = 0.62 if shape == 'wide' else 0.72
    centre = SIGN_PLATE_HEIGHT
    mesh.box((0, 0, centre / 2), (.07, .07, centre), 'kyiv_metal')
    for material, offset, flip in ((front, -.035, False), (back, .035, True)):
        corners = [(offset, -width / 2, centre - height / 2), (offset, width / 2, centre - height / 2),
                   (offset, width / 2, centre + height / 2), (offset, -width / 2, centre + height / 2)]
        uv = [(1, 1), (0, 1), (0, 0), (1, 0)] if flip else [(0, 1), (1, 1), (1, 0), (0, 0)]
        order = [(0, 1, 2), (0, 2, 3)] if flip else [(0, 2, 1), (0, 3, 2)]
        for i, j, k in order:
            mesh.tri(material, corners[i], corners[j], corners[k], uv=(uv[i], uv[j], uv[k]))
    return mesh


def spawn_sphere(name, record):
    """SpawnSphere 0.7 m above a lane point, facing along the lane (record angle, degrees)."""
    x, y, z = beam_point(record['position'])
    heading = math.radians(record['angle'])
    return scene_object(name, 'SpawnSphere', 'MissionGroup', position=[x, y, z + .7], radius=2,
                        dataBlock='SpawnSphereMarker',
                        rotationMatrix=[math.cos(heading), -math.sin(heading), 0,
                                        math.sin(heading), math.cos(heading), 0, 0, 0, 1])


def static_mesh(level, level_id, name, mesh, origin, collision=True, parent='KyivGenerated', *, optimization='balanced', collision_mesh=None, metrics=None, category='props'):
    draft = level / f'art/shapes/{name}.dae'
    stats = mesh.write(draft, origin, uv_scales=UV, optimization=optimization, collision=collision_mesh)
    # The game reuses its compiled .cdae while the .dae path is unchanged and the
    # cache is newer than the (fixed) ZIP stamp, so a re-exported level would show
    # stale geometry. A content digest in the file name makes changed meshes new paths.
    digest = hashlib.sha256(draft.read_bytes()).hexdigest()[:10]
    relative = f'art/shapes/{name}_{digest}.dae'
    draft.replace(level / relative)
    if metrics is not None:
        metrics.add(category, stats, collision)
    return scene_object(name, 'TSStatic', parent, shapeName=f'/levels/{level_id}/{relative}', position=list(origin),
                        rotationMatrix=[1, 0, 0, 0, 1, 0, 0, 0, 1], scale=[1, 1, 1],
                        collisionType=('Collision Mesh' if collision_mesh is not None else 'Visible Mesh Final') if collision else 'None', decalType='Visible Mesh',
                        meshCulling=True, useInstanceRenderData=True, canSaveDynamicFields=True)


def prop(name, shape, position, heading, parent='KyivProps', scale=1.0, collision='Visible Mesh Final'):
    cos, sin = math.cos(heading), math.sin(heading)
    return scene_object(name, 'TSStatic', parent, shapeName=shape, position=[round(v, 3) for v in position],
                        rotationMatrix=[cos, -sin, 0, sin, cos, 0, 0, 0, 1], scale=[scale] * 3,
                        collisionType=collision, decalType='None', useInstanceRenderData=True)


# --- scene dressing ---------------------------------------------------------

LAMP_CLEARANCE = 0.8                  # metres between a pole and any carriageway or junction
LAMP_SHIFTS = (0.0, 1.0, 2.0, 3.5)    # extra outward offsets tried before a pole is dropped


def street_lights(roads, corridors=None, counts=None):
    """Synthetic lighting: real Kyiv pole positions are not in the OSM snapshot.

    The navigation road only approximates the paved width (a paired road follows one
    carriageway; junction pavement is wider than the road), so each pole is checked
    against the real surface and moved outward, or dropped, until it stands clear."""
    counts = counts if counts is not None else Counter()
    result = []
    for road in roads:
        if road['drivability'] < LAMP_MIN_DRIVABILITY:
            continue
        nodes = road['nodes']
        width = max(n[3] for n in nodes)
        shape = PROP_SHAPES['highway_lamp' if width >= 14 else 'street_lamp']
        offset = width / 2 + 1.1
        travelled, index = LAMP_SPACING / 2, 0
        for (x0, y0, z0, _w0), (x1, y1, z1, _w1) in zip(nodes, nodes[1:]):
            length = math.hypot(x1 - x0, y1 - y0)
            if length < 1e-6:
                continue
            dx, dy = (x1 - x0) / length, (y1 - y0) / length
            while travelled < length:
                side = 1 if index % 2 else -1
                pz = z0 + (z1 - z0) * travelled / length
                spot = None
                for shift in LAMP_SHIFTS:
                    px = x0 + dx * travelled - dy * (offset + shift) * side
                    py = y0 + dy * travelled + dx * (offset + shift) * side
                    if corridors is None or not corridors.pavement.intersects(
                            Point(px,py).buffer(.35), pz-.8, pz+(13 if width>=14 else 8), margin=.3):
                        spot = (px, py, pz)
                        counts['street_lamps_shifted'] += shift > 0
                        break
                if spot is None:
                    counts['street_lamps_dropped_on_pavement'] += 1
                    if corridors:
                        corridors.audit.append({'kind':'lamp','source':road['name'],'position':[px,py,pz],
                                                'action':'omitted','reason':'pole envelope intersects pavement'})
                else:
                    # The mast arm of pole_light_single runs along +X; aim it at the road.
                    heading = math.atan2(-dx * side, dy * side)
                    result.append(prop(stable_id('kyiv_lamp', (road['name'], index)), shape, spot, heading))
                    if corridors and shift:
                        corridors.audit.append({'kind':'lamp','source':road['name'],'position':spot,
                                                'action':'shifted','shift_m':shift})
                travelled += LAMP_SPACING
                index += 1
            travelled -= length
    return result


# Fuel forecourts are not in the snapshot. The canopy is a synthetic slab placed
# beside the quick-travel point, which itself sits on the rightmost lane.
CANOPY_OFFSETS = (16.0, 22.0, 28.0)
CANOPY_ALONG = 18.0
CANOPY_ACROSS = 12.0
CANOPY_CLEARANCE = 5.0


def canopy_centre(position, angle, occupied, envelope=None):
    """Mesh-space centre of a fuel canopy, or None when every candidate is on pavement.

    `position` is a lane point in snapshot coordinates (east, up, south). The first
    try is to the right of travel, which is where a kerbside station sits.
    """
    east, north, up = beam_point(position)
    heading = math.radians(float(angle))
    right = (math.cos(heading), -math.sin(heading))
    for side in (1.0, -1.0):
        for dist in CANOPY_OFFSETS:
            centre = (east + right[0] * dist * side, north + right[1] * dist * side, up)
            # The inner edge has to clear the carriageway, not only the centre.
            inner = (east + right[0] * (dist - CANOPY_ACROSS / 2) * side,
                     north + right[1] * (dist - CANOPY_ACROSS / 2) * side, up)
            if not occupied(centre) and not occupied(inner) and (envelope is None or envelope(centre, angle)):
                return centre
    return None


def _oriented_box(mesh, centre, along, right, size, material):
    """Axis-aligned in (along, right, up), same winding as Mesh.box."""
    ax, ay = along
    rx, ry = right
    ha, hr, hz = (v / 2 for v in size)
    cx, cy, cz = centre

    def corner(sa, sr, sz):
        return (cx + ax * sa * ha + rx * sr * hr, cy + ay * sa * ha + ry * sr * hr, cz + sz * hz)

    pts = [corner(sa, sr, sz) for sa, sr, sz in
           ((-1, -1, -1), (1, -1, -1), (1, 1, -1), (-1, 1, -1),
            (-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1))]
    for i, j, k, l in [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]:
        mesh.tri(material, pts[i], pts[j], pts[k])
        mesh.tri(material, pts[i], pts[k], pts[l])


def canopy_mesh(centre, angle):
    """Flat deck on four posts. The deck underside is CANOPY_CLEARANCE metres up."""
    heading = math.radians(float(angle))
    along = (math.sin(heading), math.cos(heading))
    right = (math.cos(heading), -math.sin(heading))
    mesh = Mesh()
    deck = (centre[0], centre[1], centre[2] + CANOPY_CLEARANCE + 0.22)
    _oriented_box(mesh, deck, along, right, (CANOPY_ALONG, CANOPY_ACROSS, 0.45), 'kyiv_fac_cladding')
    for sa in (-1, 1):
        for sr in (-1, 1):
            foot = (centre[0] + along[0] * sa * (CANOPY_ALONG / 2 - 0.8) + right[0] * sr * (CANOPY_ACROSS / 2 - 0.6),
                    centre[1] + along[1] * sa * (CANOPY_ALONG / 2 - 0.8) + right[1] * sr * (CANOPY_ACROSS / 2 - 0.6),
                    centre[2] + CANOPY_CLEARANCE / 2)
            _oriented_box(mesh, foot, along, right, (0.35, 0.35, CANOPY_CLEARANCE), 'kyiv_metal')
    return mesh


def fuel_canopies(level, level_id, pois, occupied, counts, corridors=None, *, optimization='balanced', metrics=None):
    """One canopy per fuel quick-travel point that has a clear forecourt."""
    objects = []
    for poi in pois:
        if poi.get('kind') != 'fuel':
            continue
        def envelope(centre, angle):
            a=math.radians(angle)
            along,right=(math.sin(a),math.cos(a)),(math.cos(a),-math.sin(a))
            footprint=Polygon([(centre[0]+sa*CANOPY_ALONG/2*along[0]+sr*CANOPY_ACROSS/2*right[0],
                                centre[1]+sa*CANOPY_ALONG/2*along[1]+sr*CANOPY_ACROSS/2*right[1])
                               for sa,sr in ((-1,-1),(1,-1),(1,1),(-1,1))])
            return not corridors.pavement.intersects(footprint,centre[2]-.65,centre[2]+5.5,margin=.3)
        centre = canopy_centre(poi['position'], poi.get('angle', 0), occupied, envelope if corridors else None)
        if centre is None:
            counts['fuel_canopies_skipped'] += 1
            if corridors:
                corridors.audit.append({'kind':'canopy','source':poi['id'],'position':poi['position'],
                                        'action':'omitted','reason':'forecourt envelope overlaps pavement'})
            continue
        mesh = canopy_mesh(centre, poi.get('angle', 0))
        objects.append(static_mesh(level, level_id, stable_id('kyiv_canopy', poi['id']), mesh, centre,
                                   collision=False, parent='KyivProps', optimization=optimization, metrics=metrics))
        counts['fuel_canopies'] += 1
    return objects


def bridge_rails(tile, tileid):
    """Guardrails follow the snapshot's own bridge flag, not a guess about height."""
    from akadem_maps.adapters.beamng.beamng_geometry import ribbon
    result = []
    for number, road in enumerate(tile.get('road_strips', [])):
        if not road.get('bridge'):
            continue
        points = [beam_point(p) for p in road['points']]
        for side, edge in enumerate(ribbon(points, road['width'] + 0.6)):
            travelled, index = 0.0, 0
            for a, b in zip(edge, edge[1:]):
                length = math.dist(a[:2], b[:2])
                if length < 1e-6:
                    continue
                dx, dy = (b[0] - a[0]) / length, (b[1] - a[1]) / length
                while travelled + GUARDRAIL_SECTION <= length:
                    centre = travelled + GUARDRAIL_SECTION / 2
                    position = (a[0] + dx * centre, a[1] + dy * centre,
                                a[2] + (b[2] - a[2]) * centre / length + 0.9)
                    result.append(prop(stable_id('kyiv_rail', (tileid, number, side, index)),
                                       PROP_SHAPES['guardrail'], position, math.atan2(dy, dx)))
                    travelled += GUARDRAIL_SECTION
                    index += 1
                travelled -= length
    return result


def road_signs(level, level_id, tiles, plates, corridors=None, *, optimization='balanced', metrics=None):
    """Posted signs come straight from OSM tags in the snapshot."""
    meshes, objects, counts = {}, [], Counter()
    for tileid, tile in tiles:
        for number, sign in enumerate(tile.get('signs', [])):
            key = (sign['kind'], str(sign['value']) if sign.get('value') is not None else None)
            if key not in plates:
                counts['signs_unsupported'] += 1
                continue
            front, back, shape = plates[key]
            if front not in meshes:
                name = 'kyiv_signface_' + front.removeprefix('kyiv_sign_')
                stats = sign_mesh(front, back, shape).write(level / f'art/shapes/{name}.dae', (0, 0, 0), uv_scales=UV, optimization=optimization)
                if metrics is not None:
                    metrics.add('sign_assets', stats)
                meshes[front] = f'/levels/{level_id}/art/shapes/{name}.dae'
            x, y, z = beam_point(sign['position'])
            base = (x, y, z - SIGN_PLATE_HEIGHT)
            if corridors is not None:
                clear, shift = corridors.push_clear(base, steps=(0, .5, 1, 2, 3, 4, 6, 8), margin=.6)
                if clear is None:
                    counts['signs_unresolved'] += 1
                    corridors.audit.append({'kind': 'sign', 'position': base, 'source': sign,
                                            'action': 'unresolved', 'reason': 'no clear roadside'})
                    continue
                if shift:
                    corridors.audit.append({'kind': 'sign', 'position': base, 'new_position': clear,
                                            'source': sign, 'action': 'shifted'})
                    counts['signs_shifted'] += 1
                x, y, base_z = clear
                z = base_z + SIGN_PLATE_HEIGHT
            # signs.py already offsets to the right-hand kerb and records the plate
            # centre height; its yaw is a Godot rotation about +Y, which becomes a
            # BeamNG heading a quarter turn on. The plate faces local -X.
            objects.append(prop(stable_id('kyiv_sign', (tileid, number)), meshes[front],
                                (x, y, z - SIGN_PLATE_HEIGHT), float(sign['yaw']) + math.pi / 2))
            counts['signs'] += 1
    return objects, counts


def _triangle_points(triangles, count, rng):
    areas, total = [], 0.0
    for tri in triangles:
        a, b, c = (beam_point(p) for p in tri)
        area = abs((b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])) / 2
        total += area
        areas.append((total, a, b, c))
    if total <= 0:
        return
    for _ in range(count):
        target = rng.random() * total
        for cumulative, a, b, c in areas:
            if cumulative >= target:
                break
        u, v = rng.random(), rng.random()
        if u + v > 1:
            u, v = 1 - u, 1 - v
        yield tuple(a[k] + (b[k] - a[k]) * u + (c[k] - a[k]) * v for k in range(3))


def vegetation(tiles, dna=None):
    """Forest instances: mapped trees where OSM has them, filler inside green areas."""
    instances, counts = [], Counter()
    for tileid, tile in tiles:
        rng = seeded('trees', tileid)
        for point in tile.get('trees', []):
            x, y, z = beam_point(point)
            instances.append((rng.choice(STREET_TREES), x, y, z,
                              rng.uniform(0, math.tau), rng.uniform(0.8, 1.25)))
            counts['trees_mapped'] += 1
        if dna:
            counts['trees_osm'] += sum(t['provenance'] == 'osm' for t in tile.get('tree_records', []))
            counts['trees_synthetic_world'] += sum(t['provenance'] != 'osm' for t in tile.get('tree_records', []))
        for green in tile.get('greens', []):
            # Water, pitches and tracks carry no vegetation in any mode.
            if green['kind'] not in ('wood', 'green', 'orchard'):
                continue
            area = sum(abs((b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])) / 2
                       for a, b, c in ([beam_point(p) for p in tri] for tri in green['triangles']))
            wood = green.get('kind') == 'wood'
            fill = seeded('green', green['id'])
            trees = int(area / (70 if wood else 900))
            bushes = int(area / (45 if wood else 160))
            for point in _triangle_points(green['triangles'], min(trees, 400)*(3 if dna else 1), fill):
                if dna and fill.random() >= dna.density(point[0], -point[1])/3:
                    continue
                instances.append((fill.choice(WOOD_TREES if wood else STREET_TREES), *point,
                                  fill.uniform(0, math.tau), fill.uniform(0.75, 1.3)))
                counts['trees_filled'] += 1
            for point in _triangle_points(green['triangles'], min(bushes, 600)*(3 if dna else 1), fill):
                if dna and fill.random() >= dna.density(point[0], -point[1])/3:
                    continue
                instances.append((fill.choice(PARK_BUSHES), *point,
                                  fill.uniform(0, math.tau), fill.uniform(0.6, 1.2)))
                counts['bushes'] += 1
    return instances, counts


def visible_distance(bounds):
    """Keep the pilot's 4 km draw distance; large maps see a bit farther, not the whole bbox."""
    span = max(bounds[2] - bounds[0], bounds[3] - bounds[1])
    return int(max(4000, min(8000, span * 0.55)))


def sky_objects(distance=4000):
    """Overcast-bright Kyiv daylight: high visibility, soft fog, drifting cloud deck."""
    return [
        scene_object('theLevelInfo', 'LevelInfo', 'KyivSky', gravity=-9.81, visibleDistance=int(distance),
                     fogDensity=9e-05, fogAtmosphereHeight=700, fogColor=[0.62, 0.68, 0.76, 1],
                     canvasClearColor=[0.58, 0.66, 0.76, 255],
                     globalEnviromentMap='BNG_Sky_02_cubemap'),
        # Fixed mid-morning sun. A TimeOfDay object overrides elevation/azimuth and put the
        # sun on the horizon, which blew the whole district out to white.
        scene_object('sunsky', 'ScatterSky', 'KyivSky', azimuth=142, elevation=52,
                     skyBrightness=26, shadowDistance=min(1400, int(distance * 0.35)), shadowSoftness=0.2, texSize=2048,
                     castShadows=True, brightness=0.85, exposure=1.0, flareType='BNG_Sunflare_2',
                     flareScale=3, mieScattering=0.0018, rayleighScattering=0.0032,
                     sunScale=[1, 0.97, 0.92, 1], ambientScale=[0.36, 0.40, 0.48, 1],
                     colorize=[0.42, 0.55, 0.74, 1], colorizeAmount=0.3,
                     fogScale=[0.55, 0.66, 0.82, 1], nightFogColor=[0.09, 0.11, 0.16, 1],
                     nightColor=[0.07, 0.08, 0.12, 1], nightCubemap='BNG_Sky_02_cubemap',
                     moonEnabled=True, moonMat='Moon_Glow_Mat', moonScale=0.06,
                     occlusionScale=0.025, shadowDarkenColor=[0, 0, 0, 0]),
        scene_object('clouds', 'CloudLayer', 'KyivSky', position=[0, 0, 400], height=4.5,
                     coverage=0.42, exposure=0.5, windSpeed=1.2,
                     baseColor=[0.93, 0.94, 0.96, 1], texture='art/skies/clouds/clouds_normal_displacement.png',
                     Textures=[{'texScale': 0.55, 'texSpeed': 0.0035, 'texDirection': [0.3, 0.1]},
                               {'texScale': 0.75, 'texSpeed': 0.005, 'texDirection': [0.2, 0.9]},
                               {'texScale': 0.95, 'texSpeed': 0.0065, 'texDirection': [0.1, 0.4]}]),
    ]


# --- panel facades ----------------------------------------------------------
FACADE_PX = 256          # 6 m square: two 3 m storeys by two 3 m bays


def _facade_pixels(base, glass, style, key):
    """One repeat of a Kyiv large-panel wall: panel joints, windows, balconies."""
    rng = seeded('facade', key)
    px = FACADE_PX // 2                       # one storey / one bay
    metre = FACADE_PX / PANEL_TILE
    rows = []
    for y in range(FACADE_PX):
        floor_y = y % px                      # 0 at the storey's slab line
        row = []
        for x in range(FACADE_PX):
            bay_x = x % px
            grain = 1 + (((x * 31 + y * 17 + x * y * 7) % 19) - 9) / 190
            colour = tuple(c * grain for c in base)
            if floor_y < 2 or bay_x < 2:      # cast joint between panels
                colour = tuple(c * 0.82 for c in base)
            balcony = style == 'balcony' and (x // px) % 2 == 1
            left, right = px * 0.18, px * 0.82
            top, bottom = px * 0.22, px * 0.72
            if balcony:
                left, right = px * 0.08, px * 0.92
            if left <= bay_x <= right and top <= floor_y <= bottom:
                edge = min(bay_x - left, right - bay_x, floor_y - top, bottom - floor_y)
                if edge < 0.07 * px:
                    colour = tuple(min(1.0, c * 1.22 + 0.10) for c in base)   # frame
                else:
                    shade = 0.75 + 0.5 * rng.random()
                    colour = tuple(min(1.0, c * shade) for c in glass)
                    if bay_x - left > (right - left) / 2 - 1 and bay_x - left < (right - left) / 2 + 1:
                        colour = tuple(min(1.0, c * 1.3 + 0.08) for c in glass)  # mullion
            elif balcony and bottom < floor_y <= bottom + 0.06 * px:
                colour = tuple(c * 0.9 for c in base)                          # balcony slab
            row.extend(max(0, min(255, round(c * 255))) for c in colour)
        rows.append(row)
    # A darker weathering streak below each balcony slab, the way these blocks age.
    for bay in range(2):
        if style != 'balcony' or bay % 2 == 0:
            continue
        for storey in range(2):
            y0 = storey * px + int(0.78 * px)
            for y in range(y0, min(FACADE_PX, y0 + int(0.5 * metre))):
                fade = 1 - (y - y0) / max(1, 0.5 * metre)
                for x in range(bay * px + int(0.1 * px), bay * px + int(0.9 * px)):
                    i = x * 3
                    for c in range(3):
                        rows[y][i + c] = round(rows[y][i + c] * (1 - 0.18 * fade))
    return [v for row in rows for v in row]


def _grid_pixels(size, bay, mullion, frame, glass):
    """Repeating glazed grid. Row 0 is the top of the image, matching the panel skins."""
    pixels = []
    for y in range(size):
        for x in range(size):
            if (x % bay) < mullion or (y % bay) < mullion:
                colour = frame
            else:
                pane = (x // bay) + 3 * (y // bay)
                shade = 0.90 + (pane % 5) * 0.025
                colour = tuple(min(255, round(c * shade)) for c in glass)
            pixels.extend(colour)
    return pixels


def _cladding_pixels(size):
    """Pale horizontal panels with a glazed band along the bottom of the image."""
    glass_from = int(size * 0.62)
    panel = (214, 210, 200)
    joint = (168, 164, 154)
    glass = (96, 114, 128)
    frame = (232, 230, 224)
    pixels = []
    for y in range(size):
        for x in range(size):
            if y >= glass_from:
                edge = y < glass_from + 3 or (x % 48) < 3
                colour = frame if edge else glass
            elif y % 32 < 2:
                colour = joint
            else:
                grain = 1 + (((x * 13 + y * 7) % 11) - 5) / 180
                colour = tuple(max(0, min(255, round(c * grain))) for c in panel)
            pixels.extend(colour)
    return pixels


def _drawn_facade_pixels(name):
    if name == 'kyiv_fac_curtain':
        return _grid_pixels(FACADE_PX, 64, 4, (214, 216, 218), (118, 138, 154))
    if name == 'kyiv_fac_cladding':
        return _cladding_pixels(FACADE_PX)
    raise KeyError(name)


def panel_facade_materials(level, level_id):
    """Author the windowed wall textures the shared BeamNG sets do not provide."""
    materials = {}
    for name, (base, glass, style) in PANEL_FACADES.items():
        png(level / f'art/kyiv/{name}.png', FACADE_PX, FACADE_PX,
            _facade_pixels(base, glass, style, name))
        materials[name] = {
            'name': name, 'mapTo': name, 'class': 'Material', 'version': 1.5,
            'Stages': [{'baseColorMap': f'/levels/{level_id}/art/kyiv/{name}.png',
                        'roughnessFactor': 0.78, 'metallicFactor': 0.0}, {}, {}, {}],
            'groundType': 'ASPHALT', 'annotation': 'BUILDINGS', 'materialTag0': 'building'}
    for name in DRAWN_FACADES:
        # The cooker only picks up base colour when the file ends in .color.png.
        png(level / f'art/kyiv/{name}.color.png', FACADE_PX, FACADE_PX, _drawn_facade_pixels(name))
        materials[name] = {
            'name': name, 'mapTo': name, 'class': 'Material', 'version': 1.5,
            'Stages': [{'baseColorMap': f'/levels/{level_id}/art/kyiv/{name}.color.png',
                        'roughnessFactor': 0.72, 'metallicFactor': 0.0}, {}, {}, {}],
            'groundType': 'ASPHALT', 'annotation': 'BUILDINGS', 'materialTag0': 'building'}
    return materials


# Ukrainian plates: white ground, blue EU-style band, AA #### XX for Kyiv city. The
# game falls back to its US default when a level supplies none, so traffic in
# Академмістечко would otherwise carry American plates.
PLATE_LETTERS = 'ABCEHIKMOPTX'   # the Latin shapes shared with Cyrillic, as Ukraine uses
PLATE_BAND = (18, 62, 140)


def _plate_background(width, height, band):
    pixels = []
    for y in range(height):
        for x in range(width):
            edge = x < 4 or y < 4 or x >= width - 4 or y >= height - 4
            pixels.extend((20, 22, 26) if edge else (PLATE_BAND if x < band else (250, 250, 248)))
    glyph = max(2, band // 18)
    top = (height - 5 * glyph) // 2
    for index, letter in enumerate('UA'):
        left = (band - (2 * 4 - 1) * glyph) // 2 + index * 4 * glyph
        for row, bits in enumerate(DIGITS[letter]):
            for col, bit in enumerate(bits):
                if bit == '1':
                    for dy in range(glyph):
                        for dx in range(glyph):
                            i = ((top + row * glyph + dy) * width + left + col * glyph + dx) * 3
                            pixels[i:i + 3] = [245, 245, 245]
    return pixels


def license_plate(stage, level_id):
    """Level-scoped plate design; BeamNG picks it up by level name on its own."""
    folder = stage / 'vehicles/common/licenseplates' / level_id
    formats = {}
    for key, width, height, band, size in (('52-11', 1024, 196, 120, 150), ('30-15', 512, 256, 76, 130)):
        name = f'licenseplate-{key}_d.png'
        png(folder / name, width, height, _plate_background(width, height, band))
        formats[key] = {
            'background': f'vehicles/common/licenseplates/{level_id}/{name}',
            'normal': 'vehicles/common/licenseplates/default/licenseplate-default_n.png',
            'emboss': 3, 'size': [width, height],
            'root': {'name': 'root', 'style': {'alignItems': 'center', 'justifyContent': 'center'},
                     'children': [{'name': 'plate', 'type': 'text', 'text': '{plate}', 'font': 'plate',
                                   'color': '#101014', 'fit': 'shrink', 'fontSize': size,
                                   'letterSpacing': 4,
                                   'style': {'position': 'absolute', 'left': band + 24,
                                             'top': (height - size) // 2,
                                             'width': width - band - 48, 'height': size}}]}}
    write_json(folder / 'licensePlate-default.sktemplate.json', {
        'name': 'Ukraine (Kyiv)', 'type': 'licenseplate', 'version': 3, 'format': formats,
        'vars': {'plate': {'type': 'string', 'minLength': 0, 'maxLength': 8,
                           'charsets': {'u': PLATE_LETTERS, 'd': '0123456789'},
                           'default': 'AA{d}{d}{d}{d}{u}{u}'}}})


PREVIEW = 512


def preview_image(tiles, lane_points, bounds):
    """Level-select thumbnail: green space, footprints and the drivable network."""
    scale = (PREVIEW - 2) / max(bounds[2] - bounds[0], bounds[3] - bounds[1])
    ox = (PREVIEW - (bounds[2] - bounds[0]) * scale) / 2
    oy = (PREVIEW - (bounds[3] - bounds[1]) * scale) / 2

    def to_pixel(point):
        return (int(ox + (point[0] - bounds[0]) * scale),
                PREVIEW - 1 - int(oy + (point[1] - bounds[1]) * scale))

    canvas = [[(38, 44, 38)] * PREVIEW for _ in range(PREVIEW)]

    def fill(triangle, color):
        pixels = [to_pixel(beam_point(p)) for p in triangle]
        top, bottom = min(p[1] for p in pixels), max(p[1] for p in pixels)
        for y in range(max(0, top), min(PREVIEW, bottom + 1)):
            crossings = []
            for (x0, y0), (x1, y1) in zip(pixels, pixels[1:] + pixels[:1]):
                if (y0 <= y < y1) or (y1 <= y < y0):
                    crossings.append(x0 + (x1 - x0) * (y - y0) / (y1 - y0))
            crossings.sort()
            for start, end in zip(crossings[::2], crossings[1::2]):
                for x in range(max(0, int(start)), min(PREVIEW, int(end) + 1)):
                    canvas[y][x] = color

    for _tileid, tile in tiles:
        for green in tile.get('greens', []):
            color = {'wood': (44, 78, 40), 'water': (62, 98, 118), 'pitch': (70, 120, 56),
                     'track': (150, 76, 60)}.get(green.get('kind'), (56, 86, 48))
            for triangle in green['triangles']:
                fill(triangle, color)
    for _tileid, tile in tiles:
        for building in tile.get('buildings', []):
            shade = 96 + min(60, int(float(building.get('height') or 9)))
            fill(building['points'], (shade, shade - 6, shade - 14))
    for point in lane_points:
        x, y = to_pixel(point)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                if 0 <= x + dx < PREVIEW and 0 <= y + dy < PREVIEW:
                    canvas[y + dy][x + dx] = (214, 206, 186)
    return [v for row in canvas for px in row for v in px]


UV = {}


def apply_overrides(objects, document, baseline):
    objects = {v['name']: v for v in objects}
    conflicts = []
    for name, change in document.get('objects', {}).items():
        if objects.get(name) != change.get('base'):
            conflicts.append(name)
        edited = change.get('edited')
        if edited is None:
            objects.pop(name, None)
        else:
            # Editor corrections from old exports used the unshifted datum.
            import copy
            edited = copy.deepcopy(edited)
            shift_object(edited, (baseline or {}).get('vertical_offset', 0)-document.get('vertical_offset', 0))
            objects[name] = edited
    return list(objects.values()), conflicts


def capture_edits(level, output, baseline=None):
    """Diff a level saved by the World Editor against the baseline of its export.

    Public exports keep the baseline beside the ZIP in ``reports/``; older exports kept
    it inside the level folder.
    """
    baseline = read_json(baseline or level / 'kyiv-baseline.json')
    originals = {v['name']: v for v in baseline['objects']}
    current = {}
    for file in sorted((level / 'main').rglob('items.level.json')):
        for line in file.read_text(encoding='utf-8-sig').splitlines():
            if line.strip():
                obj = json.loads(line)
                if obj.get('name'):
                    current[obj['name']] = obj
    changes = {}
    for name in sorted(set(originals) | set(current)):
        if originals.get(name) != current.get(name):
            changes[name] = {'base': originals.get(name), 'edited': current.get(name)}
    write_json(output, {'version': VERSION, 'level_id': baseline['level_id'],
                        'vertical_offset': baseline.get('vertical_offset', 0), 'objects': changes})
    return len(changes)


def shift_object(obj, dz):
    if not dz:
        return
    if 'position' in obj:
        obj['position'] = [*obj['position'][:2], obj['position'][2]+dz]
    if obj.get('class') == 'DecalRoad':
        obj['nodes'] = [[n[0], n[1], n[2]+dz, *n[3:]] for n in obj['nodes']]
    # fogAtmosphereHeight is an absolute world height, not a height above the
    # ground. Left at its unshifted value the raised district sits deep inside the
    # fog column and the whole level renders as flat haze a few metres out.
    if obj.get('class') == 'LevelInfo' and 'fogAtmosphereHeight' in obj:
        obj['fogAtmosphereHeight'] = obj['fogAtmosphereHeight']+dz


# Newer than any shape cache written while the 2026-09-23 ring builds were loaded.
# A stamp older than the cached .cdae makes the game keep the previous mesh.
ZIP_STAMP = (2026, 9, 24, 12, 0, 0)


def deterministic_zip(root, path):
    """PNG bytes are stored uncompressed.

    BeamNG mis-reads a deflate entry whose compressed size equals the file size:
    the stream no longer starts with the PNG signature, ``readPNG`` fails, and the
    engine draws the orange NO TEXTURE stand-in. The 4×4 invisible road and the
    signal palettes were exactly those entries.
    """
    with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for file in sorted(root.rglob('*')):
            if not file.is_file():
                continue
            info = zipfile.ZipInfo(file.relative_to(root).as_posix(), ZIP_STAMP)
            info.compress_type = zipfile.ZIP_STORED if file.suffix.lower() == '.png' else zipfile.ZIP_DEFLATED
            z.writestr(info, file.read_bytes())


GROUPS = ('KyivGenerated', 'KyivNavigation', 'KyivProps', 'KyivSignals', 'KyivSky', 'KyivManual')


def export_map(mid, output, level_id=None, overrides=None, source_root=ROOT, lift=None, *, world_dir=None, namespace=False, package_zip=True, emit=None, optimization='balanced'):
    from .optimization import ExportMetrics, simplify_ground
    optimization = optimization_mode(optimization)
    feature = features(optimization)
    metrics = ExportMetrics(optimization)
    def stage_event(stage):
        metrics.enter(stage)
        if emit:
            emit('stage', stage=stage)
    def write_static(*args, **kwargs):
        return static_mesh(*args, **kwargs, optimization=optimization, metrics=metrics)
    stage_event('prepare')
    lift = VERTICAL_OFFSET if lift is None else float(lift)
    if not re.fullmatch('[a-z0-9_]+', mid):
        hint = (' (that looks like a folder: export a world folder with --world)'
                if any(c in str(mid) for c in '/\\.:') else '')
        raise ValueError(f'Invalid map id {mid!r}: use lowercase letters, digits and _ only{hint}')
    source_root = Path(world_dir) if world_dir else Path(source_root)
    config_file=source_root/'config.json' if world_dir else source_root/'config'/f'{mid}.json'
    config=read_json(config_file) if config_file.exists() else {}
    level_id = level_id or config.get('level_id') or ('kyiv_akadem' if mid == 'akadem' else 'kyiv_' + mid)
    if not re.fullmatch('[a-z0-9_]+', level_id):
        raise ValueError(f'Invalid level id {level_id!r}: use lowercase letters, digits and _ only, e.g. my_level')
    source = source_root if world_dir else source_root / 'game/data' / mid
    build = source_root if world_dir else source_root / 'data/build' / mid
    index = read_json(source / 'index.json')
    net = build / 'network.net.xml'
    if sha(net) != index['network_sha256']:
        raise ValueError('SUMO network hash differs from world index; regenerate the snapshot')
    output = Path(output).resolve()
    if output.exists():
        raise FileExistsError(f'Output already exists: {output}. Use a new build directory; editor work is never overwritten.')
    output.parent.mkdir(parents=True, exist_ok=True)
    # Python 3.13+ mkdtemp uses a private Windows ACL. After rename that would
    # make the finished mod unreadable by the desktop/game account.
    stage = output.parent / ('beamng-stage-' + uuid.uuid4().hex)
    stage.mkdir()
    try:
        level = stage / 'levels' / level_id
        level.mkdir(parents=True)
        UV.clear()
        UV.update(uv_scales())
        objects = [scene_object('MissionGroup', 'SimGroup', parent='')]
        objects[0].pop('__parent')
        objects += [scene_object(name, 'SimGroup', 'MissionGroup') for name in GROUPS]
        spawn_points = [{'objectname': 'spawn_default', 'name': 'Start'}]
        objects.append(spawn_sphere('spawn_default', index['spawn']))
        # Quick-travel points (tools/pois.py): level start menu and the freeroam big map.
        # core/levels.lua labels big-map markers with translationId; an unknown key is
        # shown as written, so it carries the literal title.
        for poi in index.get('pois', []):
            objects.append(spawn_sphere('spawn_' + poi['id'], poi))
            spawn_points.append({'objectname': 'spawn_' + poi['id'], 'name': poi['title'],
                                 'translationId': poi['title']})

        stage_event('geometry')
        nav_tiles = ((tid, read_json(source/'tiles'/f'{tid}.json')) for tid in sorted(index['tiles'])) if index.get('road_elevation') else None
        roads, lanes, location, roadstats, _elevation = road_network(index, net, tiles=nav_tiles)
        objects += roads
        sig, sigaudit = signals(index, lanes)
        write_json(level / 'map.json', {'segments': {}})
        write_json(level / 'signals.json', sig)
        counts = Counter(roadstats)
        sources = {str(net.relative_to(source_root)): sha(net),
                   str((source / 'index.json').relative_to(source_root)): sha(source / 'index.json')}
        # Cached focus snapshots contain surrounding OSM scenery well outside the road bbox.
        # Keep whole source tiles intersecting the drivable network plus 150 m scenery buffer.
        points = [beam_point(p) for lane in lanes.values() for p in lane['points']]
        bounds = [min(p[0] for p in points) - 150, min(p[1] for p in points) - 150,
                  max(p[0] for p in points) + 150, max(p[1] for p in points) + 150]
        size = index['tile_size']
        objects += sky_objects(visible_distance(bounds))
        # 'terrain': the ground heightmap replaces both the ground meshes and the low substrate.
        terrain = GroundTerrain(bounds) if 'terrain' in feature else None
        if terrain is None:
            substrate = write_substrate(level,level_id,bounds,min(p[2] for p in points))
            substrate_class = substrate.pop('class_')
            substrate_name = substrate.pop('name')
            objects.append(scene_object(substrate_name,substrate_class,'KyivGenerated',**substrate))
        errors, building_parts, tiles = [], defaultdict(list), []
        tile_ids = sorted(index['tiles'].items())
        print(f'export {mid}: {len(roads)} DecalRoad, {len(tile_ids)} source tiles', flush=True)
        for index_n, (tileid, (tx, tz)) in enumerate(tile_ids, 1):
            x0, y0 = tx * size, -(tz + 1) * size
            if x0 > bounds[2] or x0 + size < bounds[0] or y0 > bounds[3] or y0 + size < bounds[1]:
                continue
            tilefile = source / 'tiles' / f'{tileid}.json'
            tile = read_json(tilefile)
            sources[str(tilefile.relative_to(source_root))] = sha(tilefile)
            tiles.append((tileid, tile))
            origin = (x0 + size / 2, y0 + size / 2, 0)
            surface, paint = tile_meshes(tile, sidewalks=False, ground=optimization == 'legacy')
            if terrain is not None:
                terrain.add_ground(beam_point(p) for t in tile.get('ground', []) for p in t)
                terrain.add_cap(p for faces in surface.faces.values() for t in faces for p in t)
            elif optimization != 'legacy':
                ground_faces, ground_audit = simplify_ground([tuple(beam_point(p) for p in t) for t in tile.get('ground', [])])
                counts['ground_input_triangles'] += ground_audit['input_triangles']
                counts['ground_output_triangles'] += ground_audit['output_triangles']
                ground_mesh = Mesh()
                for tri in ground_faces:
                    ground_mesh.tri('kyiv_ground', *tri, up=True)
                for (ix, iy), part in sorted(ground_mesh.chunks(SURFACE_CELL).items()):
                    cell_origin = ((ix+.5)*SURFACE_CELL, (iy+.5)*SURFACE_CELL, 0.)
                    objects.append(write_static(level, level_id, stable_id('kyiv_ground', (tileid,ix,iy)), part, cell_origin, category='ground'))
                    counts['surface_triangles'] += part.count
                    counts['surface_chunks'] += 1
                del ground_faces, ground_mesh
            if paint.count:
                objects.append(write_static(level, level_id, stable_id('kyiv_paint', tileid),
                                           paint, origin, False, category='markings'))
                counts['paint_triangles'] += paint.count
                counts['degenerate_removed'] += paint.dropped
            if surface.count:
                for (ix, iy), part in sorted(surface.chunks(SURFACE_CELL).items()):
                    cell_origin = ((ix + 0.5) * SURFACE_CELL, (iy + 0.5) * SURFACE_CELL, 0.0)
                    objects.append(write_static(level, level_id, stable_id('kyiv_surface', (tileid, ix, iy)),
                                               part, cell_origin, True, category='surfaces'))
                    counts['surface_triangles'] += part.count
                    counts['surface_chunks'] += 1
                counts['degenerate_removed'] += surface.dropped
            for b in tile.get('buildings', []):
                building_parts[b['id']].append(b)
            counts['tiles'] += 1
            if index_n % 25 == 0 or index_n == len(tile_ids):
                print(f'  tiles {index_n}/{len(tile_ids)} kept={counts.get("tiles", 0)}', flush=True)
        from akadem_maps.adapters.beamng.beamng_corridors import bridge_rail_objects, Corridors
        from akadem_maps.adapters.beamng.beamng_curbs import build_sidewalks
        corridors = Corridors(tiles)
        stage_event('sidewalks')
        print('  continuous low sidewalks', flush=True)
        # compact kerbs have no bevel, so the visible mesh is the collider.
        walkcollision = Mesh() if optimization != 'legacy' and 'kerbs' not in feature else None
        walkmesh, curb_audit = build_sidewalks(tiles, corridors.pavement, optimization=optimization, collision=walkcollision)
        if terrain is not None:
            started = time.perf_counter()
            terrain.add_cap(p for faces in walkmesh.faces.values() for t in faces for p in t)
            terrain_object, terrain_stats = terrain.write(level, level_id)
            terrain_stats['seconds'] = round(time.perf_counter()-started, 2)
            del terrain
            metrics.add('terrain', {'triangles': 0, 'vertices': 0, 'bytes': terrain_stats['bytes']}, False)
            objects.append(scene_object(terrain_object.pop('name'), terrain_object.pop('class_'), 'KyivGenerated', **terrain_object))
            counts['terrain_cells'] = terrain_stats['size']**2
            print(f'  ground terrain {terrain_stats}', flush=True)
        collision_parts = walkcollision.chunks(SURFACE_CELL) if walkcollision is not None else {}
        del walkcollision
        # A collision triangle can have a different centroid than its visual
        # counterpart: attach every collision bucket, including collision-only cells.
        walk_parts = walkmesh.chunks(SURFACE_CELL)
        for key in collision_parts:
            walk_parts.setdefault(key, Mesh())
        for ix, iy in sorted(walk_parts):
            part = walk_parts.pop((ix,iy))
            cell_origin = ((ix+.5)*SURFACE_CELL, (iy+.5)*SURFACE_CELL, 0)
            collider = collision_parts.pop((ix,iy), None)
            # Visual-only cells (bevel slivers whose colliders fall next door) get no collision.
            objects.append(write_static(level, level_id, stable_id('kyiv_walk', (ix, iy)),
                                       part, cell_origin, optimization == 'legacy' or 'kerbs' in feature or collider is not None,
                                       collision_mesh=collider, category='sidewalks'))
            counts['surface_triangles'] += part.count
            counts['surface_chunks'] += 1
        del walkmesh
        objects += bridge_rail_objects(tiles, prop, PROP_SHAPES['guardrail'], stable_id)
        counts['guardrails'] = sum(1 for o in objects if o['name'].startswith('kyiv_rail_'))
        height_audit = road_height_audit(roads, tiles)
        print(f'  height audit nodes={height_audit["nodes"]} over_50cm={height_audit["over_50cm"]} '
              f'over_2m={height_audit["over_2m"]} max={height_audit["max_abs_m"]}m', flush=True)

        stage_event('buildings')
        building_items = sorted(building_parts.items())
        print(f'  buildings {len(building_items)}', flush=True)
        # Whole buildings merge into 250 m cells by footprint centre: thousands of
        # per-building TSStatics dominated level load time.
        building_cells = defaultdict(Mesh)
        dna_styles, roof_colours = {}, {}
        from akadem_maps.adapters.beamng.beamng_placement import audit_building
        for index_n, (bid, parts) in enumerate(building_items, 1):
            facade, roof = building_style(parts[0])
            if parts[0].get('local_style'):
                dna_styles[facade] = parts[0]['local_style']
                UV[facade] = 1/6
            if str(parts[0].get('id')) in LANDMARKS:
                counts['landmark_buildings'] += 1
            pts = [beam_point(p) for b in parts for p in b['points']]
            cell = building_cells[(math.floor(sum(p[0] for p in pts) / len(pts) / SURFACE_CELL),
                                   math.floor(sum(p[1] for p in pts) / len(pts) / SURFACE_CELL))]
            for b in parts:
                audit_building(b, corridors.pavement, corridors.audit)
                part_roof = roof
                if b.get('roof_color'):
                    # Observed OSM roof:colour: one shared material per colour, never per building.
                    part_roof = 'kyiv_roof_c_' + b['roof_color'][1:]
                    roof_colours[part_roof] = b['roof_color']
                    UV[part_roof] = 1/3
                try:
                    part = building_mesh(b, facade, part_roof)
                except ValueError as e:
                    errors.append({'building': b['id'], 'error': str(e)})
                    continue
                for mat, faces in part.faces.items():
                    cell.faces[mat].extend(faces)
                    cell.uvs[mat].extend(part.uvs[mat])
            counts['buildings'] += 1
            counts['facade_' + facade.removeprefix('kyiv_fac_')] += 1
            if index_n % 500 == 0 or index_n == len(building_items):
                print(f'  buildings {index_n}/{len(building_items)}', flush=True)
        for ix, iy in sorted(building_cells):
            mesh = building_cells.pop((ix,iy))
            if not mesh.count:
                continue
            cell_origin = ((ix + 0.5) * SURFACE_CELL, (iy + 0.5) * SURFACE_CELL, 0.0)
            objects.append(write_static(level, level_id, stable_id('kyiv_buildings', (ix, iy)), mesh, cell_origin, category='buildings'))
            counts['building_chunks'] += 1

        del building_parts, building_items, building_cells
        stage_event('dressing')
        materials = {**surface_materials(), **tree_materials(), **fixture_materials(level, level_id),
                     **panel_facade_materials(level, level_id)}
        from akadem_maps.core.local_dna import facade_pixels, Field
        for name, style in sorted(dna_styles.items()):
            png(level/f'art/kyiv/{name}.color.png', 256, 256, facade_pixels(style))
            materials[name] = {'name': name, 'mapTo': name, 'class': 'Material', 'version': 1.5,
                               'Stages': [{'baseColorMap': f'/levels/{level_id}/art/kyiv/{name}.color.png',
                                           'roughnessFactor': .78}, {}, {}, {}],
                               'annotation': 'BUILDINGS', 'materialTag0': 'building'}
        metal_roof = ROOFS['kyiv_roof_metal'][0]
        for name, hexa in sorted(roof_colours.items()):
            rgb = [int(hexa[i:i+2], 16)/255 for i in (1, 3, 5)]
            materials[name] = {'name': name, 'mapTo': name, 'class': 'Material', 'version': 1.5,
                               'Stages': [{**metal_roof, 'baseColorFactor': rgb + [1]}, {}, {}, {}],
                               'groundType': 'ASPHALT', 'annotation': 'BUILDINGS', 'materialTag0': 'building'}
        counts['roof_colour_materials'] = len(roof_colours)
        # Sign faces are Ukrainian (DSTU) artwork; other regions get no posted signs
        # rather than foreign-looking ones.
        ukrainian = config.get('region_profile', 'ukraine') == 'ukraine'
        if not ukrainian:
            counts['signs_skipped_region'] = sum(len(tile.get('signs', [])) for _tid, tile in tiles)
            tiles = [(tid, {**tile, 'signs': []}) for tid, tile in tiles]
        used_signs = {(s['kind'], str(s['value']) if s.get('value') is not None else None)
                      for _tid, tile in tiles for s in tile.get('signs', [])}
        signmats, plates = sign_materials(level, level_id, used_signs)
        materials.update(signmats)
        write_json(level / 'art/kyiv/main.materials.json', materials)
        write_json(level / 'art/forest/managedItemData.json', forest_item_data())

        signobjects, signcounts = road_signs(level, level_id, tiles, plates, corridors, optimization=optimization, metrics=metrics)
        objects += signobjects
        counts.update(signcounts)
        lamps = street_lights(roads, corridors, counts)
        objects += lamps
        counts['street_lamps'] = len(lamps)
        objects += fuel_canopies(level, level_id, index.get('pois', []),
                                 lambda p: corridors.occupied(p, margin=0.6, roads_only=True), counts, corridors, optimization=optimization, metrics=metrics)

        dna_report = index.get('local_visual_dna')
        dna_field = None
        if dna_report:
            positions = {(a['lon'], a['lat']): a['position'] for a in dna_report['visual_anchors']}
            dna_field = Field({'version': 1, 'profiles': dna_report['profiles'], 'anchors': dna_report['visual_anchors']},
                              lambda lon, lat: positions[(lon, lat)], dna_report['seed'])
        instances, vegcounts = vegetation(tiles, dna_field)
        before = len(instances)
        kept=[]
        for v in instances:
            item,x,y,z,yaw,scale=v
            # Trunk clearance scales with the forest instance; tall vegetation can
            # pierce an elevated carriageway even when its origin is on the ground.
            radius=FOREST_ITEMS[item][1]*scale+.3
            height=(2 if 'bush' in item else 12)*scale
            if corridors.pavement.intersects(Point(x,y).buffer(radius),z-.65,z+height):
                corridors.audit.append({'kind':'vegetation','source':item,'position':[x,y,z],
                                        'scale':scale,'action':'omitted','reason':'trunk envelope intersects road'})
            else:
                kept.append(v)
        instances=kept
        counts['vegetation_removed_from_roads'] = before-len(instances)
        instances = [(item,x,y,z+lift,yaw,scale) for item,x,y,z,yaw,scale in instances]
        counts.update(vegcounts)
        for relative, text in forest_files(instances).items():
            (level / relative).parent.mkdir(parents=True, exist_ok=True)
            (level / relative).write_text(text, encoding='utf8')
        objects.append(scene_object('KyivForest', 'Forest', 'MissionGroup'))

        head = signal_mesh()
        head.write(level / 'art/shapes/kyiv_signal_head.dae', (0, 0, 0), uv_scales=UV, optimization=optimization)
        for edge, post, top, clear, heads in signal_masts(sig, lanes, corridors, counts):
            if not clear:
                corridors.audit.append({'kind': 'signal_mast', 'source': edge, 'position': post,
                                        'action': 'unresolved', 'reason': 'no clear roadside'})
                continue
            mast = Mesh()
            mast.box((post[0], post[1], (post[2] + top) / 2), (.16, .16, top - post[2] + .1), 'kyiv_metal')
            far = max(heads, key=lambda h: math.dist(h[1][:2], post[:2]))[1]
            span = math.dist(far[:2], post[:2])
            if span > .1:
                ux, uy = (far[0] - post[0]) / span, (far[1] - post[1]) / span
                beam_box(mast, (post[0], post[1], top), (post[0] + ux * (span + .5), post[1] + uy * (span + .5), top),
                         .12, .12, 'kyiv_metal')
            # A post that found no clear kerb gets no collision rather than a wall on the road.
            objects.append(write_static(level, level_id, stable_id('kyiv_signal_mast', edge), mast,
                                       post, clear, parent='KyivProps'))
            for s, (x, y, z), (dx, dy) in heads:
                obj = prop(s['name'], f'/levels/{level_id}/art/shapes/kyiv_signal_head.dae',
                           (x, y, z), 0, parent='KyivSignals', collision='None')
                # Row-major like every other prop here: local +X -> direction of travel,
                # so the lenses on local -X face the drivers approaching the stop line.
                obj['rotationMatrix'] = [dx, -dy, 0, dy, dx, 0, 0, 0, 1]
                obj['signalInstance'] = s['name']
                obj['dynamic'] = True
                obj['annotation'] = 'TRAFFIC_SIGNALS'
                obj['instanceColor'] = [0, 0, 0, 1]
                obj['instanceColor1'] = [0, 0, 0, 1]
                obj['instanceColor2'] = [0, 0, 0, 1]
                objects.append(obj)
        counts.update({'spawn_points': len(spawn_points), 'nav_lanes': len(lanes), 'signal_instances': len(sig['instances']),
                       'signal_sequences': len(sig['sequences']), 'forest_instances': len(instances),
                       'scene_objects': len(objects)})

        # These stock shapes ship a dedicated Colmesh-1. Visible Mesh Final
        # unnecessarily feeds all lamp render details to static collision.
        if optimization != 'legacy':
            stock_colliders = {PROP_SHAPES[k] for k in ('street_lamp', 'highway_lamp', 'guardrail')}
            for obj in objects:
                if obj.get('shapeName') in stock_colliders and obj.get('collisionType') == 'Visible Mesh Final':
                    obj['collisionType'] = 'Collision Mesh'
                    counts['stock_collision_mesh_instances'] += 1

        for obj in objects:
            shift_object(obj, lift)
        for signal in sig['instances']:
            signal['pos'] = [*signal['pos'][:2], signal['pos'][2]+lift]
        write_json(level / 'signals.json', sig)
        if namespace:
            from .namespace import namespace_level
            objects, sig = namespace_level(level, level_id, objects, sig)
            write_json(level / 'signals.json', sig)
        baseline = {'version': VERSION, 'level_id': level_id, 'objects': objects,
                    'vertical_offset': lift}
        write_json(level / 'kyiv-baseline.json', baseline)
        conflicts = []
        if overrides:
            document = read_json(overrides)
            if document.get('level_id') != level_id or document.get('version') != VERSION:
                raise ValueError('Overrides target another level or format version')
            objects, conflicts = apply_overrides(objects, document, baseline)
            if conflicts:
                raise ValueError(f'Manual override conflicts: {conflicts}; review against the new baseline')
        groups = defaultdict(list)
        byname = {o['name']: o for o in objects}
        if len(byname) != len(objects):
            raise ValueError('Duplicate scene names')

        def group_path(name, seen=()):
            if not name:
                return level / 'main'
            if name in seen or name not in byname:
                raise ValueError(f'Invalid scene parent {name}')
            return group_path(byname[name].get('__parent', ''), seen + (name,)) / name

        for obj in objects:
            groups[group_path(obj.get('__parent', '')) / 'items.level.json'].append(obj)
        for file, values in groups.items():
            write_items(file, values)
        # A declared SimGroup without its own items file makes the loader log a
        # deserialisation error, so every group gets one even when it stays empty.
        for name in GROUPS:
            if namespace:
                name = level_id + '__' + name
            file = level / 'main/MissionGroup' / name / 'items.level.json'
            if not file.exists():
                write_items(file, [])

        write_json(level / 'info.json', {
            'title': 'Kyiv — ' + index['name'],
            'description': 'Real OSM road layout and buildings; synthetic elevations, signal timings and street dressing.',
            'authors': 'Earth2Road contributors',
            'size': [round(bounds[2] - bounds[0]), round(bounds[3] - bounds[1])],
            'defaultSpawnPointName': 'spawn_default',
            'spawnPoints': spawn_points,
            'supportsTraffic': True, 'roadRules': {'rightHandDrive': False}, 'previews': ['preview.png']})
        png(level / 'preview.png', 512, 512, preview_image(tiles, points, bounds))
        if ukrainian:
            license_plate(stage, level_id)
        attribution = index['attribution'] + (
            '\n\nSignal timings, inferred heights, street lighting and procedural appearance are synthetic,\n'
            'not surveyed Kyiv data. Vegetation, street furniture and surface materials reference the\n'
            'BeamNG.drive shared art libraries by path; no game file is redistributed with this mod.\n')
        for doc in ('SOURCES.md', 'CITY_ENRICHMENT.md'):
            file = source_root / 'docs' / doc
            if file.exists():
                attribution += '\n' + file.read_text(encoding='utf8')
        (level / 'ATTRIBUTION.txt').write_text(attribution, encoding='utf8')
        report = {'format_version': VERSION, 'map': mid, 'level_id': level_id, 'counts': dict(counts), 'optimization': optimization,
                  'source_files': sources, 'coordinate_transform': 'BeamNG(x,y,z) = World(x,-z,y+vertical_offset)',
                  'vertical_offset': lift,
                  'sumo_location': location, 'sumo_center_offset': index['offset'],
                  'base_height': index['base_height'], 'bounds': bounds, 'signal_reductions': sigaudit,
                  'road_height_audit': height_audit,
                  'curb_audit': curb_audit, 'placement_audit': corridors.audit,
                  'acceptance_ready': not any(a['action'] == 'unresolved' for a in corridors.audit),
                  'geometry_errors': errors, 'override_conflicts': conflicts, 'runtime_verified': False,
                  'stock_assets': 'BeamNG /art/shapes, /assets/meshes and /assets/materials referenced by path',
                  'limitations': [
                      'Roads and terrain use triangle meshes; a native TerrainBlock 100 m below the lowest road replaces the mesh-only physics fallback at z=0.',
                      'Street lighting and park filler planting are synthetic dressing, not surveyed.',
                      'Facade, roof and ground materials are a plausible palette keyed to the OSM '
                      'building type. Named malls and big-box shops in config/landmarks.json get a '
                      'synthetic glass or cladding skin; fuel canopies are synthetic slabs beside '
                      'the OSM station, not a measured forecourt. No logos or trademark colours.',
                      'Panel facades, road sign faces, signal lenses and the licence plate are drawn '
                      'by this project; the game ships no Ukrainian equivalents.',
                      'Lane markings come from SUMO; the AI roads are drawn with an invisible material.',
                      'Manual capture preserves scene objects, not edited DAE, terrain or signal files.',
                      'Input snapshot edge gaps are retained; no claim of 2 cm road-seam acceptance.',
                      'Visible mesh collision uses triangles; 250 m buckets serve spatial culling.',
                      f'Level datum shifted by {lift:g} m from the snapshot.',
                      'Navigation roads are thinned and de-duplicated for the engine graph; the '
                      'visible surface keeps the full snapshot geometry.']}
        write_json(level / 'kyiv-manifest.json', report)
        write_json(level / 'placement-corrections.json', {'version':1,'records':corridors.audit,
                   'note':'Derived export corrections; source OSM and snapshot are unchanged.'})
        write_json(level / 'building-conflicts.json', {'version':1,
                   'records':[a for a in corridors.audit if a['kind']=='building'],
                   'note':'Buildings preserved unchanged at user request; conflicts are deferred.'})
        if errors:
            raise ValueError(f'{len(errors)} invalid building footprints: {errors[:3]}')
        stage_event('validate')
        validate_level(level)
        stage.rename(output)
        if package_zip:
            stage_event('package')
            deterministic_zip(output, output.parent / (output.name + '.zip'))
        write_json(output.parent / (output.name + '.performance.json'), metrics.report())
        return report
    except BaseException:
        # Only remove the temporary directory allocated by this invocation.
        if stage.exists():
            shutil.rmtree(stage)
        raise


def validate_level(level):
    objects = []
    for file in (level / 'main').rglob('items.level.json'):
        objects.extend(json.loads(s) for s in file.read_text(encoding='utf8').splitlines() if s.strip())
    names = {v['name'] for v in objects if 'name' in v}
    if len(names) != len(objects):
        raise ValueError('Duplicate or unnamed objects')
    materials = set(read_json(level / 'art/kyiv/main.materials.json'))
    for obj in objects:
        if obj.get('__parent') and obj['__parent'] not in names:
            raise ValueError('Missing scene parent')
        if obj['class'] == 'TSStatic' and obj['shapeName'].startswith('/levels/'):
            relative = obj['shapeName'].removeprefix('/levels/' + level.name + '/')
            if not (level / relative).is_file():
                raise ValueError(f'Missing shape: {relative}')
        if obj['class'] == 'DecalRoad' and obj['material'] not in materials:
            raise ValueError(f'Missing road material: {obj["material"]}')
        if obj['class'] == 'TerrainBlock':
            relative=obj['terrainFile'].removeprefix('/levels/'+level.name+'/')
            if not (level/relative).is_file():
                raise ValueError(f'Missing native terrain: {relative}')
    items = set(read_json(level / 'art/forest/managedItemData.json'))
    forest = 0
    for file in sorted((level / 'forest').glob('*.forest4.json')):
        if file.name.removesuffix('.forest4.json') not in items:
            raise ValueError(f'Forest file without item data: {file.name}')
        for line in file.read_text(encoding='utf8').splitlines():
            if line.strip():
                if json.loads(line)['type'] not in items:
                    raise ValueError('Forest instance without item data')
                forest += 1
    sig = read_json(level / 'signals.json')
    ids = [v['id'] for values in sig.values() for v in values]
    if len(ids) != len(set(ids)):
        raise ValueError('Duplicate signal IDs')
    controllers = {v['id'] for v in sig['controllers']}
    sequences = {v['id'] for v in sig['sequences']}
    for s in sig['instances']:
        if s['controllerId'] not in controllers or s['sequenceId'] not in sequences:
            raise ValueError('Missing signal controller/sequence')
    return {'objects': len(objects), 'signals': len(sig['instances']), 'forest': forest}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--map', default='focus_metro_mcd',
                        help='Installed map id (game/data/<id>); a world folder path is treated as --world')
    parser.add_argument('--world', type=Path,
                        help='World folder from `earth2road build` or the in-game generator (out/generated/<id>); '
                             'writes the same installable ZIP as `earth2road export --target beamng`')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--level-id')
    parser.add_argument('--overrides', type=Path)
    parser.add_argument('--optimization', type=optimization_mode, default='balanced',
                        help='legacy, balanced, compact, or balanced+writer/kerbs/terrain (joined with +)')
    parser.add_argument('--vertical-offset', type=float, default=VERTICAL_OFFSET,
                        help='Raise the whole level by this many metres (0 keeps the snapshot datum)')
    parser.add_argument('--capture-edits', type=Path, metavar='SAVED_LEVEL')
    parser.add_argument('--validate', type=Path, metavar='LEVEL')
    args = parser.parse_args()
    if args.validate:
        print(json.dumps(validate_level(args.validate)))
        return
    if not args.output:
        parser.error('--output is required')
    if args.capture_edits:
        print(f'Captured {capture_edits(args.capture_edits, args.output)} changed objects')
        return
    world = args.world
    if world is None and not re.fullmatch('[a-z0-9_]+', args.map) and (Path(args.map) / 'config.json').is_file():
        world = Path(args.map)
    if world is not None:
        if args.vertical_offset != VERTICAL_OFFSET:
            parser.error('--vertical-offset applies to installed map ids, not to --world exports')
        from akadem_maps.adapters.beamng.export import export_world
        result = export_world(world, args.output, overrides=args.overrides, level_id=args.level_id, optimization=args.optimization)
    else:
        result = export_map(args.map, args.output, args.level_id, args.overrides, lift=args.vertical_offset, optimization=args.optimization)
    print(json.dumps(result,
                     ensure_ascii=True, indent=2))


if __name__ == '__main__':
    main()
