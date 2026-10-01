"""Continuous low sidewalks and kerbs, built globally before spatial chunking.

The asphalt is immutable. Sidewalk footprints are clipped to its exact triangles
at the same grade. Shared pedestrian boundaries disappear in a polygon union;
rounded inward offsets form the concrete lip without individual stone objects.
"""
from collections import defaultdict
import math

import shapely
from shapely.geometry import Point, Polygon
from shapely.ops import unary_union
from shapely.strtree import STRtree

from akadem_maps.adapters.beamng.beamng_geometry import Mesh, beam_point
from akadem_maps.adapters.beamng.beamng_pavement import Pavement, polygons

HEIGHT = .035
WIDTH = .15
BEVEL = .008
MAX_STEP = 2.0
ARC_ERROR = .002
# 'compact': no 8 mm bevel (the visual kerb equals its collider), 1 cm arc sagitta on
# the 15 cm kerb corners, and patch outlines densified to MAX_STEP and then simplified
# (1 cm XY, 2 mm Z): stations remain where the height profile bends, not every 2 m.
COMPACT_XY = .01
COMPACT_ARC_ERROR = .01


def arc_segments(radius, error=ARC_ERROR):
    """Segments per quadrant for a bounded circular-arc sagitta."""
    return max(1, math.ceil(math.pi / (4 * math.acos(max(-1., 1-error/radius)))))


def simplify_patch(patch, height, xy_tolerance=1e-9):
    """Remove collinear XY boundary stations only when their Z profile agrees.

    RDP checks every discarded station against its final retained segment, so
    errors do not accumulate. XY moves at most xy_tolerance (numerical precision
    by default); ramps and lowered crossings retain their height breakpoints.
    """
    import numpy as np
    def ring(coords):
        coords = list(coords)[:-1]
        if len(coords) < 5:
            return coords
        def chain(points):
            values = np.asarray([height(x,y) for x,y in points])
            keep = {0,len(points)-1}
            stack = [(0,len(points)-1)]
            while stack:
                a,b = stack.pop()
                if b-a < 2:
                    continue
                delta = values[b,:2]-values[a,:2]
                length = float(delta@delta)
                if length < 1e-18:
                    keep.update(range(a,b+1))
                    continue
                part = values[a+1:b]
                t = np.clip((part[:,:2]-values[a,:2])@delta/length,0,1)
                projected = values[a]+t[:,None]*(values[b]-values[a])
                score = np.maximum(np.linalg.norm(part[:,:2]-projected[:,:2],axis=1)/xy_tolerance,
                                   np.abs(part[:,2]-projected[:,2])/.002)
                i = int(np.argmax(score))
                if score[i] > 1:
                    k=a+1+i
                    keep.add(k); stack.extend(((a,k),(k,b)))
            return [points[i] for i in sorted(keep)]
        half = len(coords)//2
        return chain(coords[:half+1])[:-1]+chain(coords[half:]+coords[:1])[:-1]
    rings = [ring(patch.exterior.coords)]+[ring(r.coords) for r in patch.interiors]
    if any(len(r) < 3 for r in rings):
        return patch
    candidate = Polygon(rings[0], rings[1:])
    if not candidate.is_valid or candidate.is_empty or patch.symmetric_difference(candidate).area > max(1e-7, xy_tolerance*patch.length):
        return patch
    return candidate


def _walk_sources(tiles):
    for tid, tile in tiles:
        for i, walk in enumerate(tile.get('sidewalks', [])):
            mesh = Mesh()
            mesh.strip([beam_point(p) for p in walk['points']], walk['width'], 'walk')
            yield (tid, 'sidewalk', i), walk.get('structure_level', int(walk.get('bridge', False))), mesh.faces['walk']
        for i, area in enumerate(tile.get('walkingareas', [])):
            yield (tid, 'area', i), area.get('structure_level', int(area.get('bridge', False))), [
                [beam_point(p) for p in t] for t in area['triangles']]


def build_sidewalks(tiles, pavement=None, *, optimization='balanced', collision=None):
    tiles = list(tiles)
    pavement = pavement or Pavement.from_tiles(tiles)
    crossings = []
    for _, tile in tiles:
        for mark in tile.get('markings', []):
            if mark.get('dash') == [.5, .6]:
                m = Mesh()
                m.strip([beam_point(p) for p in mark['points']], mark['width']+.5, 'crossing')
                crossings.extend(m.faces['crossing'])
    crossing_index = Pavement(crossings)
    groups = defaultdict(list)
    for key, grade, tris in _walk_sources(tiles):
        if tris:
            groups[grade].append((key, Pavement(tris)))
    # Old snapshots lost the structural flag on walking areas. Even within a
    # nominal layer, separate footprints that overlap in XY at different Z.
    # This also handles two decks tagged with the same OSM layer.
    separated = defaultdict(list)
    for grade,sources in groups.items():
        shapes=[unary_union(source.polygons) for _,source in sources]
        tree=STRtree(shapes)
        colors=[]
        for i,((key,source),shape) in enumerate(zip(sources,shapes)):
            forbidden=set()
            for j in tree.query(shape,predicate='intersects'):
                if j>=i: continue
                q=shape.intersection(shapes[j]).representative_point()
                if q.is_empty: continue
                other=sources[j][1]
                z=source.z(int(source.tree.nearest(q)),q.x,q.y)
                oz=other.z(int(other.tree.nearest(q)),q.x,q.y)
                if abs(z-oz)>.65: forbidden.add(colors[j])
            color=0
            while color in forbidden: color+=1
            colors.append(color)
            separated[(grade,color)].append((key,source))
    groups=separated
    mesh = Mesh()
    audit = {'height_m': HEIGHT, 'max_height_m': .04, 'width_m': WIDTH,
             'source': 'synthetic low-kerb profile', 'patches': 0, 'curb_length_m': 0,
             'clipped_area_m2': 0, 'max_contact_rise_m':0.0, 'unresolved': []}
    for grade, sources in sorted(groups.items()):
        clean, all_tris = [], []
        for source_n, (key, source) in enumerate(sources):
            if source_n % 1000 == 0:
                print(f'    sidewalk grade={grade} clipping {source_n}/{len(sources)}', flush=True)
            shape = unary_union(source.polygons)
            if shape.is_empty:
                continue
            # Legacy walking areas were cut 5 cm away from the road. Extend only
            # that narrow seam, then cut the exact asphalt (never inflate asphalt).
            if key[1] == 'area':
                shape = shape.buffer(.05, join_style='round', quad_segs=8)
            cuts = []
            for i in pavement.tree.query(shape, predicate='intersects'):
                hit = shape.intersection(pavement.polygons[i])
                p = hit.representative_point()
                wi = int(source.tree.nearest(p))
                if abs(source.z(wi, p.x, p.y)-pavement.z(i, p.x, p.y)) < .65:
                    cuts.append(pavement.polygons[i])
            clipped = shape.difference(unary_union(cuts)) if cuts else shape
            audit['clipped_area_m2'] += max(0, shape.area-clipped.area)
            clean.extend(polygons(shapely.make_valid(clipped)))
            all_tris.extend(source.triangles)
        if not clean:
            continue
        walk = Pavement(all_tris)
        # A different structural level is never unioned in XY with this one.
        merged = unary_union(clean)
        for patch_n, patch in enumerate(polygons(merged)):
            patch = shapely.orient_polygons(patch)
            if patch_n % 100 == 0:
                print(f'    sidewalk grade={grade} meshing patch {patch_n}', flush=True)
            audit['patches'] += 1
            # Inward round offsets fit corners without miter spikes. The 16-way
            # quarter circles have <1 mm sagitta at this profile width.
            cache = {}
            lifts = {}
            patch_boundary = patch.boundary

            def vertex(x, y, lip=False):
                xy = (round(x, 8), round(y, 8), lip)
                if xy in cache:
                    return cache[xy]
                pt = Point(x, y)
                wi = int(walk.tree.nearest(pt))
                base = walk.z(wi, x, y)
                road = pavement.nearest((x, y, base), distance=2.5)
                # Match the road plane through the complete kerb cross-section,
                # then blend back to the pedestrian surface away from the edge.
                if road:
                    distance, _, ri = road
                    road_z = pavement.z(ri, x, y)
                    blend = max(0, min(1, (distance-WIDTH)/2))
                    base = road_z*(1-blend)+base*blend
                # End caps and crossings are flush; transition over one metre.
                # The boundary lies away from asphalt at these open connections.
                boundary_dist = pt.distance(patch_boundary)
                if road:
                    raised = 1
                else:
                    raised = min(1, boundary_dist)
                crossing = crossing_index.nearest((x, y, base), distance=1.5)
                if crossing:
                    raised = min(raised, min(1, max(0, crossing[0]-.25)))
                lift = HEIGHT*raised
                if road and road[0]<.02:
                    rise=base+lift-pavement.z(road[2],x,y)
                    audit['max_contact_rise_m']=max(audit['max_contact_rise_m'],rise)
                    if rise>.040001:
                        audit['unresolved'].append({'position':[x,y,base],'rise_m':rise})
                lifts[xy[:2]] = lift
                if lip:
                    lift = max(0, lift-BEVEL)
                cache[xy] = (x, y, base+lift)
                return cache[xy]

            compact = optimization == 'compact'
            if optimization != 'legacy':
                # compact: densify first, so the 2 mm height check (not the 2 m step)
                # decides which stations along long edges remain.
                patch = (simplify_patch(shapely.segmentize(patch, MAX_STEP), vertex, COMPACT_XY) if compact
                         else simplify_patch(patch, vertex))
            inner = patch.buffer(-WIDTH, join_style='round', quad_segs=16 if optimization == 'legacy' else
                                 arc_segments(WIDTH, COMPACT_ARC_ERROR if compact else ARC_ERROR))
            if compact:
                layers = [(mesh, inner, 'kyiv_concrete', False),
                          (mesh, patch.difference(inner), 'kyiv_curb', False)]
            else:
                bevel_inner = patch.buffer(-BEVEL, join_style='round', quad_segs=16 if optimization == 'legacy' else arc_segments(BEVEL))
                curb_top = bevel_inner.difference(inner)
                bevel = patch.difference(bevel_inner)
                layers = [(mesh, inner, 'kyiv_concrete', False),
                          (mesh, curb_top, 'kyiv_curb', False),
                          (mesh, bevel, 'kyiv_curb', True)]
            if collision is not None:
                layers += [(collision, inner, 'kyiv_concrete', False),
                           (collision, patch.difference(inner), 'kyiv_curb', False)]
            for target, geom, material, lip in layers:
                for pg in polygons(geom):
                    if not compact:
                        pg = shapely.segmentize(pg, MAX_STEP)
                    for tri in shapely.constrained_delaunay_triangles(pg).geoms:
                        pts = list(tri.exterior.coords)[:3]
                        # Bevel height rises with inward distance over 8 mm.
                        vertices = []
                        for x, y in pts:
                            v = vertex(x, y)
                            if lip:
                                v = (x, y, v[2]-min(lifts[(round(x,8),round(y,8))],
                                                  max(0, BEVEL-Point(x,y).distance(patch_boundary))))
                            vertices.append(v)
                        target.tri(material, *vertices, up=True)
            for ring in [patch.exterior, *patch.interiors]:
                points = list((ring if compact else shapely.segmentize(ring, MAX_STEP)).coords)
                for a, b in zip(points, points[1:]):
                    va, vb = vertex(*a), vertex(*b)
                    mid = tuple((va[k]+vb[k])/2 for k in range(3))
                    road = pavement.nearest((mid[0], mid[1], mid[2]-HEIGHT), distance=.08)
                    if not road:
                        continue
                    za = va[2]-lifts[(round(a[0],8),round(a[1],8))]
                    zb = vb[2]-lifts[(round(b[0],8),round(b[1],8))]
                    # At road-facing boundaries enforce the cap relative to the
                    # same triangle used by the wheels, including on slopes.
                    ca = crossing_index.nearest((a[0], a[1], za), distance=1.5)
                    cb = crossing_index.nearest((b[0], b[1], zb), distance=1.5)
                    ha = HEIGHT*(min(1, max(0, ca[0]-.25)) if ca else 1)
                    hb = HEIGHT*(min(1, max(0, cb[0]-.25)) if cb else 1)
                    bevel_drop = 0 if compact else BEVEL
                    va = (a[0], a[1], za+max(0, ha-bevel_drop))
                    vb = (b[0], b[1], zb+max(0, hb-bevel_drop))
                    ba, bb = (a[0], a[1], za), (b[0], b[1], zb)
                    mesh.tri('kyiv_curb', ba, bb, vb)
                    mesh.tri('kyiv_curb', ba, vb, va)
                    if collision is not None:
                        ca = (a[0], a[1], za+ha)
                        cb = (b[0], b[1], zb+hb)
                        collision.tri('kyiv_curb', ba, bb, cb)
                        collision.tri('kyiv_curb', ba, cb, ca)
                    audit['curb_length_m'] += math.dist(a, b)
    audit['triangles'] = mesh.count
    audit['collision_triangles'] = collision.count if collision is not None else mesh.count
    audit['arc_error_m'] = {'legacy': None, 'compact': COMPACT_ARC_ERROR}.get(optimization, ARC_ERROR)
    return mesh, audit
