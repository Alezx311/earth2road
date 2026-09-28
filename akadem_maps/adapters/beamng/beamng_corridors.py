"""Grade-aware clearance queries shared by bridge furniture and road audits."""
from collections import defaultdict
import math
from akadem_maps.adapters.beamng.beamng_geometry import beam_point, ribbon, normal, cross
from akadem_maps.adapters.beamng.beamng_pavement import Pavement
from shapely.geometry import Polygon, Point
from shapely.ops import unary_union, nearest_points


class Corridors:
    CELL = 20

    def __init__(self, tiles):
        tiles = list(tiles)
        self.pavement = Pavement.from_tiles(tiles)
        self.audit = []
        self.cells = defaultdict(list)
        self.junction_cells = defaultdict(list)
        self.strips = []
        for tileid, tile in tiles:
            # Junction pavement is drivable too: without it lamps and signal posts were
            # accepted right in the middle of intersections.
            for i, junction in enumerate(tile.get('junctions', [])):
                key = (tileid, 'junctions', i)
                for tri in junction.get('triangles', []):
                    t = [beam_point(p) for p in tri]
                    for ix in range(math.floor((min(p[0] for p in t)-2)/self.CELL), math.floor((max(p[0] for p in t)+2)/self.CELL)+1):
                        for iy in range(math.floor((min(p[1] for p in t)-2)/self.CELL), math.floor((max(p[1] for p in t)+2)/self.CELL)+1):
                            self.junction_cells[ix,iy].append((key, t))
            for field in ('road_strips', 'sidewalks'):
                for i, strip in enumerate(tile.get(field, [])):
                    key = (tileid, field, i)
                    points = [beam_point(p) for p in strip['points']]
                    width = strip['width']
                    self.strips.append((key, strip, points))
                    for a, b in zip(points, points[1:]):
                        margin = width/2 + 1
                        for ix in range(math.floor((min(a[0],b[0])-margin)/self.CELL), math.floor((max(a[0],b[0])+margin)/self.CELL)+1):
                            for iy in range(math.floor((min(a[1],b[1])-margin)/self.CELL), math.floor((max(a[1],b[1])+margin)/self.CELL)+1):
                                self.cells[ix,iy].append((key,a,b,width))

    def occupied(self, p, margin=0.3, exclude=None, roads_only=False):
        if self.pavement.occupied(p, margin):
            return True
        if roads_only:
            return False
        cell = (math.floor(p[0]/self.CELL), math.floor(p[1]/self.CELL))
        for key,a,b,width in self.cells.get(cell, ()):
            if key[1] == 'road_strips':
                continue
            if key == exclude or (roads_only and key[1] != 'road_strips'):
                continue
            dx,dy=b[0]-a[0],b[1]-a[1]
            den=dx*dx+dy*dy
            if den < 1e-10:
                continue
            t=((p[0]-a[0])*dx+(p[1]-a[1])*dy)/den
            if not 0 <= t <= 1:
                continue
            z=a[2]+t*(b[2]-a[2])
            if abs(p[2]-z) < .65 and math.hypot(p[0]-a[0]-t*dx,p[1]-a[1]-t*dy) < width/2+margin:
                return True
        return False

    def push_clear(self, p, steps=(0.0, 0.5, 1.0, 2.0, 3.0, 4.0), margin=0.3):
        """p moved straight away from the nearest carriageway strip until it is clear of all
        carriageway; (point, shift) or (None, None) when no step clears it."""
        if not self.occupied(p,margin=margin,roads_only=True):
            return p,0.0
        pt=Point(p[:2])
        nearby=[self.pavement.polygons[i] for i in self.pavement.tree.query(pt.buffer(30))
                if abs(self.pavement.z(i,p[0],p[1])-p[2])<.65]
        away, best = None, None
        if nearby:
            footprint=unary_union(nearby)
            q=nearest_points(pt,footprint.boundary)[1]
            sign=1 if footprint.covers(pt) else -1
            dx,dy=(q.x-p[0])*sign,(q.y-p[1])*sign
            length=math.hypot(dx,dy)
            if length>1e-8:
                away,best=(dx/length,dy/length),-1
        for key, a, b, _width in self.cells.get((math.floor(p[0]/self.CELL), math.floor(p[1]/self.CELL)), ()):
            if key[1] != 'road_strips':
                continue
            dx, dy = b[0]-a[0], b[1]-a[1]
            den = dx*dx+dy*dy
            if den < 1e-10:
                continue
            t = max(0.0, min(1.0, ((p[0]-a[0])*dx+(p[1]-a[1])*dy)/den))
            ox, oy = p[0]-a[0]-t*dx, p[1]-a[1]-t*dy
            d = math.hypot(ox, oy)
            if abs(p[2]-(a[2]+t*(b[2]-a[2]))) < .65 and (best is None or d < best):
                length = math.sqrt(den)
                # On the centre line itself go to the right of travel, where signs stand.
                best, away = d, (ox/d, oy/d) if d > 1e-6 else (dy/length, -dx/length)
        for shift in steps:
            q = p if away is None else (p[0]+away[0]*shift, p[1]+away[1]*shift, p[2])
            if not self.occupied(q, margin=margin, roads_only=True):
                return q, shift
            if away is None:
                break
        return None, None


def _near_triangle(p, t, margin):
    """p within `margin` of triangle t in plan, and within 0.65 m of its height."""
    if not min(v[2] for v in t) - .65 < p[2] < max(v[2] for v in t) + .65:
        return False
    (ax, ay, _), (bx, by, _), (cx, cy, _) = t
    d1 = (p[0]-bx)*(ay-by) - (ax-bx)*(p[1]-by)
    d2 = (p[0]-cx)*(by-cy) - (bx-cx)*(p[1]-cy)
    d3 = (p[0]-ax)*(cy-ay) - (cx-ax)*(p[1]-ay)
    if not ((d1 < 0 or d2 < 0 or d3 < 0) and (d1 > 0 or d2 > 0 or d3 > 0)):
        return True
    for a, b in ((t[0], t[1]), (t[1], t[2]), (t[2], t[0])):
        dx, dy = b[0]-a[0], b[1]-a[1]
        den = dx*dx + dy*dy
        u = 0 if den < 1e-12 else max(0, min(1, ((p[0]-a[0])*dx + (p[1]-a[1])*dy)/den))
        if math.hypot(p[0]-a[0]-u*dx, p[1]-a[1]-u*dy) < margin:
            return True
    return False


def edge_sections(points, length=2.42):
    """Constant arc-length sections; never extend backwards across a polyline corner."""
    chain=[0.]
    for a,b in zip(points,points[1:]):
        chain.append(chain[-1]+math.dist(a,b))
    def at(s):
        for i in range(len(chain)-1):
            if chain[i+1] >= s and chain[i+1]-chain[i] > 1e-8:
                t=(s-chain[i])/(chain[i+1]-chain[i])
                return tuple(points[i][k]+t*(points[i+1][k]-points[i][k]) for k in range(3))
        return points[-1]
    s=0.
    while s+length <= chain[-1]+1e-8:
        a,b=at(s),at(s+length)
        if math.dist(a,b) > length*.94:
            yield a,b
        s+=length


def bridge_rail_objects(tiles, make_prop, shape, stable_id):
    corridors=Corridors(tiles)
    result=[]
    occupied=set()
    for key,strip,points in corridors.strips:
        if not strip.get('bridge'):
            continue
        # The stock rail extends 0.466 m to one side of its origin. Its posts
        # extend to z=-0.913; keep the entire rail beyond the paved envelope.
        for side,edge in enumerate(ribbon(points,strip['width']+1.2)):
            for i,(a,b) in enumerate(edge_sections(edge)):
                centre=tuple((a[k]+b[k])/2 for k in range(3))
                if any(corridors.occupied(p,margin=.5,exclude=key) for p in (a,centre,b)):
                    continue
                unique=tuple(round(v*2) for v in centre)
                if unique in occupied:
                    continue
                occupied.add(unique)
                obj=make_prop(stable_id('kyiv_rail',(key,side,i)),shape,
                              (centre[0],centre[1],centre[2]+.913),0)
                x=normal(tuple(b[k]-a[k] for k in range(3)))
                y=normal((-x[1],x[0],0)); z=cross(x,y)
                obj['rotationMatrix']=[x[0],y[0],z[0],x[1],y[1],z[1],x[2],y[2],z[2]]
                # Actual stock rail bounds, measured from guardrail1.dae. Check
                # the rotated whole section, not only its centre and endpoints.
                footprint=Polygon([(centre[0]+u*x[0]+v*y[0], centre[1]+u*x[1]+v*y[1])
                                   for u,v in ((-1.212,-.058),(1.212,-.058),(1.212,.466),(-1.212,.466))])
                if corridors.pavement.intersects(footprint, min(a[2],b[2])-.05, max(a[2],b[2])+1.07, margin=.05):
                    continue
                result.append(obj)
    return result
