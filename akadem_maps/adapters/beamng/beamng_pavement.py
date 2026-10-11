"""Exact projected triangles shared by roadside clearance and low kerbs.

Heights are interpolated on the exported surface, never on a road centreline.
The spatial index retains overlapping decks as separate triangles.
"""
import math

from shapely.geometry import Point, Polygon, box
from shapely.strtree import STRtree

from akadem_maps.adapters.beamng.beamng_geometry import Mesh, beam_point


def road_mesh(tile):
    mesh = Mesh()
    for road in tile.get('road_strips', []):
        if road.get('geometry') == 'v2':
            # Cut at a generated junction socket; the ribbon would overlap it.
            for tri in road['triangles']:
                mesh.tri('road', *(beam_point(p) for p in tri), up=True)
        else:
            mesh.strip([beam_point(p) for p in road['points']], road['width'],
                       'road', centre_seam=True)
    for junction in tile.get('junctions', []):
        for tri in junction.get('triangles', []):
            mesh.tri('road', *(beam_point(p) for p in tri), up=True)
    return mesh


class Pavement:
    def __init__(self, triangles):
        self.triangles, self.polygons, self.planes = [], [], []
        for tri in triangles:
            a, b, c = tri
            den = (b[1]-c[1])*(a[0]-c[0]) + (c[0]-b[0])*(a[1]-c[1])
            if abs(den) < 1e-10:
                continue
            self.triangles.append(tri)
            self.polygons.append(Polygon([p[:2] for p in tri]))
            ux, uy = (b[1]-c[1])/den, (c[0]-b[0])/den
            vx, vy = (c[1]-a[1])/den, (a[0]-c[0])/den
            sx = ux*(a[2]-c[2])+vx*(b[2]-c[2])
            sy = uy*(a[2]-c[2])+vy*(b[2]-c[2])
            self.planes.append((sx, sy, c[2]-sx*c[0]-sy*c[1]))
        self.tree = STRtree(self.polygons)

    @classmethod
    def from_tiles(cls, tiles):
        return cls(tri for _, tile in tiles for tri in road_mesh(tile).faces['road'])

    def z(self, i, x, y):
        a, b, c = self.planes[i]
        return a*x+b*y+c

    def nearest(self, p, distance=2, grade=.65):
        """(XY distance, surface Z, triangle index), respecting the reference deck."""
        if not self.polygons:
            return None
        x,y=p[:2]
        best = None
        for i in self.tree.query(box(x-distance-1e-7,y-distance-1e-7,x+distance+1e-7,y+distance+1e-7)):
            tri=self.triangles[i]
            signs=[(b[0]-a[0])*(y-a[1])-(b[1]-a[1])*(x-a[0])
                   for a,b in zip(tri,(*tri[1:],tri[0]))]
            if min(signs)>=-1e-8 or max(signs)<=1e-8:
                d,qx,qy=0.,x,y
            else:
                d,qx,qy=float('inf'),x,y
                for a,b in zip(tri,(*tri[1:],tri[0])):
                    dx,dy=b[0]-a[0],b[1]-a[1]
                    den=dx*dx+dy*dy
                    u=max(0,min(1,((x-a[0])*dx+(y-a[1])*dy)/den)) if den else 0
                    ax,ay=a[0]+u*dx,a[1]+u*dy
                    ds=(x-ax)**2+(y-ay)**2
                    if ds<d: d,qx,qy=ds,ax,ay
                d=math.sqrt(d)
            if d>distance+1e-7:
                continue
            z = self.z(i, qx, qy)
            if abs(z-p[2]) > grade:
                continue
            candidate = (round(d,9), abs(z-p[2]), int(i), z)
            if best is None or candidate < best:
                best = candidate
        return (best[0], best[3], best[2]) if best else None

    def intersects(self, footprint, bottom, top, margin=0):
        """3D envelope against actual road triangles; bridges remain independent.

        Clip each triangle by the object's vertical interval before the XY test.
        Merely overlapping its min/max Z is insufficient on a slope.
        """
        shape = footprint.buffer(margin) if margin else footprint
        for i in self.tree.query(shape, predicate='intersects'):
            vertices = list(self.triangles[i])
            for height, above in ((bottom, True), (top, False)):
                clipped = []
                for a, b in zip(vertices, vertices[1:] + vertices[:1]):
                    ina = a[2] >= height if above else a[2] <= height
                    inb = b[2] >= height if above else b[2] <= height
                    if ina:
                        clipped.append(a)
                    if ina != inb:
                        t = (height-a[2])/(b[2]-a[2])
                        clipped.append(tuple(a[k]+t*(b[k]-a[k]) for k in range(3)))
                vertices = clipped
                if not vertices:
                    break
            if len(vertices) >= 3 and Polygon([p[:2] for p in vertices]).intersects(shape):
                return True
        return False

    def occupied(self, p, margin=.3):
        return self.intersects(Point(p[:2]).buffer(max(margin, 1e-6)), p[2]-.65, p[2]+.65)


def polygons(geometry):
    if geometry.geom_type == 'Polygon':
        if geometry.area > 1e-7:
            yield geometry
    elif hasattr(geometry, 'geoms'):
        for part in geometry.geoms:
            yield from polygons(part)
