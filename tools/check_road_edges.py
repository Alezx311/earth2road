#!/usr/bin/env python3
"""Audit road-ribbon edges against the actually rendered surfaces of a generated map.

Read-only. Loads game/data/<id>/ tiles, rebuilds each road strip's ribbon borders with the
same miter formula world.gd draws (port below), samples them, and for every station finds
what the player would see just outside the asphalt: a covering ribbon (another road lane,
a sidewalk curb), or a terrain triangle (ground/green/wood/water/parking/walkingarea).

Tile selection matches tools/prepare.py write_world: every item goes whole to the tile of
its first godot-space point (floor(x/500)_floor(z/500)); triangle soups per-triangle
centroid. `--near` therefore loads every tile whose godot-space box can hold a first point
of an item passing within the radius (margin 800 m), then filters strips by true distance.

Metrics (per kind, per tile set):
  road_border groups  = road border z - rendered surface z at the same XY (m). Positive =
                        the asphalt edge hangs above the surface = the dark-wedge class.
                        Surfaced via: ground / green* , parking* (greens & parking sit
                        0.5 m off the asphalt, '*' = lateral offset) / walkarea /
                        roadrib (neighbouring lane, junction; expect ~0) /
                        sidewalk (curb top; expect ~ -0.15) / exposed (no surface within
                        0.25 m) / hole (no terrain triangle within 0.5 m).
  shared_border kinds = at green/wood/water/parking/walkarea triangle vertices that lie on
                        a ground triangle, z of that surface minus ground z. Verifies the
                        exact shared-border constraint of every terrain family, not just
                        bare ground at the road edge.

    .venv/bin/python tools/check_road_edges.py --map west_kyiv --near 22.305,147.05,200 --step 0.5
    .venv/bin/python tools/check_road_edges.py --map west_kyiv --max-strips 3000
"""
import argparse
import json
import math
from pathlib import Path
import sys

import numpy as np
from shapely.geometry import Point, Polygon
from shapely import STRtree

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tools'))
import paths

CURB = 0.15          # world.gd sidewalk / walkingarea lift
TILE = 500.0         # prepare.py write_world
WEDGE_CM = 0.05      # |gap| above this counts as a visible seam
QUERY_R = 1.5        # look for terrain triangles within this lateral distance of a station
EXPOSED = 0.25       # lateral distance beyond which the road edge is "exposed"
HOLE_R = 0.5         # no terrain triangle within this distance -> hole
RIBBON_EPS = 0.6     # ribbon coverage tolerance (extension + junction overlap)
NEAR_MARGIN = 800.0  # first-point margin when selecting tiles for --near

TERRAIN_KINDS = {'ground', 'green', 'wood', 'water', 'parking', 'walkarea'}
ROAD_KINDS = {'roadrib', 'junction'}


def godot_borders(points, half):
    """Port of world.gd `borders`: mitered offset of the polyline in the (x, z) plane with
    clamp scale 0.5. Points are [gx, gy, gz]; heights (gy) are carried through unchanged."""
    n = len(points)
    left, right = [], []
    for i in range(n):
        p = np.asarray(points[i], dtype=float)
        prev = np.asarray(points[max(i-1, 0)], dtype=float)
        nxt = np.asarray(points[min(i+1, n-1)], dtype=float)
        d0 = np.array([p[0]-prev[0], p[2]-prev[2]])
        d1 = np.array([nxt[0]-p[0], nxt[2]-p[2]])
        if i > 0 and math.hypot(*d0) > 1e-12:
            d0 = d0/math.hypot(*d0)
        else:
            d0 = np.zeros(2)
        if i < n-1 and math.hypot(*d1) > 1e-12:
            d1 = d1/math.hypot(*d1)
        else:
            d1 = np.zeros(2)
        direc = d0+d1
        dl = math.hypot(*direc)
        if dl < 1e-5:
            direc = d1 if math.hypot(*d1) > 1e-9 else d0
            dl = math.hypot(*direc) or 1.0
        direc = direc/dl
        perp = np.array([-direc[1], direc[0]])
        ref = np.array([-d0[1], d0[0]]) if math.hypot(*d0) > 1e-9 else np.array([-d1[1], d1[0]])
        scale = 1.0/max(0.5, abs(float(perp @ ref)))
        off = np.array([perp[0], 0.0, perp[1]])*half*scale
        left.append(p+off)
        right.append(p-off)
    return left, right


def seg_index(segments, cell=50.0):
    """segments: (x0, z0, y0, x1, z1, y1); returns grid cell -> list of indices."""
    grid = {}
    for idx, s in enumerate(segments):
        for i in range(int(min(s[0], s[3])//cell), int(max(s[0], s[3])//cell)+1):
            for j in range(int(min(s[1], s[4])//cell), int(max(s[1], s[4])//cell)+1):
                grid.setdefault((i, j), []).append(idx)
    return grid


def nearest_segment(segments, grid, x, z, skip=(), cell=50.0):
    """Closest ribbon segment to (x, z) not in `skip`: (distance, interpolated y, idx)."""
    cx, cz = int(x//cell), int(z//cell)
    best = None
    for i in (-1, 0, 1):
        for j in (-1, 0, 1):
            for idx in grid.get((cx+i, cz+j), ()):
                if idx in skip:
                    continue
                x0, z0, y0, x1, z1, y1 = segments[idx]
                dx, dz = x1-x0, z1-z0
                length2 = dx*dx+dz*dz
                t = 0.0
                if length2 > 1e-12:
                    t = max(0.0, min(1.0, ((x-x0)*dx+(z-z0)*dz)/length2))
                px, pz = x0+dx*t, z0+dz*t
                d = math.hypot(px-x, pz-z)
                if best is None or d < best[0]:
                    best = (d, y0+(y1-y0)*t, idx)
    return best


def tri_geom(tri):
    return Polygon([(tri[0][0], tri[0][2]), (tri[1][0], tri[1][2]), (tri[2][0], tri[2][2])])


def tri_area2(tri):
    (x1, _, z1), (x2, _, z2), (x3, _, z3) = tri
    return abs((x2-x1)*(z3-z1)-(x3-x1)*(z2-z1))


def tri_sample(tri, x, z, within=True):
    """Height of the plane of `tri` at (x, z), plus 2D containment flag."""
    (x1, y1, z1), (x2, y2, z2), (x3, y3, z3) = tri
    area = (x2-x1)*(z3-z1)-(x3-x1)*(z2-z1)
    if abs(area) < 1e-14:
        return None, False
    w1 = ((x2-x)*(z3-z)-(x3-x)*(z2-z))/area
    w2 = ((x3-x)*(z1-z)-(x1-x)*(z3-z))/area
    w3 = 1.0-w1-w2
    inside = within and w1 >= -1e-6 and w2 >= -1e-6 and w3 >= -1e-6
    return w1*y1+w2*y2+w3*y3, inside


def load_surfaces(folder, tile_names):
    """Triangles (kind-tagged) and ribbon segments of the chosen tiles. Returns
    (tris, tri_kinds, ribbon_segs 6-tuples, ribbon_kinds, road_strip_ranges, strips)."""
    tris, tri_kinds, ribbons, ribbon_kinds = [], [], [], []
    strip_ranges, strips = [], []

    def add_tri(t, kind, lift=0.0):
        v = [(p[0], p[1]+lift, p[2]) for p in t]
        if tri_area2(v) < 1e-6:
            return
        tris.append(v)
        tri_kinds.append(kind)

    for name in tile_names:
        tile = json.loads((folder/'tiles'/f'{name}.json').read_text())
        for t in tile.get('ground', []):
            add_tri(t, 'ground')
        for area in tile.get('greens', []):
            for t in area['triangles']:
                add_tri(t, area.get('kind', 'green'))
        for t in tile.get('parking', []):
            add_tri(t, 'parking')
        for area in tile.get('walkingareas', []):
            for t in area['triangles']:
                add_tri(t, 'walkarea', lift=CURB)
        for j in tile.get('junctions', []):
            for t in j['triangles']:
                add_tri(t, 'junction')
        for strip in tile.get('road_strips', []):
            start = len(ribbons)
            half = strip['width']/2
            l, r = godot_borders(strip['points'], half)
            for border in (l, r):
                for (x0, y0, z0), (x1, y1, z1) in zip(border, border[1:]):
                    n = len(ribbons)
                    ribbons.append((x0, z0, y0, x1, z1, y1))
                    ribbon_kinds.append('roadrib')
            strip_ranges.append((start, len(ribbons)))
            strips.append(strip)
        for walk in tile.get('sidewalks', []):
            l, r = godot_borders(walk['points'], walk['width']/2)
            for border in (l, r):
                for (x0, y0, z0), (x1, y1, z1) in zip(border, border[1:]):
                    ribbons.append((x0, z0, y0+0.0, x1, z1, y1+0.0))
                    ribbon_kinds.append('sidewalk')
    return tris, tri_kinds, ribbons, ribbon_kinds, strip_ranges, strips


def stats_for(values):
    if not values:
        return {'n': 0, 'mean': 0.0, 'p90': 0.0, 'max': 0.0,
                'abs_gt_5cm': 0, 'pos_gt_5cm': 0}
    a = np.asarray(values, dtype=float)
    return {'n': int(a.size), 'mean': round(float(a.mean()), 4),
            'p90': round(float(np.percentile(a, 90)), 4), 'max': round(float(a.max()), 4),
            'abs_gt_5cm': int((np.abs(a) > WEDGE_CM).sum()),
            'pos_gt_5cm': int((a > WEDGE_CM).sum())}


def audit(mid, tile_names, center=None, radius=250.0, max_strips=None, step=1.0):
    folder = paths.game_dir(mid)
    index = json.loads((folder/'index.json').read_text())
    tris, tri_kinds, segs, kinds, strip_ranges, all_strips = load_surfaces(folder, tile_names)
    grid = seg_index(segs)
    tree = STRtree([tri_geom(t) for t in tris])
    spawn_pos = index.get('spawn', {}).get('position')
    cx, cz = center if center else ((spawn_pos[0], spawn_pos[2]) if spawn_pos else (0.0, 0.0))

    def terrain_at(x, z):
        """(kind, surface_z, lateral) of the best terrain triangle at (x, z)."""
        geom = Point(x, z)
        best = None
        for ci in tree.query(geom.buffer(QUERY_R)):
            z_hit, inside = tri_sample(tris[ci], x, z)
            if z_hit is None or z_hit != z_hit:
                continue
            lateral = 0.0 if inside else geom.distance(tri_geom(tris[ci]))
            key = (not inside, lateral)
            if best is None or key < best[0]:
                best = (key, z_hit, tri_kinds[ci])
        if best is None:
            return None
        (not_inside, lateral), z_hit, kind = best
        return kind, z_hit, lateral

    def station(x, z, road_z, skip):
        # 1) Another ribbon covering this XY (neighbouring lane / sidewalk)?
        nb = nearest_segment(segs, grid, x, z, skip)
        if nb is not None and nb[0] <= RIBBON_EPS:
            kind = kinds[nb[2]]
            if kind == 'sidewalk':
                return 'sidewalk', road_z-(nb[1]+CURB), nb[0]
            return 'roadrib', road_z-nb[1], nb[0]
        # 2) Terrain triangle.
        res = terrain_at(x, z)
        if res is not None:
            kind, z_hit, lateral = res
            group = kind if kind in TERRAIN_KINDS else 'roadrib'
            if lateral > 0.02:
                group += '*' if group in TERRAIN_KINDS else ''
            return group, road_z-z_hit, lateral
        # 3) Nothing within QUERY_R: nearest triangle plane, or hole.
        nb2 = tree.nearest(Point(x, z))
        if isinstance(nb2, tuple):
            nb2 = nb2[0]
        if nb2 is not None and int(nb2) >= 0:
            z_hit, _ = tri_sample(tris[int(nb2)], x, z, within=False)
            if z_hit == z_hit:
                lateral = Point(x, z).distance(tri_geom(tris[int(nb2)]))
                return ('exposed' if lateral > EXPOSED else 'terrain-nearest',
                        road_z-z_hit, lateral)
        return 'hole', 0.0, math.inf

    # Strips within range, nearest-first.
    picked = []
    for i, s in enumerate(all_strips):
        d0 = min(math.hypot(p[0]-cx, p[2]-cz) for p in s['points'])
        if d0 <= radius+RIBBON_EPS:
            picked.append((d0, i, s))
    picked.sort(key=lambda t: t[0])
    if max_strips:
        picked = picked[:max_strips]

    buckets = {}
    shared = {}
    total_stations = 0
    spawn_strip = None

    for d0, idx, s in picked:
        if spawn_strip is None:
            spawn_strip = {'distance_to_spawn_m': round(d0, 2),
                           'points_start': s['points'][0], 'width': s['width'],
                           'bridge': s.get('bridge', False)}
        if s.get('bridge', False):
            continue                      # bridges are excluded from the fix by design
        half = s['width']/2
        skip = set(range(*strip_ranges[idx]))
        for border in godot_borders(s['points'], half):
            for (x0, y0, z0), (x1, y1, z1) in zip(border, border[1:]):
                length = math.hypot(x1-x0, z1-z0)
                if length <= 1e-9:
                    continue
                n = max(1, int(math.ceil(length/step)))
                total_stations += n
                for k in range(n):
                    t = k/n
                    group, gap, lateral = station(x0+(x1-x0)*t, z0+(z1-z0)*t,
                                                  y0+(y1-y0)*t, skip)
                    buckets.setdefault(group, []).append(gap)

    # Shared-border pass: every green/wood/water/parking/walkarea vertex that sits ON a
    # ground triangle must agree with the ground surface (z-step check per kind).
    kinds_to_check = {'green', 'wood', 'water', 'parking', 'walkarea'}
    for ci, kind in enumerate(tri_kinds):
        if kind not in kinds_to_check:
            continue
        for v in tris[ci]:
            x, z = v[0], v[2]
            res = terrain_at(x, z)
            if res is None or res[0] != 'ground':
                continue
            _, gz, lateral = res
            if lateral > 0.05:
                continue
            shared.setdefault(kind+'-on-ground', []).append(v[1]-gz)

    groups = {g: stats_for(v) for g, v in sorted(buckets.items())}
    shared_out = {k: stats_for(v) for k, v in sorted(shared.items())}
    return {'map': mid, 'tiles': sorted(tile_names),
            'center': [round(cx, 2), round(cz, 2)], 'radius': radius,
            'strips_near_center': len(picked), 'border_stations': total_stations,
            'spawn': spawn_strip, 'groups': groups, 'shared_border': shared_out}


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--map', default=None, help='map id (default: active map)')
    ap.add_argument('--tiles', default=None, help='comma list of tile names (default: all)')
    ap.add_argument('--near', default=None, help='gx,gz,radius: strips/tiles near a point')
    ap.add_argument('--max-strips', type=int, default=None)
    ap.add_argument('--step', type=float, default=1.0, help='sample spacing along borders, m')
    ap.add_argument('--out', default=None, help='json output path')
    args = ap.parse_args()

    mid = args.map or paths.map_id()
    folder = paths.game_dir(mid)
    index = json.loads((folder/'index.json').read_text())
    all_tiles = sorted(index['tiles'])
    center = None
    radius = 250.0
    tile_names = all_tiles
    if args.near:
        gx, gz, radius = (float(v) for v in args.near.split(','))
        center = (gx, gz)
        m = radius+NEAR_MARGIN
        # Same key() as prepare.write_world: godot-space floor(coord/500), no offset.
        tx0, tx1 = int(math.floor((gx-m)/TILE)), int(math.floor((gx+m)/TILE))
        tz0, tz1 = int(math.floor((gz-m)/TILE)), int(math.floor((gz+m)/TILE))
        cand = {f'{tx}_{tz}' for tx in range(tx0, tx1+1) for tz in range(tz0, tz1+1)}
        tile_names = sorted(cand & set(index['tiles']))
    if args.tiles:
        tile_names = sorted(set(args.tiles.split(',')) & set(index['tiles']))
    if not tile_names:
        ap.error('no tiles selected')

    report = audit(mid, tile_names, center, radius, args.max_strips, args.step)
    out = args.out or str(ROOT/'logs/road_edge_audit.json')
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(json.dumps(report, indent=1, ensure_ascii=False))
    print(json.dumps(report, indent=1, ensure_ascii=False))


if __name__ == '__main__':
    main()