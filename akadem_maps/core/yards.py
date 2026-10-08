"""Courtyard dressing (playtest 2026-10-08, note 3): parked cars, entrance benches, shrubs
along apartment walls and playground equipment. Every item is synthetic and anchored to an
observed OSM feature (parking area, yard service road, entrance node, apartment wall,
playground); none of it claims an observed object position.

Items go to the world as ``visual_props`` (Godot draws them). ``parked_car`` is Godot-only by
decision: the BeamNG exporter never reads ``visual_props`` (DECISIONS 2026-10-08).
"""
import math
import random

from shapely import STRtree
from shapely.affinity import rotate, translate
from shapely.geometry import LineString, Point, Polygon, box

from .osm_buildings import LocalArea, robust, union

# Passenger models of config/vehicles.json (size = width, height, length) and their share.
PARKED_MODELS = {'sedan': ((1.8, 1.45, 4.5), 5), 'hatchback-sports': ((1.76, 1.42, 4.1), 3),
                 'sedan-sports': ((1.82, 1.32, 4.45), 1), 'suv': ((1.88, 1.7, 4.6), 3),
                 'suv-luxury': ((1.95, 1.75, 4.9), 1), 'van': ((1.92, 1.95, 4.95), 1)}
STALL_WIDTH, STALL_DEPTH, AISLE = 2.6, 5.0, 6.0
PARKING_OCCUPANCY = 0.65
KERB_SPACING, KERB_OCCUPANCY = 5.8, 0.4
YARD_RADIUS = 40.0           # a service road this close to an apartment block is a yard road
YARD_SERVICES = (None, 'parking_aisle', 'alley')
APARTMENTS = ('apartments', 'residential', 'dormitory')
ENTRANCES = ('staircase', 'yes', 'main', 'home')
SHRUB_STEP, SHRUB_OFFSET, SHRUB_CHANCE = 3.0, 1.4, 0.45
# Playground kit: kind -> clearance radius, m.
PLAYGROUND_KIT = {'swing': 2.2, 'slide': 2.0, 'sandbox': 1.8, 'climber': 2.0, 'carousel': 1.6}
PROVENANCE = 'synthetic:yard'


def _tags(el):
    return {t.get('k'): t.get('v') for t in el.findall('tag')}


def _yaw(dx, dy):
    """Godot yaw that turns local +Z toward the network direction (dx, dy); game z = -y."""
    return round(math.atan2(dx, -dy), 4)


def _car_box(x, y, along, size):
    w, _, l = size
    rect = box(-l/2, -w/2, l/2, w/2)
    return translate(rotate(rect, math.degrees(math.atan2(along[1], along[0])), origin=(0, 0)), x, y)


class _Placed:
    """Footprints already used by this module, queried locally (100 m cells)."""
    def __init__(self):
        self.cells = {}

    def _keys(self, g):
        x0, y0, x1, y1 = g.bounds
        return [(i, j) for i in range(math.floor(x0/100), math.floor(x1/100)+1)
                for j in range(math.floor(y0/100), math.floor(y1/100)+1)]

    def free(self, g):
        return not any(o.intersects(g) for k in self._keys(g) for o in self.cells.get(k, ()))

    def add(self, g):
        for k in self._keys(g):
            self.cells.setdefault(k, []).append(g)


def _pick_model(rng):
    names = list(PARKED_MODELS)
    return rng.choices(names, weights=[PARKED_MODELS[n][1] for n in names])[0]


def dress(root, nodes, to_xy, point, road_cut, area, parking_polys, seed):
    """Return (visual_props, counts). ``to_xy`` converts lon/lat to network XY; ``point``
    network XY to a game point on the ground; ``road_cut`` covers carriageways and sidewalks."""
    building_ways, entrances, playgrounds, footways, yard_roads = {}, {}, [], [], []
    for n in root.findall('node'):
        t = _tags(n)
        if t.get('entrance') in ENTRANCES:
            entrances[n.get('id')] = t
    for w in root.findall('way'):
        t = _tags(w)
        refs = [nd.get('ref') for nd in w.findall('nd')]
        if not t or not all(r in nodes for r in refs) or len(refs) < 2:
            continue
        coords = [to_xy(*nodes[r]) for r in refs]
        if 'building' in t and len(refs) >= 4 and refs[0] == refs[-1]:
            poly = Polygon(coords)
            if poly.is_valid and area.intersects(poly):
                building_ways[w.get('id')] = (t, refs, poly)
        elif t.get('leisure') == 'playground' and len(refs) >= 4 and refs[0] == refs[-1]:
            poly = Polygon(coords).buffer(0)
            if not poly.is_empty and area.intersects(poly):
                playgrounds.append((w.get('id'), poly.intersection(area)))
        elif t.get('highway') in ('footway', 'path', 'pedestrian', 'steps', 'cycleway'):
            footways.append(LineString(coords))
        elif (t.get('highway') == 'service' and t.get('service') in YARD_SERVICES) or t.get('highway') == 'living_street':
            yard_roads.append((w.get('id'), LineString(coords)))
    footprints = union(p for _, _, p in building_ways.values())
    walks = union(f.buffer(0.6) for f in footways) if footways else Polygon()
    parking = union(parking_polys) if parking_polys else Polygon()
    near_road, near_house, near_walk = LocalArea(road_cut), LocalArea(footprints), LocalArea(walks)
    near_parking = LocalArea(parking)
    placed = _Placed()
    props = []
    counts = {'parked_cars_lots': 0, 'parked_cars_kerb': 0, 'entrance_benches': 0, 'entrance_bins': 0,
              'shrubs': 0, 'playground_items': 0}

    def blocked(g, road=0.2, house=0.8, walk=True, lots=True):
        x0, y0, x1, y1 = g.bounds
        win = (x0-3, y0-3, x1+3, y1+3)
        if not area.covers(g):
            return True
        if near_road.within(*win).buffer(road).intersects(g) if road else near_road.within(*win).intersects(g):
            return True
        if near_house.within(*win).buffer(house).intersects(g):
            return True
        if walk and near_walk.within(*win).intersects(g):
            return True
        if lots and near_parking.within(*win).intersects(g):
            return True
        return not placed.free(g)

    def add(kind, x, y, yaw, radius, rule, source, footprint, **extra):
        placed.add(footprint)
        props.append({'kind': kind, 'position': point(x, y), 'yaw': yaw, 'radius': radius,
                      'provenance': PROVENANCE, 'rule': rule, 'source': source, **extra})

    # 1. Stalls on observed surface parking: double rows (5 m + 5 m) between 6 m aisles along
    # the lot's long axis; mapped parking aisles are carriageway and stay clear by road_cut.
    for i, lot in enumerate(parking_polys):
        lot = lot.intersection(area)
        if lot.is_empty or lot.area < STALL_WIDTH*STALL_DEPTH*2:
            continue
        rect = lot.minimum_rotated_rectangle
        corners = list(rect.exterior.coords)[:4]
        edges = [(corners[k], corners[(k+1) % 4]) for k in range(2)]
        a, b = max(edges, key=lambda e: math.dist(*e))
        length = math.dist(a, b)
        ux, uy = (b[0]-a[0])/length, (b[1]-a[1])/length
        vx, vy = -uy, ux
        depth = min(math.dist(*e) for e in edges)
        # Rect side order: make v point into the lot.
        c = lot.centroid
        if (c.x-a[0])*vx+(c.y-a[1])*vy < 0:
            vx, vy = -vx, -vy
        rand = random.Random(f'{seed}:lot:{i}')
        inner = lot.buffer(0.05)
        # A row along each long side facing a middle aisle (typical yard lot); deep lots add
        # back-to-back double rows between 6 m aisles; shallow lots get one row.
        edge = STALL_DEPTH/2 + 0.1
        if depth < 2*STALL_DEPTH + AISLE:
            rows = [edge]
        else:
            rows = [edge, depth-edge]
            d = STALL_DEPTH + AISLE
            while d + 2*STALL_DEPTH + AISLE + STALL_DEPTH <= depth:
                rows += [d + STALL_DEPTH/2, d + 1.5*STALL_DEPTH]
                d += 2*STALL_DEPTH + AISLE
        for r in rows:
            s = STALL_WIDTH/2
            while s <= length - STALL_WIDTH/2 + 0.01:
                x, y = a[0]+ux*s+vx*r, a[1]+uy*s+vy*r
                s += STALL_WIDTH
                if rand.random() > PARKING_OCCUPANCY:
                    continue
                along = (vx, vy)                       # cars stand across the row
                model = _pick_model(rand)
                size = PARKED_MODELS[model][0]
                fp = _car_box(x, y, along, size)
                if not inner.covers(fp) or blocked(fp, road=0.3, walk=False, lots=False):
                    continue
                if rand.random() < 0.5:
                    along = (-vx, -vy)
                add('parked_car', x, y, _yaw(*along), round(size[2]/2, 2), 'parking_stall', 'parking_lot',
                    fp, model=model, size=list(size))
                counts['parked_cars_lots'] += 1

    # 2. Kerbside cars along yard service roads near apartment blocks, just off the carriageway.
    blocks = [p for t, _, p in building_ways.values() if t.get('building') in APARTMENTS]
    block_tree = STRtree(blocks) if blocks else None
    for wid, line in yard_roads:
        if block_tree is None or not len(block_tree.query(line.buffer(YARD_RADIUS))):
            continue
        rand = random.Random(f'{seed}:kerb:{wid}')
        s = 8.0
        while s < line.length - 8.0:
            p, q = line.interpolate(s), line.interpolate(min(s+1, line.length))
            s += KERB_SPACING
            if rand.random() > KERB_OCCUPANCY:
                continue
            dx, dy = q.x-p.x, q.y-p.y
            norm = math.hypot(dx, dy) or 1
            ux, uy = dx/norm, dy/norm
            side = 1 if rand.random() < 0.5 else -1
            model = _pick_model(rand)
            size = PARKED_MODELS[model][0]
            for off in (2.6, 3.0, 3.4, 3.8, 4.2, 4.6):
                x, y = p.x - uy*off*side, p.y + ux*off*side
                fp = _car_box(x, y, (ux, uy), size)
                if not blocked(fp, house=1.2, walk=False):
                    along = (ux, uy) if rand.random() < 0.5 else (-ux, -uy)
                    add('parked_car', x, y, _yaw(*along), round(size[2]/2, 2), 'yard_kerb', 'way/'+wid,
                        fp, model=model, size=list(size))
                    counts['parked_cars_kerb'] += 1
                    break

    # 3. A bench beside each observed entrance of a residential block, a bin next to it.
    entrance_zone = []
    owner = {}
    for wid, (t, refs, poly) in building_ways.items():
        for k, r in enumerate(refs[:-1]):
            if r in entrances:
                owner.setdefault(r, (wid, t, refs, poly, k))
    for nid, (wid, t, refs, poly, k) in sorted(owner.items()):
        if t.get('building') not in APARTMENTS + ('yes',):
            continue
        prev, nxt = to_xy(*nodes[refs[k-1 if k else -2]]), to_xy(*nodes[refs[k+1]])
        here = to_xy(*nodes[refs[k]])
        tx, ty = nxt[0]-prev[0], nxt[1]-prev[1]
        norm = math.hypot(tx, ty) or 1
        tx, ty = tx/norm, ty/norm
        nx, ny = ty, -tx
        if poly.contains(Point(here[0]+nx*0.5, here[1]+ny*0.5)):
            nx, ny = -nx, -ny
        entrance_zone.append(Point(here).buffer(4.0))
        rand = random.Random(f'{seed}:entrance:{nid}')
        sides = [1, -1] if rand.random() < 0.5 else [-1, 1]
        for side in sides:
            bx, by = here[0]+nx*2.4+tx*2.3*side, here[1]+ny*2.4+ty*2.3*side
            fp = rotate(box(bx-0.95, by-0.35, bx+0.95, by+0.35), math.degrees(math.atan2(ty, tx)), origin=(bx, by))
            if blocked(fp, road=0.3, house=0.3):
                continue
            # The backrest (+Z) toward the wall: the bench faces away from the door.
            add('bench', bx, by, _yaw(-nx, -ny), 0.9, 'entrance', 'node/'+nid, fp)
            counts['entrance_benches'] += 1
            ix, iy = bx+tx*1.4*side, by+ty*1.4*side
            fb = Point(ix, iy).buffer(0.3)
            if rand.random() < 0.7 and not blocked(fb, road=0.3, house=0.3):
                add('bin', ix, iy, _yaw(-nx, -ny), 0.3, 'entrance', 'node/'+nid, fb)
                counts['entrance_bins'] += 1
            break
    near_entrance = LocalArea(union(entrance_zone)) if entrance_zone else None

    # 4. Shrubs along the walls of apartment blocks, away from doors, paths and roads.
    for wid, (t, refs, poly) in sorted(building_ways.items()):
        if t.get('building') not in APARTMENTS:
            continue
        rand = random.Random(f'{seed}:shrubs:{wid}')
        ring = list(poly.exterior.coords)
        for (x0, y0), (x1, y1) in zip(ring, ring[1:]):
            length = math.hypot(x1-x0, y1-y0)
            if length < 6:
                continue
            tx, ty = (x1-x0)/length, (y1-y0)/length
            nx, ny = ty, -tx
            mid = ((x0+x1)/2+nx*0.5, (y0+y1)/2+ny*0.5)
            if poly.contains(Point(mid)):
                nx, ny = -nx, -ny
            s = 1.5
            while s < length-1.5:
                x, y = x0+tx*s+nx*SHRUB_OFFSET, y0+ty*s+ny*SHRUB_OFFSET
                s += SHRUB_STEP
                if rand.random() > SHRUB_CHANCE:
                    continue
                fp = Point(x, y).buffer(0.7)
                if near_entrance is not None and near_entrance.within(x-1, y-1, x+1, y+1).intersects(fp):
                    continue
                if blocked(fp, road=1.0, house=0.1):
                    continue
                add('shrub', x, y, round(rand.uniform(0, math.tau), 3), 0.7, 'apartment_wall', 'way/'+wid, fp)
                counts['shrubs'] += 1

    # 5. Equipment on observed playgrounds; a couple of benches at the edge.
    for wid, poly in playgrounds:
        inner = robust(lambda a: a.buffer(-1.0), poly)
        if inner.is_empty or poly.area < 40:
            continue
        rand = random.Random(f'{seed}:playground:{wid}')
        want = max(2, min(6, int(poly.area/90)))
        kinds = list(PLAYGROUND_KIT)
        rand.shuffle(kinds)
        x0, y0, x1, y1 = inner.bounds
        for kind in (kinds*2)[:want]:
            radius = PLAYGROUND_KIT[kind]
            for _ in range(25):
                x, y = rand.uniform(x0, x1), rand.uniform(y0, y1)
                fp = Point(x, y).buffer(radius)
                if inner.covers(fp) and not blocked(fp, road=0.5, house=0.5, walk=False):
                    add(kind, x, y, round(rand.choice((0, 0.5, 1, 1.5))*math.pi, 4), radius,
                        'playground', 'way/'+wid, fp)
                    counts['playground_items'] += 1
                    break
        edge = poly.exterior
        for k in range(2):
            p = edge.interpolate(rand.uniform(0, edge.length))
            q = edge.interpolate(min(edge.length, edge.project(p)+1))
            tx, ty = q.x-p.x, q.y-p.y
            norm = math.hypot(tx, ty) or 1
            nx, ny = ty/norm, -tx/norm
            if not poly.contains(Point(p.x+nx, p.y+ny)):
                nx, ny = -nx, -ny
            bx, by = p.x+nx*1.2, p.y+ny*1.2
            fp = Point(bx, by).buffer(0.9)
            if not blocked(fp, road=0.3, house=0.5, walk=False):
                # Backrest to the edge: the bench faces the playground.
                add('bench', bx, by, _yaw(-nx, -ny), 0.9, 'playground', 'way/'+wid, fp)
                counts['playground_items'] += 1
    return props, counts
