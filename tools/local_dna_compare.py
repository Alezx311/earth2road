"""Compare immutable A/B worlds, draw an influence map and pin eight BeamNG cameras.

Usage: python tools/local_dna_compare.py BASELINE STYLED --output NEW_DIRECTORY
Optional --capture runs both public BeamNG exports in isolated profiles (Windows).
"""
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from akadem_maps.context import read_json, write_json
from akadem_maps.world import validate_world
from akadem_maps.core.local_dna import Field


def digest(v):
    return hashlib.sha256(json.dumps(v, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def world(path):
    validate_world(path)
    index = read_json(path/'index.json')
    tiles = [read_json(path/'tiles'/f'{name}.json') for name in sorted(index['tiles'])]
    return index, tiles


def influence(report, tiles, dest):
    from PIL import Image, ImageDraw
    positions = {(a['lon'],a['lat']): a['position'] for a in report['visual_anchors']}
    f = Field(dict(version=1, profiles=report['profiles'], anchors=report['visual_anchors']),
              lambda lon,lat: positions[(lon,lat)], report['seed'])
    colors = [(215,190,131),(145,157,167),(133,171,191),(154,119,95)]
    ids = list(report['profiles'])
    colors = {pid: colors[i % len(colors)] for i,pid in enumerate(ids)}
    image = Image.new('RGB',(800,860),'white')
    px = image.load()
    for j in range(800):
        for i in range(800):
            weights = f.weights((i-400)*2.5,(j-400)*2.5)
            px[i,j] = tuple(round(sum(w*colors[a['profile']][c] for a,w in weights)) for c in range(3)) if weights else (220,220,220)
    draw = ImageDraw.Draw(image)
    for tile in tiles:
        for b in tile['buildings']:
            draw.polygon([(400+p[0]/2.5,400+p[2]/2.5) for p in b['points']], outline=(70,70,70))
    for a in report['visual_anchors']:
        x,y=400+a['position'][0]/2.5,400+a['position'][2]/2.5
        draw.ellipse((x-4,y-4,x+4,y+4),fill=(255,255,255),outline='black')
    draw.text((12,808),'Manual DNA hypotheses; circles = visual anchors; outlines = OSM buildings',fill='black')
    for i,(pid,color) in enumerate(colors.items()):
        draw.rectangle((12+i*195,834,26+i*195,848),fill=color)
        draw.text((32+i*195,834),pid,fill='black')
    image.save(dest)


def cameras(index, tiles):
    def beam(p): return [p[0],-p[2],p[1]]
    spawn = beam(index['spawn']['position'])
    views=[{'name':'overview','pos':[spawn[0]-350,spawn[1]-450,spawn[2]+450],'look':spawn},
           {'name':'roofs','pos':[spawn[0]+100,spawn[1]-220,spawn[2]+110],'look':spawn}]
    buildings=[b for t in tiles for b in t['buildings'] if b.get('local_style',{}).get('architecture') == 'historic' and 6 <= b['height'] <= 24]
    if not buildings:
        buildings=[b for t in tiles for b in t['buildings']]
    lanes=[p for l in index['lanes'] if not l.get('internal') for p in l['points']]
    used=[]
    for n in range(6):
        angle=n*math.tau/6
        target=(math.cos(angle)*550,math.sin(angle)*550)
        candidates=[b for b in buildings if b['id'] not in used] or buildings
        b=min(candidates,key=lambda b: math.dist(target,(sum(p[0] for p in b['points'])/len(b['points']),sum(p[2] for p in b['points'])/len(b['points']))))
        used.append(b['id'])
        x,z=sum(p[0] for p in b['points'])/len(b['points']),sum(p[2] for p in b['points'])/len(b['points'])
        road=min(lanes,key=lambda p: abs(math.dist((x,z),(p[0],p[2]))-30))
        # Prefer a nearby lane rather than another road on the 30 m circle.
        near=[p for p in lanes if 15 <= math.dist((x,z),(p[0],p[2])) <= 60]
        if near: road=min(near,key=lambda p: math.dist((x,z),(p[0],p[2])))
        pos=beam(road); pos[2]+=2.2
        views.append({'name':f'street_{n+1:02d}','pos':pos,'look':[x,-z,min(p[1] for p in b['points'])+min(8,b['height']*.5)]})
    return views


def compare(a, b, output):
    ia,ta=world(a); ib,tb=world(b)
    checks={'network_sha256':ia['network_sha256']==ib['network_sha256']}
    checks['osm_sha256'] = read_json(a/'sources.json')['osm_sha256'] == read_json(b/'sources.json')['osm_sha256']
    def dem(path):
        return {k:v for k,v in read_json(path/'inputs/manifest.json')['files'].items() if k.startswith('raw/terrain/')}
    checks['dem_sha256'] = dem(a) == dem(b)
    for key in ('lanes','spawn','signals','tls'):
        checks[key]=digest(ia.get(key))==digest(ib.get(key))
    for key in ('road_strips','junctions','sidewalks','walkingareas','markings','paths'):
        left=sorted((v for t in ta for v in t.get(key,[])),key=digest)
        right=sorted((v for t in tb for v in t.get(key,[])),key=digest)
        checks[key]=digest(left)==digest(right)
    def outlines(tiles):
        return sorted((str(b['id']),b['points'],b.get('base',0)) for t in tiles for b in t['buildings'])
    checks['building_footprints']=digest(outlines(ta))==digest(outlines(tb))
    def observed(tiles):
        return sorted((str(b['id']),b['height']) for t in tiles for b in t['buildings'] if b['height_source'] in ('height','levels'))
    checks['observed_heights']=observed(ta)==observed(tb)
    base_trees = {tuple(p) for t in ta for p in t['trees']}
    osm_trees = {tuple(r['position']) for t in tb for r in t.get('tree_records',[]) if r['provenance']=='osm'}
    checks['osm_tree_positions_retained'] = osm_trees <= base_trees
    checks['osm_tree_count'] = read_json(a/'audit.json')['counts'].get('osm_trees',0) == sum(
        r['provenance']=='osm' for t in tb for r in t.get('tree_records',[]))
    if not all(checks.values()):
        raise ValueError(f'A/B invariant failed: {checks}')
    result={'checks':checks,'baseline':str(a),'styled':str(b),'counts':ib['local_visual_dna']['counts'],
            'architecture':dict(Counter(b['local_style']['architecture'] for t in tb for b in t['buildings'] if b.get('local_style'))),
            'recognisability':'pending human evaluation; these are structural checks'}
    write_json(output/'comparison.json',result)
    views=cameras(ia,tb)
    write_json(output/'cameras.json',views)
    influence(ib['local_visual_dna'],tb,output/'influence.png')
    return views, result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('baseline',type=Path); p.add_argument('styled',type=Path)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--capture',nargs=2,type=Path,metavar=('BASE_EXPORT','DNA_EXPORT'))
    args=p.parse_args()
    args.output.mkdir(parents=True,exist_ok=False)
    views,result=compare(args.baseline,args.styled,args.output)
    if args.capture:
        import beamng_bench as bench
        runs={}
        result['exports'] = {}
        for name, export in zip(('baseline','dna'),args.capture):
            artifact=read_json(export/'artifact.json')
            result['exports'][name] = {'zip_bytes': (export/artifact['zip']).stat().st_size,
                                      'artifact': artifact,
                                      'performance': read_json(export/'reports/performance.json')}
        write_json(args.output/'comparison.json',result)
        settings=SimpleNamespace(timeout=900,settle=10,stream=8,measure=3,resolution='1920 1080',quality='Normal')
        for name,export in zip(('baseline','dna'),args.capture):
            artifact=read_json(export/'artifact.json')
            user=(args.output/name/'user').resolve()
            level=bench.stage(export/artifact['zip'],user,views,settings)
            runs[name]={'cold':bench.run(user,level,'cold',900)}
            write_json(args.output/'runtime.json',runs)
            if runs[name]['cold']['status']!='complete':
                raise RuntimeError(f'{name} runtime capture failed')
        bench.sheets(runs,views,args.output)
    print(json.dumps(result,indent=2))


if __name__=='__main__': main()
