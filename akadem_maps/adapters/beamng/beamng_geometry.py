"""Engine-independent geometry and Collada writer (metres, right-handed Z-up).

No Blender or Godot installation is needed to export the cached city snapshot.
"""
from collections import defaultdict
from array import array
import math
from pathlib import Path
from xml.sax.saxutils import escape


OPTIMIZATIONS = ('compact', 'balanced', 'legacy')
CREASE_DEG = 30    # faces meeting at a smaller angle share a smoothed vertex normal
_CREASE_COS = math.cos(math.radians(CREASE_DEG))


def fmt_compact(v, digits=3):
    """Shortest fixed-point text: 1.500 → 1.5, 2.000 → 2."""
    text = f'{v:.{digits}f}'.rstrip('0').rstrip('.')
    return '0' if text in ('-0', '') else text


def _compact_geometry(faces, explicit, scale, origin, collision):
    """Indexed arrays for one material: (pos, normal, uv), indices, triangle count.

    Positions are rounded to 1 mm relative to origin. Around each position, face
    normals within CREASE_DEG of an area-weighted group share that group's normal,
    so flat and gently curved surfaces share vertices while kerb and wall edges
    stay sharp. UVs (4 decimals) remain part of the key, so texture seams are kept.
    Triangles that are zero-area or collapse at 1 mm are dropped. Collision
    geometry is keyed by position only; its normal/UV arrays are placeholders.
    """
    ox, oy, oz = origin
    corners = []    # per kept face: (pos keys, raw normal, face uv)
    groups = defaultdict(list)    # pos key -> [[sx, sy, sz], ...]
    for i, tri in enumerate(faces):
        keys = tuple((round(p[0]-ox, 3), round(p[1]-oy, 3), round(p[2]-oz, 3)) for p in tri)
        if keys[0] == keys[1] or keys[1] == keys[2] or keys[0] == keys[2]:
            continue
        c = cross(sub(tri[1], tri[0]), sub(tri[2], tri[0]))
        if c[0]*c[0]+c[1]*c[1]+c[2]*c[2] < 1e-14:
            continue
        n = normal(c)
        fixed = explicit[i] if i < len(explicit) else None
        if fixed:
            uvs = fixed
        elif abs(n[2]) < .5:
            side = abs(n[0]) < abs(n[1])
            uvs = [((p[0] if side else p[1])*scale, p[2]*scale) for p in tri]
        else:
            uvs = [(p[0]*scale, p[1]*scale) for p in tri]
        slots = []
        for key in keys:
            if collision:
                slots.append(0)
                continue
            options = groups[key]
            for g, acc in enumerate(options):
                length = math.sqrt(acc[0]*acc[0]+acc[1]*acc[1]+acc[2]*acc[2])
                if (acc[0]*n[0]+acc[1]*n[1]+acc[2]*n[2]) >= _CREASE_COS*length:
                    acc[0] += c[0]; acc[1] += c[1]; acc[2] += c[2]
                    slots.append(g)
                    break
            else:
                slots.append(len(options))
                options.append([c[0], c[1], c[2]])
        corners.append((keys, slots, uvs))
    values = [array('d'), array('d'), array('d')]
    indices, lookup = array('I'), {}
    for keys, slots, uvs in corners:
        for key, slot, (u, v) in zip(keys, slots, uvs):
            full = key if collision else (key, slot, round(u, 4), round(v, 4))
            idx = lookup.get(full)
            if idx is None:
                idx = lookup[full] = len(lookup)
                values[0].extend(key)
                if collision:
                    values[1].extend((0., 0., 1.)); values[2].extend((0., 0.))
                else:
                    values[1].extend(normal(groups[key][slot])); values[2].extend((round(u, 4), round(v, 4)))
            indices.append(idx)
    return values, indices, len(corners)


def beam_point(p):
    return (float(p[0]), -float(p[2]), float(p[1]))


def sub(a, b):
    return tuple(x-y for x, y in zip(a, b))


def cross(a, b):
    return (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])


def normal(a):
    length = math.sqrt(sum(x*x for x in a))
    return tuple(x/length for x in a) if length > 1e-12 else (0., 0., 0.)


def ribbon(points, width, lift=0):
    """Same clamped mitres as world.gd; input/output are BeamNG coordinates."""
    pts = [tuple(p) for i, p in enumerate(points) if i == 0 or math.dist(p, points[i-1]) > 1e-8]
    if len(pts) < 2:
        return [], []
    left, right = [], []
    for i, p in enumerate(pts):
        a, b = pts[max(0, i-1)], pts[min(len(pts)-1, i+1)]
        d0 = normal((p[0]-a[0], p[1]-a[1], 0))
        d1 = normal((b[0]-p[0], b[1]-p[1], 0))
        d = normal(tuple(x+y for x, y in zip(d0, d1)))
        if d == (0., 0., 0.):
            d = d1 if d1 != (0., 0., 0.) else d0
        perp = (-d[1], d[0])
        ref = d0 if i else d1
        scale = width/2 / max(.5, abs(perp[0]*(-ref[1])+perp[1]*ref[0]))
        left.append((p[0]+perp[0]*scale, p[1]+perp[1]*scale, p[2]+lift))
        right.append((p[0]-perp[0]*scale, p[1]-perp[1]*scale, p[2]+lift))
    return left, right


def dashed(points, pattern):
    if not pattern:
        yield points
        return
    on, off = pattern
    if on <= 0 or off < 0:
        raise ValueError('Invalid dash lengths')
    distance, current = 0., []
    for a, b in zip(points, points[1:]):
        length = math.hypot(b[0]-a[0], b[1]-a[1])
        if length < 1e-9:
            continue
        s = 0.
        while s < length-1e-8:
            phase = (distance+s) % (on+off)
            drawing = phase < on-1e-8
            step = min((on-phase if drawing else on+off-phase), length-s)
            if step < 1e-8:
                step = min(1e-7, length-s)
            p = tuple(a[k]+(b[k]-a[k])*s/length for k in range(3))
            q = tuple(a[k]+(b[k]-a[k])*(s+step)/length for k in range(3))
            if drawing:
                if not current:
                    current.append(p)
                current.append(q)
            elif current:
                yield current
                current = []
            s += step
        distance += length
    if len(current) > 1:
        yield current


def triangulate(ring):
    """Ear clipping of a simple footprint. Never silently fill a concave roof with a fan."""
    pts = list(ring)
    if pts and pts[0] == pts[-1]:
        pts.pop()
    def turn(a, b, c):
        return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])
    if sum(a[0]*b[1]-b[0]*a[1] for a, b in zip(pts, pts[1:]+pts[:1])) < 0:
        pts.reverse()
    ids = list(range(len(pts)))
    result = []
    while len(ids) > 3:
        for j in range(len(ids)):
            ia, ib, ic = ids[j-1], ids[j], ids[(j+1) % len(ids)]
            a, b, c = pts[ia], pts[ib], pts[ic]
            if turn(a, b, c) <= 1e-10:
                if abs(turn(a,b,c)) < 1e-10:
                    ids.pop(j)
                    break
                continue
            if any(turn(a,pts[k],b) < -1e-9 and turn(b,pts[k],c) < -1e-9
                   and turn(c,pts[k],a) < -1e-9 for k in ids if k not in (ia,ib,ic)):
                continue
            result.append((a,b,c))
            ids.pop(j)
            break
        else:
            raise ValueError('Non-simple building footprint')
    if len(ids) == 3:
        result.append(tuple(pts[k] for k in ids))
    return result


class Mesh:
    def __init__(self):
        self.faces = defaultdict(list)
        self.uvs = defaultdict(list)
        self.dropped = 0

    def tri(self, material, a, b, c, up=False, uv=None):
        """uv overrides the world-metre projection, for plates with a fitted texture."""
        if not all(math.isfinite(v) for p in (a,b,c) for v in p):
            raise ValueError('Non-finite vertex')
        n = cross(sub(b,a),sub(c,a))
        if sum(v*v for v in n) < 1e-14:
            self.dropped += 1
            return
        if up and n[2] < 0:
            b,c = c,b
            uv = (uv[0],uv[2],uv[1]) if uv else None
        self.faces[material].append((a,b,c))
        self.uvs[material].append(uv)

    def strip(self, points, width, material, lift=0, sides=False, depth=0, centre_seam=False):
        left,right = ribbon(points,width,lift)
        for i in range(len(left)-1):
            if centre_seam:
                a=tuple((left[i][k]+right[i][k])/2 for k in range(3))
                b=tuple((left[i+1][k]+right[i+1][k])/2 for k in range(3))
                self.tri(material,left[i],a,b,up=True)
                self.tri(material,left[i],b,left[i+1],up=True)
                self.tri(material,a,right[i],right[i+1],up=True)
                self.tri(material,a,right[i+1],b,up=True)
            else:
                self.tri(material,left[i],right[i],right[i+1],up=True)
                self.tri(material,left[i],right[i+1],left[i+1],up=True)
            if sides:
                self.wall(left[i+1],left[i],-depth,0,material)
                self.wall(right[i],right[i+1],-depth,0,material)
        return left,right

    def wall(self,a,b,bottom,top,material):
        p=(a[0],a[1],a[2]+bottom); q=(b[0],b[1],b[2]+bottom)
        r=(b[0],b[1],b[2]+top); s=(a[0],a[1],a[2]+top)
        self.tri(material,p,q,r); self.tri(material,p,r,s)

    def box(self,center,size,material):
        x,y,z=center; a,b,c=(v/2 for v in size)
        pts=[(x+dx*a,y+dy*b,z+dz*c) for dx,dy,dz in
             [(-1,-1,-1),(1,-1,-1),(1,1,-1),(-1,1,-1),(-1,-1,1),(1,-1,1),(1,1,1),(-1,1,1)]]
        for i,j,k,l in [(0,3,2,1),(4,5,6,7),(0,1,5,4),(1,2,6,5),(2,3,7,6),(3,0,4,7)]:
            self.tri(material,pts[i],pts[j],pts[k]); self.tri(material,pts[i],pts[k],pts[l])

    @property
    def count(self):
        return sum(map(len,self.faces.values()))

    def chunks(self, cell):
        """Group triangles by XY centroid for spatial culling (not convex hulls).

        Triangles are not clipped, so a long triangle can extend outside a bucket.
        The mesh-only physics fallback at z=0 is replaced by a native low substrate.
        """
        buckets = defaultdict(Mesh)
        for mat, faces in self.faces.items():
            uvs = self.uvs[mat]
            for i, tri in enumerate(faces):
                cx = (tri[0][0] + tri[1][0] + tri[2][0]) / 3.0
                cy = (tri[0][1] + tri[1][1] + tri[2][1]) / 3.0
                key = (math.floor(cx / cell), math.floor(cy / cell))
                part = buckets[key]
                part.faces[mat].append(tri)
                part.uvs[mat].append(uvs[i] if i < len(uvs) else None)
        return buckets

    def write(self, path, origin=(0,0,0), uv_scales=None, *, optimization='balanced', collision=None):
        """Stream indexed attributes; share only identical position/normal/UV tuples.

        The key uses the same six decimals as the legacy writer, so indexing cannot
        alter exported shading, texture seams or coordinates. Work is bounded to
        one material at a time. Optional Colmesh nodes use triangle collisions.
        'compact' rounds positions to 1 mm and smooths normals across faces within
        CREASE_DEG (see _compact_geometry); zero-area triangles are dropped.
        """
        if optimization not in OPTIMIZATIONS:
            raise ValueError('Unknown BeamNG optimization: '+str(optimization))
        compact = optimization == 'compact'
        triangle_count = collision_count = 0
        if optimization == 'legacy':
            self._write_legacy(path, origin, uv_scales)
            return {'triangles': self.count, 'vertices': self.count*3,
                    'collision_triangles': 0, 'bytes': Path(path).stat().st_size}
        uv_scales = uv_scales or {}
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        meshes = [(False, self)] + ([(True, collision)] if collision is not None else [])
        materials = sorted({m for _, mesh in meshes for m in mesh.faces})
        nodes = []
        vertex_count = 0
        with path.open('w', encoding='utf8', newline='\n') as out:
            def line(s):
                out.write(s+'\n')
            def numbers(values, fmt):
                for i in range(0, len(values), 4096):
                    if i:
                        out.write(' ')
                    out.write(' '.join(fmt(v) for v in values[i:i+4096]))
            def emit_geometry(gid, mat, values, indices, count, fmts):
                line(f'<geometry id="{gid}" name="{gid}"><mesh>')
                for (label, stride, params), data, fmt in zip((('pos',3,'XYZ'),('normal',3,'XYZ'),('uv',2,'ST')), values, fmts):
                    sid = f'{gid}-{label}'
                    out.write(f'<source id="{sid}"><float_array id="{sid}-array" count="{len(data)}">')
                    numbers(data, fmt)
                    line(f'</float_array><technique_common><accessor source="#{sid}-array" count="{len(data)//stride}" stride="{stride}">'+''.join(f'<param name="{p}" type="float"/>' for p in params)+'</accessor></technique_common></source>')
                line(f'<vertices id="{gid}-verts"><input semantic="POSITION" source="#{gid}-pos"/></vertices>')
                out.write(f'<triangles count="{count}" material="{mat}"><input semantic="VERTEX" source="#{gid}-verts" offset="0"/><input semantic="NORMAL" source="#{gid}-normal" offset="0"/><input semantic="TEXCOORD" source="#{gid}-uv" offset="0" set="0"/><p>')
                numbers(indices, str)
                line('</p></triangles></mesh></geometry>')
            line('<?xml version="1.0" encoding="utf-8"?>')
            line('<COLLADA xmlns="http://www.collada.org/2005/11/COLLADASchema" version="1.4.1">')
            line('<asset><created>2026-09-21T00:00:00Z</created><modified>2026-09-21T00:00:00Z</modified><unit name="meter" meter="1"/><up_axis>Z_UP</up_axis></asset>')
            line('<library_effects>')
            for mat in materials:
                line(f'<effect id="{mat}-fx"><profile_COMMON><technique sid="common"><lambert><diffuse><color>0.5 0.5 0.5 1</color></diffuse></lambert></technique></profile_COMMON></effect>')
            line('</library_effects><library_materials>')
            for mat in materials:
                line(f'<material id="{mat}" name="{mat}"><instance_effect url="#{mat}-fx"/></material>')
            line('</library_materials><library_geometries>')
            for is_collision, mesh in meshes:
                for mat in sorted(mesh.faces):
                    faces = mesh.faces[mat]
                    if not faces:
                        continue
                    gid = f'g{len(nodes)}'
                    name = f'Colmesh{len(nodes)}-1' if is_collision else f'part{len(nodes)}_a600'
                    nodes.append((gid, name, mat))
                    explicit = mesh.uvs[mat]
                    scale = uv_scales.get(mat, 1.)
                    if compact:
                        values, indices, written = _compact_geometry(faces, explicit, scale, origin, is_collision)
                        vertex_count += len(values[0])//3
                        triangle_count += 0 if is_collision else written
                        collision_count += written if is_collision else 0
                        if written:
                            emit_geometry(gid, mat, values, indices, written, (fmt_compact, fmt_compact, lambda v: fmt_compact(v, 4)))
                        else:
                            nodes.pop()
                        continue
                    values = [array('d'), array('d'), array('d')]
                    indices, lookup = array('I'), {}
                    ox, oy, oz = origin
                    for i, tri in enumerate(faces):
                        n = normal(cross(sub(tri[1],tri[0]), sub(tri[2],tri[0])))
                        # The rounded normal is shared by all three corners.
                        nkey = (round(n[0], 6), round(n[1], 6), round(n[2], 6))
                        vertical, side = abs(n[2]) < .5, abs(n[0]) < abs(n[1])
                        fixed = explicit[i] if i < len(explicit) else None
                        for corner, p in enumerate(tri):
                            if fixed:
                                u, v = fixed[corner]
                            elif vertical:
                                u, v = (p[0] if side else p[1])*scale, p[2]*scale
                            else:
                                u, v = p[0]*scale, p[1]*scale
                            key = (round(p[0]-ox, 6), round(p[1]-oy, 6), round(p[2]-oz, 6),
                                   *nkey, round(u, 6), round(v, 6))
                            idx = lookup.get(key)
                            if idx is None:
                                idx = len(lookup)
                                lookup[key] = idx
                                values[0].extend(key[:3]); values[1].extend(key[3:6]); values[2].extend(key[6:])
                            indices.append(idx)
                    vertex_count += len(lookup)
                    del lookup
                    emit_geometry(gid, mat, values, indices, len(faces), (lambda v: f'{v:.6f}',)*3)
            line('</library_geometries><library_visual_scenes><visual_scene id="Scene"><node id="base00" name="base00"><node id="start01" name="start01">')
            for gid, name, mat in nodes:
                line(f'<node id="node{gid}" name="{name}"><instance_geometry url="#{gid}"><bind_material><technique_common><instance_material symbol="{mat}" target="#{mat}"/></technique_common></bind_material></instance_geometry></node>')
            line('</node></node></visual_scene></library_visual_scenes><scene><instance_visual_scene url="#Scene"/></scene></COLLADA>')
        if not compact:
            triangle_count = self.count
            collision_count = collision.count if collision is not None else 0
        return {'triangles': triangle_count, 'vertices': vertex_count,
                'collision_triangles': collision_count, 'bytes': path.stat().st_size}

    def _write_legacy(self,path,origin=(0,0,0),uv_scales=None):
        """One material submesh per geometry; normals and UVs explicit. Z_UP retained.

        UVs are world metres, scaled per material so a tileable texture keeps its
        real-world size instead of repeating once per metre.
        """
        uv_scales=uv_scales or {}
        path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
        chunks=['<?xml version="1.0" encoding="utf-8"?>',
                '<COLLADA xmlns="http://www.collada.org/2005/11/COLLADASchema" version="1.4.1">',
                '<asset><created>2026-09-21T00:00:00Z</created><modified>2026-09-21T00:00:00Z</modified><unit name="meter" meter="1"/><up_axis>Z_UP</up_axis></asset>']
        mats=sorted(self.faces)
        chunks.append('<library_effects>')
        for mat in mats:
            chunks.append(f'<effect id="{mat}-fx"><profile_COMMON><technique sid="common"><lambert><diffuse><color>0.5 0.5 0.5 1</color></diffuse></lambert></technique></profile_COMMON></effect>')
        chunks.append('</library_effects><library_materials>')
        for mat in mats:
            chunks.append(f'<material id="{mat}" name="{mat}"><instance_effect url="#{mat}-fx"/></material>')
        chunks.append('</library_materials><library_geometries>')
        for num,mat in enumerate(mats):
            faces=self.faces[mat]; gid=f'g{num}'
            scale=uv_scales.get(mat,1.)
            explicit=self.uvs[mat]
            positions=[]; normals=[]; uvs=[]
            for index,tri in enumerate(faces):
                n=normal(cross(sub(tri[1],tri[0]),sub(tri[2],tri[0])))
                vertical=abs(n[2])<.5
                fixed=explicit[index] if index<len(explicit) else None
                for corner,p in enumerate(tri):
                    positions.extend(sub(p,origin)); normals.extend(n)
                    if fixed:
                        uvs.extend(fixed[corner])
                        continue
                    uv=(p[0] if abs(n[0])<abs(n[1]) else p[1], p[2]) if vertical else p[:2]
                    uvs.extend(v*scale for v in uv)
            chunks.append(f'<geometry id="{gid}" name="{gid}"><mesh>')
            for name,data,stride,params in [('pos',positions,3,'XYZ'),('normal',normals,3,'XYZ'),('uv',uvs,2,'ST')]:
                sid=f'{gid}-{name}'
                chunks.append(f'<source id="{sid}"><float_array id="{sid}-array" count="{len(data)}">'+ ' '.join(f'{v:.6f}' for v in data)+f'</float_array><technique_common><accessor source="#{sid}-array" count="{len(data)//stride}" stride="{stride}">'+''.join(f'<param name="{p}" type="float"/>' for p in params)+'</accessor></technique_common></source>')
            chunks.append(f'<vertices id="{gid}-verts"><input semantic="POSITION" source="#{gid}-pos"/></vertices>')
            chunks.append(f'<triangles count="{len(faces)}" material="{mat}"><input semantic="VERTEX" source="#{gid}-verts" offset="0"/><input semantic="NORMAL" source="#{gid}-normal" offset="0"/><input semantic="TEXCOORD" source="#{gid}-uv" offset="0" set="0"/><p>'+ ' '.join(str(i) for i in range(len(faces)*3))+'</p></triangles></mesh></geometry>')
        chunks.append('</library_geometries><library_visual_scenes><visual_scene id="Scene"><node id="base00" name="base00"><node id="start01" name="start01">')
        for num,mat in enumerate(mats):
            # Trailing pixel size is the Torque detail level. Collision uses visible mesh
            # for exact roads, and the deliberately simple building geometry.
            chunks.append(f'<node id="mesh{num}" name="part{num}_a600"><instance_geometry url="#g{num}"><bind_material><technique_common><instance_material symbol="{mat}" target="#{mat}"/></technique_common></bind_material></instance_geometry></node>')
        chunks.append('</node></node></visual_scene></library_visual_scenes><scene><instance_visual_scene url="#Scene"/></scene></COLLADA>')
        path.write_text('\n'.join(chunks),encoding='utf-8')
