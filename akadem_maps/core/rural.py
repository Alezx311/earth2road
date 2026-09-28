"""Opt-in rural rendering. Geometry is OSM; untagged appearance is synthetic.

No runtime dependency on downloaded assets. Roofs preserve footprints, and fences
are clipped against the full map road/building set before tiling.
"""
import hashlib
import math
import xml.etree.ElementTree as ET

from shapely.geometry import LineString, Point, Polygon
from shapely.ops import split, unary_union
from akadem_maps.core import scene


def enabled(cfg):
    return cfg.get('visual_profile') == 'rural'


def surface(tags):
    value = tags.get('surface', '')
    if value in ('gravel', 'fine_gravel', 'compacted', 'pebblestone'):
        return 'gravel'
    if value in ('dirt', 'earth', 'ground', 'sand', 'grass', 'mud', 'unpaved'):
        return 'dirt'
    if value:
        return 'road'
    return 'dirt' if tags.get('highway') == 'track' else 'road'


def accessible_track(tags):
    if tags.get('highway') != 'track':
        return False
    access = next((tags[k] for k in ('motorcar', 'motor_vehicle', 'vehicle', 'access') if k in tags), 'yes')
    return access not in ('no', 'private', 'agricultural', 'forestry')


def configure_types(path):
    root = ET.parse(path).getroot()
    for t in root.findall('type'):
        kind = t.get('id', '')
        if kind in ('highway.residential', 'highway.unclassified', 'highway.living_street'):
            t.set('speed', '8.33')  # assumed 30 km/h where no explicit OSM maxspeed
            t.set('width', '2.75')
            t.attrib.pop('sidewalkWidth', None)
        if kind == 'highway.track':
            t.attrib.pop('disallow', None)
            t.attrib.update(allow='passenger pedestrian bicycle', speed='5.56', width='2.5', numLanes='1', oneway='false')
    ET.ElementTree(root).write(path, encoding='utf-8', xml_declaration=True)


def prepare_tracks(root):
    """Keep accessible tracks; forbidden tracks remain non-motor scenery only."""
    for w in root.findall('way'):
        tags = {t.get('k'): t.get('v') for t in w.findall('tag')}
        # SUMO splits an unqualified lanes=1 between both directions, producing
        # 1.4 m lanes. A 5 m shared village carriageway is an explicit assumption
        # when OSM has no width; retain the original lane-count observation.
        if (tags.get('highway') in ('residential','unclassified') and tags.get('lanes')=='1'
                and tags.get('oneway','no') not in ('yes','1','true','-1') and 'width' not in tags):
            ET.SubElement(w,'tag',k='width',v='5.0')
            ET.SubElement(w,'tag',k='akadem:width_source',v='assumed rural shared carriageway')
        if tags.get('highway') == 'track' and not accessible_track(tags):
            ET.SubElement(w, 'tag', k='motorcar', v='no')


def cover(tags):
    use = tags.get('landuse')
    if use in ('farmland', 'farmyard'):
        return 'farmland' if use == 'farmland' else 'yard'
    if use in ('orchard', 'vineyard'):
        return 'orchard'
    if use == 'allotments':
        return 'garden'
    if tags.get('leisure') == 'garden':
        return 'garden'
    return None


def roof(item, tags):
    """Gable surfaces split on the ridge, within the exact original footprint.

    Height is total height; walls stop below the roof. Complex outlines retain
    their silhouette instead of replacing them with bounding rectangles.
    """
    pts = item['points']
    poly = Polygon([(p[0], p[2]) for p in pts])
    kind = tags.get('building') or item.get('building_type') or 'yes'
    if poly.is_empty or not poly.is_valid or poly.area < 8 or item.get('base', 0):
        return
    item['visual_profile'] = 'rural'
    seed = int(hashlib.sha256(str(item['id']).encode()).hexdigest()[:8], 16)
    if not item.get('visual_family'):
        item['visual_family'] = 'brick' if seed % 3 == 0 else 'insulated'
    if poly.area < 35 and item.get('height_source') in ('assumed','enriched_assumed'):
        item['height'] = 3.0
        item['levels'] = 1
    shape = tags.get('roof:shape', 'gabled' if item['height'] <= 12 and kind != 'apartments' else 'flat')
    item['roof_source'] = 'osm' if 'roof:shape' in tags else 'synthetic'
    if shape not in ('gabled', 'hipped', 'pyramidal'):
        return
    ring = list(poly.minimum_rotated_rectangle.exterior.coords)
    a, b = max(zip(ring, ring[1:]), key=lambda pair: Point(pair[0]).distance(Point(pair[1])))
    dx, dz = b[0]-a[0], b[1]-a[1]
    size = math.hypot(dx, dz)
    normal = (-dz/size, dx/size)
    origin = poly.centroid
    values = [(x-origin.x)*normal[0]+(z-origin.y)*normal[1] for x,z in poly.exterior.coords]
    lo, hi = min(values), max(values)
    half, mid = (hi-lo)/2, (hi+lo)/2
    if half < 0.5:
        return
    rise = min(2.2, half*0.45, item['height']*0.35)
    floor = max(p[1] for p in pts)
    item['floor_height'] = floor
    item['wall_height'] = item['height']-rise
    base = floor+item['wall_height']
    def xyz(x, z):
        u = (x-origin.x)*normal[0]+(z-origin.y)*normal[1]-mid
        return [round(x,3), round(base+rise*max(0,1-abs(u)/half),3), round(z,3)]
    cx, cz = origin.x+mid*normal[0], origin.y+mid*normal[1]
    axis = (dx/size, dz/size)
    reach = size*4+100
    ridge = LineString([(cx-reach*axis[0],cz-reach*axis[1]), (cx+reach*axis[0],cz+reach*axis[1])])
    pieces = split(poly, ridge)
    item['roof_triangles'] = [[xyz(x,z) for x,z in tri] for part in pieces.geoms for tri in scene.triangles(part)]
    item['roof_material'] = 'roof_tile' if seed % 3 == 0 else 'roof_metal'
    # Split gable edges at the ridge, too: no triangle may bridge the apex.
    sides = split(poly.boundary, ridge)
    faces = []
    for line in sides.geoms:
        coords = list(line.coords)
        for p,q in zip(coords,coords[1:]):
            up, uq = xyz(*p), xyz(*q)
            bp, bq = [p[0],base,p[1]], [q[0],base,q[1]]
            for tri in ([bp,bq,uq], [bp,uq,up]):
                if max(v[1] for v in tri)-base > 0.002:
                    # world.tri uses facing_up=false for gable faces.
                    faces.append(tri)
    item['roof_gables'] = faces
    item['roof_shape_rendered'] = 'gabled'
    if shape != 'gabled':
        item['roof_source'] = 'synthetic approximation of '+shape


def dress(buildings, way_tags, root, nodes, net, point, road_cut, area):
    """Return fences and trees in global map coordinates; no per-tile blind spots."""
    # Reconstruct network XY from game points using the supplied centre conversion.
    zero = point(0,0)
    def poly_xy(b):
        return Polygon([(p[0]-zero[0], zero[2]-p[2]) for p in b['points']])
    footprint = unary_union([poly_xy(b) for b in buildings]) if buildings else Polygon()
    forbidden = unary_union([road_cut.buffer(1.2), footprint.buffer(0.8)])
    fences, trees, gardens = [], [], []
    seen = Polygon()
    for b in buildings:
        tags = way_tags.get(str(b['id']), {})
        roof(b, tags)
        kind = tags.get('building') or b.get('building_type') or 'yes'
        if kind not in ('yes', 'house', 'detached', 'residential', 'microsoft', 'overture') or b['height'] > 8:
            continue
        plot = poly_xy(b)
        if not 35 < plot.area < 450:
            continue
        ring = plot.minimum_rotated_rectangle.buffer(4, join_style=2)
        if not area.covers(ring):
            continue
        # Keep a wide doorway/driveway opening toward the nearest road.
        from shapely.ops import nearest_points
        home, street = nearest_points(plot.centroid, road_cut)
        entry = LineString([home,street]).buffer(2.5)
        garden = ring.difference(unary_union([forbidden,entry,seen]))
        if not garden.is_empty:
            gardens.append({'id':'garden_'+str(b['id']), 'kind':'garden','poly':garden,
                            'provenance':'synthetic garden near observed footprint; parcel unknown'})
            # One modest garden tree, not a claim of an observed tree position.
            location = garden.representative_point()
            if location.distance(forbidden)>1.2:
                trees.append(point(location.x,location.y))
        lines = ring.boundary.difference(unary_union([forbidden, entry, seen]))
        for line in ([lines] if lines.geom_type == 'LineString' else getattr(lines,'geoms',[])):
            if line.geom_type != 'LineString' or line.length < 2:
                continue
            fences.append({'id':str(b['id']), 'points':[point(x,y) for x,y in line.coords],
                           'height':1.1, 'provenance':'synthetic setback fence; parcel unknown'})
        seen = unary_union([seen, ring.buffer(0.5)])
    # Observed shelterbelts are lines, not forests. Fill their lines at a fixed spacing.
    for w in root.findall('way'):
        tags = {t.get('k'):t.get('v') for t in w.findall('tag')}
        coords = [net.convertLonLat2XY(*nodes[n.get('ref')]) for n in w.findall('nd') if n.get('ref') in nodes]
        if len(coords) < 2:
            continue
        if tags.get('natural') == 'tree_row':
            line = LineString(coords).intersection(area)
            for part in ([line] if line.geom_type=='LineString' else getattr(line,'geoms',[])):
                if part.geom_type != 'LineString': continue
                for i in range(int(part.length/9)+1):
                    p = part.interpolate(i*9)
                    if not forbidden.covers(p): trees.append(point(p.x,p.y))
        if tags.get('barrier') in ('fence','wall','hedge'):
            line = LineString(coords).intersection(area).difference(road_cut.buffer(1.2))
            for part in ([line] if line.geom_type=='LineString' else getattr(line,'geoms',[])):
                if part.geom_type=='LineString' and part.length>1:
                    fences.append({'id':w.get('id'), 'points':[point(x,y) for x,y in part.coords],
                                   'height':1.2,'provenance':'osm alignment; assumed height'})
    return fences, trees, gardens


def relation_covers(root, nodes, to_xy, clip):
    """OSM multipolygon landcover, including the estuary's shoreline and holes."""
    from shapely.ops import polygonize
    ways = {w.get('id'):w for w in root.findall('way')}
    result = []
    for rel in root.findall('relation'):
        tags = {t.get('k'):t.get('v') for t in rel.findall('tag')}
        kind = 'water' if tags.get('natural') in ('water','bay') else cover(tags)
        if not kind: continue
        rings = {'outer':[], 'inner':[]}
        for member in rel.findall('member'):
            w = ways.get(member.get('ref')) if member.get('type')=='way' else None
            if w is None: continue
            refs = [n.get('ref') for n in w.findall('nd')]
            if len(refs)<2 or any(r not in nodes for r in refs): continue
            rings['inner' if member.get('role')=='inner' else 'outer'].append(LineString([nodes[r] for r in refs]))
        outer = unary_union(list(polygonize(rings['outer'])))
        inner = unary_union(list(polygonize(rings['inner'])))
        if outer.is_empty: continue
        from shapely.ops import transform
        local = outer.difference(inner).intersection(clip)
        if local.is_empty: continue
        result.append({'id':'relation_'+rel.get('id'), 'kind':kind,
                       'poly':transform(lambda x,y,z=None: to_xy(x,y),local),
                       'provenance':'osm multipolygon'})
    return result


def clip_roads(root, area):
    """Clip boundary-map roads before SUMO; keep shared in-area OSM node IDs.

    netconvert's boundary option selects entire edges, including kilometres
    beyond the playable ground. Synthetic cut nodes terminate them at the edge.
    """
    import copy
    nodes = {n.get('id'):n for n in root.findall('node')}
    coordinates = {nid:(float(n.get('lon')),float(n.get('lat'))) for nid,n in nodes.items()}
    lookup = {tuple(round(v,7) for v in p):nid for nid,p in coordinates.items()}
    next_id = 9_000_000_000_000
    report = {'ways_clipped':0,'cut_nodes':0,'ways_removed':0,'provenance':'derived map boundary cuts'}
    for way in list(root.findall('way')):
        tags = {t.get('k'):t.get('v') for t in way.findall('tag')}
        if 'highway' not in tags: continue
        refs = [n.get('ref') for n in way.findall('nd')]
        if len(refs)<2 or any(r not in coordinates for r in refs): continue
        line = LineString([coordinates[r] for r in refs])
        if area.covers(line): continue
        cut = line.intersection(area)
        parts = [cut] if cut.geom_type=='LineString' else [p for p in getattr(cut,'geoms',[]) if p.geom_type=='LineString']
        parts = [p for p in parts if p.length>1e-7]
        root.remove(way)
        if not parts:
            report['ways_removed']+=1
            continue
        report['ways_clipped']+=1
        for i,part in enumerate(parts):
            new = copy.deepcopy(way)
            if i:
                new.set('id',str(next_id)); next_id+=1
            for nd in list(new.findall('nd')): new.remove(nd)
            for x,y in part.coords:
                key = (round(x,7),round(y,7))
                nid = lookup.get(key)
                if nid is None:
                    nid=str(next_id); next_id+=1
                    root.insert(0,ET.Element('node',id=nid,lon=str(x),lat=str(y)))
                    lookup[key]=nid
                    report['cut_nodes']+=1
                ET.SubElement(new,'nd',ref=nid)
            root.append(new)
    return report
