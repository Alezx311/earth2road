"""Build or replay the roadgen proving ground without downloads or engine startup."""
import argparse
import copy
import html
import json
import math
from pathlib import Path
import statistics
import sys
import time
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from akadem_maps.context import read_json, write_json, sha256
from akadem_maps.core import roadgen, road_graph, road_geometry, surface_audit, scene
from akadem_maps.core.roadgen_lab import fixture, CASES


def saved_patches(prepared):
    from shapely.geometry import Polygon
    index=read_json(prepared/'index.json')
    ox,oy=index['offset']
    output={}
    for tile in sorted((prepared/'tiles').glob('*.json')):
        for j in read_json(tile)['junctions']:
            tris=[[(v[0]+ox,-v[2]+oy,v[1]) for v in tri] for tri in j['triangles']]
            output[j['id']]={'poly':road_geometry.union(Polygon([p[:2] for p in tri]) for tri in tris),
                             'triangles':tris,'arms':[],'saved':True}
    return output


def replay(prepared, mode, tolerance, repeats=1, targets=None):
    import sumolib
    prepared = Path(prepared)
    snapshot = read_json(prepared/'roadgen_input.json')
    if sha256(prepared/'network.net.xml') != snapshot['network_sha256']:
        raise ValueError('Prepared network hash differs from geometry snapshot')
    net = sumolib.net.readNet(str(prepared/'network.net.xml'), withInternal=True)
    z = SimpleNamespace(**{k:snapshot[k] for k in ('shapes','z','internal_by_node')})
    z.shape = lambda lane:z.shapes[lane.getID()]
    saved=saved_patches(prepared)
    if mode=='legacy' and read_json(prepared/'config.json').get('road_geometry',{}).get('mode')=='v2':
        raise ValueError('A legacy preview requires a legacy prepared world; v2 snapshots do not contain legacy junction surfaces')
    times=[]
    for _ in range(repeats):
        strips=copy.deepcopy(snapshot['strips'])
        start=time.perf_counter()
        if mode == 'v2':
            patches,graph,report,_=roadgen.generate(snapshot['source'],net,strips,z,tolerance,targets)
        else:
            graph=road_graph.bind(snapshot['source'],net,strips)
            patches={}
            report={'version':1,'mode':'legacy','junctions':[]}
        times.append(time.perf_counter()-start)
    patches={**saved,**patches}
    return strips,patches,graph,report,{'repeats':repeats,'seconds':times,'median_seconds':statistics.median(times)}


def preview(output, strips, patches, title, bounds=None):
    """Portable vector debug view and a PNG contact sheet; no browser dependencies."""
    from PIL import Image, ImageDraw
    triangles=[(tri,'#465b63') for r in strips.values() for tri in r.get('triangles',surface_audit.ribbon_triangles(r['points'],r['width']))]
    triangles += [(tri,'#72858a' if p.get('saved') else '#327c81') for p in patches.values() for tri in p['triangles']]
    if bounds:
        triangles=[(t,c) for t,c in triangles if any(bounds[0]<=p[0]<=bounds[2] and bounds[1]<=p[1]<=bounds[3] for p in t)]
    points=[p for t,c in triangles for p in t]
    if not points: return
    xs,ys=zip(*[p[:2] for p in points])
    bounds=bounds or (min(xs),min(ys),max(xs),max(ys))
    scale=min(1300/max(1,bounds[2]-bounds[0]),1000/max(1,bounds[3]-bounds[1]))
    top=60+(1000-(bounds[3]-bounds[1])*scale)/2
    def xy(p): return (40+(p[0]-bounds[0])*scale,top+(bounds[3]-p[1])*scale)
    img=Image.new('RGB',(1400,1120),'#e8edef'); draw=ImageDraw.Draw(img)
    svg=['<svg xmlns="http://www.w3.org/2000/svg" width="1400" height="1120" viewBox="0 0 1400 1120">',
         '<rect width="100%" height="100%" fill="#e8edef"/>',
         f'<text x="30" y="28" font-family="sans-serif" font-size="20">{html.escape(title)}</text>']
    draw.text((30,10),title,fill='black')
    for tri,color in triangles:
        coords=[xy(p) for p in tri]
        draw.polygon(coords,fill=color,outline='#93a5ac')
        formatted=' '.join(f'{x:.3f},{y:.3f}' for x,y in coords)
        svg.append(f'<polygon points="{formatted}" fill="{color}" stroke="#93a5ac" stroke-width=".35"/>')
    for patch in patches.values():
        for arm in patch['arms']:
            for field,color in [('outer','#eaa72f'),('inner','#d8537d')]:
                coords=[xy(p) for p in arm[field]]
                draw.line(coords,fill=color,width=3)
                svg.append(f'<path d="M{coords[0][0]},{coords[0][1]} L{coords[1][0]},{coords[1][1]}" stroke="{color}" stroke-width="3"/>')
    svg.append('</svg>')
    (output/'geometry.svg').write_text('\n'.join(svg),encoding='utf-8')
    img.save(output/'geometry.png')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--case',choices=['all']+[c['id'] for c in CASES],default='all')
    p.add_argument('--engine',choices=['legacy','v2'],default='v2')
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--prepared',type=Path,help='Replay a world roadgen_input.json without netconvert/terrain/build')
    p.add_argument('--curve-tolerance',type=float,default=.02)
    p.add_argument('--repeats',type=int,default=3)
    p.add_argument('--export',choices=['beamng','godot','both'])
    args=p.parse_args()
    roadgen.options({'road_geometry':{'mode':args.engine,'curve_tolerance_m':args.curve_tolerance}})
    if not 1<=args.repeats<=1000: p.error('--repeats must be 1..1000')
    if args.prepared and args.export: p.error('--export requires a full build; omit --prepared')
    args.output.mkdir(parents=True,exist_ok=False)
    started=time.perf_counter()
    targets,bounds=None,None
    if args.prepared:
        prepared=args.prepared
        cases=[]
        if args.case!='all':
            catalogue=read_json(prepared.parent/'inputs/cases.json')
            case=next((c for c in catalogue if c['id']==args.case),None)
            if case is None: p.error('The prepared fixture does not contain this case')
            graph=read_json(prepared/'road_graph.json') if (prepared/'road_graph.json').exists() else None
            import sumolib
            net=sumolib.net.readNet(str(prepared/'network.net.xml'))
            targets={n.getID() for n in net.getNodes() if n.getID() in case['source_nodes'] or
                     any(s in n.getID().replace('cluster_','').split('_') for s in case['source_nodes'])}
            if not targets: p.error('No effective junction for this case (e.g. an unconnected overpass)')
            x,y=net.getNode(sorted(targets)[0]).getCoord()
            bounds=(x-90,y-90,x+90,y+90)
    else:
        from akadem_maps.world import build_world
        cfg,cases=fixture(args.output/'inputs',args.case,args.engine,args.curve_tolerance)
        prepared=args.output/'world'
        build_world(cfg,prepared,inputs=args.output/'inputs',offline=True,
                    emit=lambda event,**data: print(event,json.dumps(data),flush=True))
    build_seconds=time.perf_counter()-started
    strips,patches,graph,report,timings=replay(prepared,args.engine,args.curve_tolerance,args.repeats,targets)
    preview(args.output,strips,patches,'Roadgen '+args.engine+' / '+args.case,bounds)
    write_json(args.output/'road_graph.json',graph)
    write_json(args.output/'roadgen_report.json',report)
    write_json(args.output/'timings.json',{'build_seconds':build_seconds,'geometry':timings})
    if cases:
        import sumolib
        net=sumolib.net.readNet(str(prepared/'network.net.xml'))
        for c in cases:
            match=[j for j in report.get('junctions',[]) if j['id'] in c['source_nodes'] or
                   any(n in j['id'].replace('cluster_','').split('_') for n in c['source_nodes'])]
            c['results']=match
        write_json(args.output/'cases.json',cases)
    if args.export in ('beamng','both'):
        from akadem_maps.adapters.beamng.export import export_world
        export_world(prepared,args.output/'beamng',optimization='compact')
    if args.export in ('godot','both'):
        from akadem_maps.adapters.godot.export import export_world
        export_world(prepared,args.output/'godot',offline=True)
    print(json.dumps({'output':str(args.output),'counts':report.get('counts'), 'families':report.get('families'),
                      'geometry_seconds':timings['median_seconds']}),flush=True)


if __name__=='__main__':
    main()
