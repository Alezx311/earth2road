"""Standalone GIS overview and coverage audit from the actual generated Rivne map."""
from collections import Counter
import json
from pathlib import Path
import xml.etree.ElementTree as ET
from PIL import Image, ImageDraw, ImageFont
from shapely.geometry import Polygon, Point, shape
from shapely.ops import transform
from pyproj import Transformer
import sumolib
import paths
import corridor

ROOT=Path(__file__).resolve().parents[1]
MID='rivne_mykolaiv'


def main():
    cfg=json.loads((ROOT/f'config/{MID}.json').read_text(encoding='utf8'))
    area=corridor.area(cfg)
    boundary=json.loads((ROOT/cfg['boundary']['geojson']).read_text(encoding='utf8'))
    outline=shape(boundary['features'][0]['geometry'])
    net=sumolib.net.readNet(str(paths.build_dir(MID)/'network.net.xml'))
    data=paths.load_world(MID,tiles=True)
    ox,oy=data['offset']
    def net_xy(x,y,z=None):return net.convertLonLat2XY(x,y)
    area_xy=transform(net_xy,area)
    village_xy=transform(net_xy,outline)
    west,south,east,north=area_xy.bounds
    width,height=1700,1600
    scale=min((width-150)/(east-west),(height-240)/(north-south))
    left=(width-(east-west)*scale)/2
    def pixel(x,y):return (left+(x-west)*scale,140+(north-y)*scale)
    def game_pixel(p):return pixel(p[0]+ox,oy-p[2])
    image=Image.new('RGB',(width,height),'#f4f1e8')
    draw=ImageDraw.Draw(image)
    def font(size):
        for path in ('C:/Windows/Fonts/arial.ttf','/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'):
            if Path(path).exists():return ImageFont.truetype(path,size)
        return ImageFont.load_default()
    title,body,small=font(42),font(24),font(19)
    draw.text((60,32),'РІВНЕ · село та 1 км від околиць',font=title,fill='#1e3b36')
    draw.text((60,90),'Миколаївська область · карта для Godot · геометрія з відкритих даних',font=body,fill='#50645a')
    draw.polygon([pixel(x,y) for x,y in area_xy.exterior.coords],fill='#d0d3ac')
    palette={'farmland':'#dcd29c','garden':'#93ad71','wood':'#739477','green':'#98b482','water':'#8dbdcc','yard':'#c5b794','orchard':'#8aa76c'}
    for cover in data['greens']:
        for tri in cover['triangles']:
            draw.polygon([game_pixel(p) for p in tri],fill=palette.get(cover['kind'],'#a0b890'))
    for road in data['road_strips']:
        color='#7d7971' if road.get('surface','road')=='road' else '#aa8256'
        draw.line([game_pixel(p) for p in road['points']],fill=color,width=max(2,round(road['width']*scale)))
    for b in data['buildings']:
        draw.polygon([game_pixel(p) for p in b['points']],fill='#6c6057' if not b.get('source') else '#997d66')
    draw.line([pixel(x,y) for x,y in village_xy.exterior.coords],fill='#cc6a31',width=3)
    draw.line([pixel(x,y) for x,y in area_xy.exterior.coords],fill='#286c66',width=4)
    sx,sy=game_pixel(data['spawn']['position'])
    draw.ellipse((sx-7,sy-7,sx+7,sy+7),fill='#af382e',outline='white',width=2)
    draw.text((sx+12,sy-14),'Старт',font=small,fill='#8d2d25',stroke_width=2,stroke_fill='#f4f1e8')
    # Label the longest local segment for each distinct observed street name.
    root=ET.parse(ROOT/f'data/raw/{MID}.osm').getroot()
    nodes={n.get('id'):(float(n.get('lon')),float(n.get('lat'))) for n in root.findall('node')}
    streets={}
    for way in root.findall('way'):
        tags={t.get('k'):t.get('v') for t in way.findall('tag')}
        if not tags.get('highway') or not tags.get('name'):continue
        pts=[nodes[n.get('ref')] for n in way.findall('nd') if n.get('ref') in nodes]
        pts=[p for p in pts if outline.covers(Point(p))]
        if len(pts)>len(streets.get(tags['name'],[])):streets[tags['name']]=pts
    labels=[]
    for name,pts in sorted(streets.items(),key=lambda item:-len(item[1])):
        if len(pts)<2:continue
        x,y=pixel(*net.convertLonLat2XY(*pts[len(pts)//2]))
        if any(abs(x-a)<150 and abs(y-b)<35 for a,b in labels):continue
        label=name.replace(' вулиця','').replace('вулиця ','')
        draw.text((x+5,y-23),label,font=small,fill='#34423b',stroke_width=2,stroke_fill='#f4f1e8')
        labels.append((x,y))
    draw.line((90,height-115,90+500*scale,height-115),fill='#243c36',width=5)
    draw.text((90,height-105),'500 м',font=small,fill='#243c36')
    draw.text((width-110,160),'Пн ↑',font=body,fill='#243c36')
    draw.text((390,height-120),'Помаранчева межа — забудова; зелена — територія гри',font=small,fill='#34423b')
    draw.text((390,height-90),f"{len(data['buildings'])} будівель · {len(data['tiles'])} тайлів · {area_xy.area/1e6:.2f} км²",font=body,fill='#34423b')
    draw.text((60,height-40),'© OpenStreetMap contributors (ODbL) · Microsoft GlobalMLBuildingFootprints (CDLA-Permissive-2.0)',font=small,fill='#536059')
    out=ROOT/'logs/rivne'
    out.mkdir(parents=True,exist_ok=True)
    image.save(out/'overview.png')
    missing=[]
    for e in net.getEdges():
        for x,y in e.getShape():
            if not area_xy.buffer(0.25).covers(Point(x,y)):missing.append(e.getID());break
    overview={'map':MID,'area_km2':area_xy.area/1e6,'village_km2':village_xy.area/1e6,'buildings':len(data['buildings']),
              'building_sources':dict(Counter(b.get('source','osm') for b in data['buildings'])),
              'tiles':len(data['tiles']),'trees':len(data['trees']),'fence_segments':len(data['fences']),
              'road_surfaces':dict(Counter(r.get('surface','road') for r in data['road_strips'])),
              'road_edges_outside_boundary':sorted(set(missing)),
              'area_source':cfg['boundary'],'geometry_sources':cfg['geofabrik'],
              'assumptions':'Unobserved heights, roofs, parcel fences, garden trees, road width defaults and traffic are synthetic.'}
    (out/'coverage.json').write_text(json.dumps(overview,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(overview,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
