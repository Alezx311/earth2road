"""Courtyard props for BeamNG from the world's `visual_props` (akadem_maps/core/yards.py).

Parked cars are never exported (DECISIONS 2026-10-08: CPU/GPU load in BeamNG). Shrubs become
forest bushes; benches, bins and playground kits are simple box meshes, the same shapes as the
Godot procedural props, merged per 250 m cell like buildings.
"""
import math
from collections import Counter, defaultdict

from .beamng_geometry import Mesh, beam_point

SKIPPED = ('parked_car',)
COLOURS = {'kyiv_yard_wood': (0.46, 0.39, 0.30), 'kyiv_yard_metal': (0.27, 0.29, 0.30),
           'kyiv_yard_red': (0.66, 0.28, 0.24), 'kyiv_yard_yellow': (0.82, 0.66, 0.24),
           'kyiv_yard_blue': (0.31, 0.45, 0.49), 'kyiv_yard_sand': (0.80, 0.72, 0.55)}
SHRUBS = ('kyiv_bush', 'kyiv_bush_small')


def materials():
    return {name: {'name': name, 'mapTo': name, 'class': 'Material', 'version': 1.5,
                   'Stages': [{'baseColorFactor': [*rgb, 1], 'roughnessFactor': .8}, {}, {}, {}],
                   'annotation': 'OBSTACLE', 'materialTag0': 'Miscellaneous'}
            for name, rgb in COLOURS.items()}


def _box(mesh, origin, axes, local, size, material, pitch=0.0):
    """Box at `local` (x right, y up, z forward, Godot prop space) of `size` (x, y, z);
    `pitch` tilts it about local x (the slide chute)."""
    (ox, oy, oz), (fx, fy), (rx, ry) = origin, axes[0], axes[1]
    cp, sp = math.cos(pitch), math.sin(pitch)
    hx, hy, hz = (v/2 for v in size)
    pts = []
    for sx, sy, sz in ((-1, -1, -1), (1, -1, -1), (1, 1, -1), (-1, 1, -1),
                       (-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1)):
        x, y, z = sx*hx, sy*hy, sz*hz
        y, z = y*cp - z*sp, y*sp + z*cp                     # pitch about local x
        x, y, z = x + local[0], y + local[1], z + local[2]
        pts.append((ox + rx*x + fx*z, oy + ry*x + fy*z, oz + y))
    for i, j, k, l in [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]:
        mesh.tri(material, pts[i], pts[j], pts[k])
        mesh.tri(material, pts[i], pts[k], pts[l])


def _kit(kind):
    """[(local centre, size, material, pitch)] — mirrors game/visuals/assets.gd prop()."""
    W, M, R, Y, B, S = 'kyiv_yard_wood', 'kyiv_yard_metal', 'kyiv_yard_red', 'kyiv_yard_yellow', 'kyiv_yard_blue', 'kyiv_yard_sand'
    p = []
    if kind == 'bench':
        p += [((x, .3, 0), (.08, .6, .5), M, 0) for x in (-.72, .72)]
        p += [((0, .5, z), (1.8, .07, .14), W, 0) for z in (-.18, 0, .18)]
        p += [((0, y, .23), (1.8, .14, .05), W, 0) for y in (.72, .9)]
    elif kind == 'bin':
        p += [((0, .43, 0), (.42, .86, .42), M, 0)]
    elif kind == 'swing':
        p += [((x, 1.1, z*.6), (.07, 2.2, .07), M, 0) for x in (-1.3, 1.3) for z in (-.6, .6)]
        p += [((0, 2.2, 0), (2.7, .08, .08), M, 0)]
        p += [((x, .5, 0), (.45, .05, .25), R, 0) for x in (-.5, .5)]
        p += [((x+dx, 1.35, 0), (.02, 1.7, .02), M, 0) for x in (-.5, .5) for dx in (-.2, .2)]
    elif kind == 'slide':
        p += [((0, 1.2, -.9), (1.0, .08, 1.0), Y, 0)]
        p += [((x, .6, z), (.07, 1.2, .07), M, 0) for x in (-.45, .45) for z in (-1.35, -.45)]
        p += [((0, .65, .7), (.6, .06, 2.6), R, .5), ((0, .65, -1.75), (.5, .05, 1.5), M, -.95)]
    elif kind == 'sandbox':
        p += [((x, .15, z), (sx, .3, sz), W, 0) for x, z, sx, sz in
              ((0, 1.2, 2.5, .25), (0, -1.2, 2.5, .25), (1.2, 0, .25, 2.15), (-1.2, 0, .25, 2.15))]
        p += [((0, .08, 0), (2.2, .16, 2.2), S, 0)]
    elif kind == 'climber':
        p += [((x, .9, z), (.06, 1.8, .06), B, 0) for x in (-1.0, 0, 1.0) for z in (-.7, .7)]
        p += [((0, y, z), (2.0, .05, .05), B, 0) for y in (.6, 1.2, 1.8) for z in (-.7, .7)]
        p += [((0, 1.8, 0), (.05, .05, 1.4), Y, 0)]
    elif kind == 'carousel':
        p += [((0, .3, 0), (1.6, .08, 1.6), R, 0), ((0, .55, 0), (.08, .5, .08), M, 0)]
    return p


def yard_props(tiles, cell_size):
    """-> ({cell: Mesh}, [forest instance], Counter). Instances are (item, x, y, z, yaw, scale)."""
    cells, bushes, counts = defaultdict(Mesh), [], Counter()
    for _tileid, tile in tiles:
        for item in tile.get('visual_props', []):
            kind = item['kind']
            if kind in SKIPPED:
                counts['yard_skipped_'+kind] += 1
                continue
            x, y, z = beam_point(item['position'])
            yaw = float(item.get('yaw', 0))
            if kind == 'shrub':
                choice = SHRUBS[int(abs(x*7 + y*13)) % len(SHRUBS)]
                bushes.append((choice, x, y, z, yaw, 0.7))
                counts['yard_shrubs'] += 1
                continue
            parts = _kit(kind)
            if not parts:
                counts['yard_unknown_'+kind] += 1
                continue
            # Godot yaw turns local +Z to game (sin, cos) = BeamNG (sin, -cos); local +X to (cos, sin).
            axes = ((math.sin(yaw), -math.cos(yaw)), (math.cos(yaw), math.sin(yaw)))
            mesh = cells[(math.floor(x/cell_size), math.floor(y/cell_size))]
            for local, size, material, pitch in parts:
                _box(mesh, (x, y, z), axes, local, size, material, pitch)
            counts['yard_'+kind] += 1
    return cells, bushes, counts
