"""MIT synthetic junction proving ground, generated from small parametric cases."""
import hashlib
import json
import math
from pathlib import Path
import shutil
import xml.etree.ElementTree as ET

import numpy as np
from PIL import Image

from akadem_maps.context import write_json, sha256, RESOURCES

CASES = [
    {'id':'t_regular', 'angles':[0,90,180]},
    {'id':'t_oblique', 'angles':[0,65,180]},
    {'id':'t_acute', 'angles':[0,30,180]},
    {'id':'t_multilane', 'angles':[0,90,180], 'lanes':[4,2,4]},
    {'id':'x_regular', 'angles':[0,90,180,270]},
    {'id':'x_skew', 'angles':[0,60,180,240]},
    {'id':'x_unequal', 'angles':[0,90,180,270], 'lanes':[2,4,2,4]},
    {'id':'x_oneway', 'angles':[0,90,180,270], 'flow':['in','out','out','in']},
    {'id':'y_regular', 'angles':[0,120,240]},
    {'id':'y_asymmetric', 'angles':[0,105,225]},
    {'id':'y_acute', 'angles':[0,35,200]},
    {'id':'merge', 'angles':[180,-25,25], 'flow':['out','in','in']},
    {'id':'split', 'angles':[180,-25,25], 'flow':['in','out','out']},
    {'id':'width_transition', 'angles':[0,180], 'lanes':[2,4]},
    {'id':'curved_approach', 'angles':[0,90,180], 'curve':8},
    {'id':'grade_longitudinal', 'angles':[0,90,180], 'slope':[.04,0]},
    {'id':'grade_cross', 'angles':[0,90,180,270], 'slope':[0,.03]},
    {'id':'grade_change', 'angles':[0,120,240], 'slope':[.025,.025]},
    {'id':'short_transition', 'angles':[0,90,180], 'length':18, 'expected':'fallback'},
    {'id':'close_junctions', 'angles':[0,90,180], 'special':'close', 'expected':'fallback'},
    {'id':'divided_island', 'angles':[0,12,90,180], 'expected':'fallback'},
    {'id':'roundabout', 'angles':[0,90,180,270], 'special':'roundabout', 'expected':'fallback'},
    {'id':'five_arms', 'angles':[0,72,144,216,288], 'expected':'fallback'},
    {'id':'overpass', 'angles':[0,90,180,270], 'special':'overpass', 'expected':'fallback'},
]


def fixture(output, case='all', mode='v2', tolerance=.02):
    """Create a fresh, fully pinned offline input bundle; no downloaded data."""
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    selected = CASES if case == 'all' else [c for c in CASES if c['id'] == case]
    if not selected:
        raise ValueError('Unknown lab case: '+case)
    root = ET.Element('osm', version='0.6', generator='Earth2Road roadgen lab (synthetic MIT)')
    lon0, lat0 = 30.345, 50.446
    coordinates, next_node, next_way = {}, 1000, 10000
    def node(x, y):
        nonlocal next_node
        nid = str(next_node)
        next_node += 1
        coordinates[nid] = (x, y)
        ET.SubElement(root, 'node', id=nid, lon=f'{lon0+x/71000:.10f}', lat=f'{lat0+y/111200:.10f}')
        return nid
    def way(refs, tags=None):
        nonlocal next_way
        wid = str(next_way)
        next_way += 1
        w = ET.SubElement(root, 'way', id=wid)
        for nid in refs:
            ET.SubElement(w, 'nd', ref=nid)
        for k,v in {'highway':'residential','lanes':'2','maxspeed':'40', **(tags or {})}.items():
            ET.SubElement(w, 'tag', k=k, v=str(v))
        return wid
    catalogue, connectors = [], []
    for index, spec in enumerate(selected):
        cx, cy = 100+(index%6)*200, 100+(index//6)*200
        center = node(cx, cy)
        centers, ends, ids = [center], [], []
        ring = []
        if spec.get('special') == 'roundabout':
            # Mapped roundabouts carry a node every few metres; a node per arm
            # only would draw straight chords (a diamond), not a circle.
            circle = {a: node(cx+15*math.cos(math.radians(a)),cy+15*math.sin(math.radians(a)))
                      for a in sorted(set(range(0,360,15)) | set(spec['angles']))}
            ids.append(way([*circle.values(), next(iter(circle.values()))],
                           {'junction':'roundabout','oneway':'yes','lanes':1}))
            ring = [circle[a] for a in spec['angles']]
            centers = ring
        if spec.get('special') == 'overpass':
            centers.append(node(cx,cy))  # geometrically coincident, topologically separate
        for i, angle in enumerate(spec['angles']):
            rad = math.radians(angle)
            u, v = (math.cos(rad), math.sin(rad)), (-math.sin(rad), math.cos(rad))
            length = spec.get('length', 70)
            origin = ring[i] if ring else (centers[1] if spec.get('special')=='overpass' and i%2 else center)
            pts = [origin]
            for step in (.35, .65, 1.):
                lateral = spec.get('curve',0)*math.sin(step*math.pi)
                pts.append(node(cx+u[0]*length*step+v[0]*lateral, cy+u[1]*length*step+v[1]*lateral))
            ends.append(pts[-1])
            flow = spec.get('flow',['both']*len(spec['angles']))[i]
            tags = {'lanes':spec.get('lanes',[2]*len(spec['angles']))[i], 'sidewalk':'both'}
            if flow != 'both':
                tags['oneway'] = 'yes'
                if flow == 'in':
                    pts.reverse()
            if spec.get('special') == 'overpass' and i%2:
                tags.update(bridge='yes', layer='1')
            ids.append(way(pts,tags))
        if spec.get('special') == 'close':
            other = node(cx+28,cy)
            # A second branch sharing the first approach's intermediate OSM node.
            first = next(w for w in root.findall('way') if w.get('id')==ids[0])
            junction = first.findall('nd')[1].get('ref')
            ids.append(way([junction,other,node(cx+28,cy-65)]))
            centers.append(junction)
        connector = node(cx+90,cy+90)
        ex,ey=coordinates[ends[0]]
        # Route around the case: a west-facing first arm (merge/split) would
        # otherwise send the connector straight through the junction unconnected.
        bends=[node(cx+90,ey)] if ex>cx else [node(cx-90,ey),node(cx-90,cy+60)]
        way([ends[0],*bends,connector], {'highway':'service','sidewalk':'no'})
        if spec.get('special') == 'overpass':
            # Attach the elevated component outside the crossing itself.
            way([ends[1],node(cx+85,cy+75),connector], {'highway':'service'})
        connectors.append(connector)
        catalogue.append({**spec, 'center_xy':[cx,cy], 'source_nodes':centers,
                          'source_ways':ids, 'expected':spec.get('expected','v2')})
    for i, connector in enumerate(connectors):
        if i%6:
            way([connectors[i-1],connector], {'highway':'service','sidewalk':'no'})
        elif i>=6:
            way([connectors[i-6],connector], {'highway':'service','sidewalk':'no'})
    # Single cases still need a >=120 m spawn approach in the existing pipeline.
    last = connectors[-1]
    x,y=coordinates[last]
    way([last,node(x+160,y)], {'highway':'residential','sidewalk':'no'})
    xs,ys=zip(*coordinates.values())
    bbox=[lon0+(min(xs)-25)/71000,lat0+(min(ys)-25)/111200,
          lon0+(max(xs)+25)/71000,lat0+(max(ys)+25)/111200]
    cfg={'id':'roadgen_lab' if case=='all' else 'roadgen_'+case, 'name':'Roadgen junction laboratory',
         'bbox':bbox,'center':[(bbox[0]+bbox[2])/2,(bbox[1]+bbox[3])/2],
         'seed':311,'source_kind':'synthetic','input_provenance':'Parametric synthetic streets and analytic DEM; MIT',
         'region_profile':'experimental','terrain_zoom':15,'demand_pool':5,
         'road_geometry':{'mode':mode,'curve_tolerance_m':tolerance},'osm_file':'lab.osm'}
    raw=output/'raw'
    raw.mkdir()
    root[:] = root.findall('node')+root.findall('way')
    ET.ElementTree(root).write(raw/'lab.osm',encoding='utf-8',xml_declaration=True)
    # A procedural height tile is an input fixture, not a special runtime terrain provider.
    def merc(lon,lat):
        return ((lon+180)/360*32768,(1-math.asinh(math.tan(math.radians(lat)))/math.pi)/2*32768)
    west,north=merc(bbox[0],bbox[3]); east,south=merc(bbox[2],bbox[1])
    for tx in range(math.floor(west),math.floor(east)+1):
        for ty in range(math.floor(north),math.floor(south)+1):
            xx,yy=np.meshgrid(tx+np.arange(256)/255,ty+np.arange(256)/255)
            lon=xx/32768*360-180
            lat=np.degrees(np.arctan(np.sinh(math.pi*(1-2*yy/32768))))
            px,py=(lon-lon0)*71000,(lat-lat0)*111200
            height=np.full((256,256),100.)
            for c in catalogue:
                if 'slope' not in c: continue
                dx,dy=px-c['center_xy'][0],py-c['center_xy'][1]
                fade=np.clip((95-np.maximum(abs(dx),abs(dy)))/20,0,1)
                height+=(c['slope'][0]*dx+c['slope'][1]*dy)*fade
            encoded=np.rint((height+32768)*256).astype(np.int64)
            rgb=np.stack([(encoded>>16)&255,(encoded>>8)&255,encoded&255],axis=-1).astype(np.uint8)
            target=raw/f'terrain/15/{tx}/{ty}.png'; target.parent.mkdir(parents=True,exist_ok=True)
            Image.fromarray(rgb).save(target)
    resources=output/'resources'; resources.mkdir()
    for name in ('osm_types.typ.xml','building_sources.json'):
        shutil.copy2(RESOURCES/name,resources/name)
    for name,value in {'corrections.json':{'ways':{}},'style.json':{'overrides':{}},
                       'shots.json':{'shots':[]},'landmarks.json':{'by_id':{}}}.items():
        write_json(resources/name,value)
    write_json(output/'config.json',cfg)
    write_json(output/'cases.json',catalogue)
    write_json(output/'manifest.json', {'files':{p.relative_to(output).as_posix():sha256(p)
               for p in sorted(output.rglob('*')) if p.is_file()}, 'tools':{'fixture':'roadgen-lab-v1'}})
    return cfg, catalogue
