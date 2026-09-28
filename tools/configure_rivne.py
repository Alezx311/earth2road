"""Reproduce Rivne's reviewed OSM settlement outline and 1 km playable buffer.

First survey (cached, not committed):
python tools/osm_extract.py data/raw/geofabrik/ukraine-260918.osm.pbf .cache/rivne-survey.osm --bbox 31.53,46.73,31.64,46.81
Then: python tools/configure_rivne.py
"""
import argparse
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET
from shapely.geometry import Polygon, LineString, mapping
from shapely.ops import unary_union, transform, nearest_points
from pyproj import Transformer
import corridor
import osm_extract

ROOT = Path(__file__).resolve().parents[1]
MID = 'rivne_mykolaiv'


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf8')


def configure(survey):
    root = ET.parse(survey).getroot()
    nodes = {n.get('id'):(float(n.get('lon')),float(n.get('lat'))) for n in root.findall('node')}
    tags = lambda e: {t.get('k'):t.get('v') for t in e.findall('tag')}
    way = next(w for w in root.findall('way') if w.get('id')=='631613565')
    if tags(way).get('name') != 'Рівне' or tags(way).get('postal_code') != '57530':
        raise ValueError('Unexpected settlement identity')
    outline = Polygon([nodes[n.get('ref')] for n in way.findall('nd')])
    forward = Transformer.from_crs(4326,32636,always_xy=True).transform
    reverse = Transformer.from_crs(32636,4326,always_xy=True).transform
    metro = transform(forward,outline)
    selected, ids = [metro], ['631613565']
    supplementary = []
    enrichment = ROOT/'.cache/rivne-buildings.geojson'
    if enrichment.exists():
        from shapely.geometry import shape
        for f in json.loads(enrichment.read_text(encoding='utf8'))['features']:
            p = transform(forward,shape(f['geometry']))
            if not metro.covers(p) and p.distance(metro)<180:
                selected.append(p)
                supplementary.append({'geometry':f['geometry'],'properties':f['properties']})
    for w in root.findall('way'):
        refs = [n.get('ref') for n in w.findall('nd')]
        if not tags(w).get('building') or len(refs)<4 or refs[0]!=refs[-1]: continue
        p = transform(forward,Polygon([nodes[r] for r in refs]))
        if p.is_valid and p.distance(metro)<180:
            selected.append(p); ids.append(w.get('id'))
    # Explicit narrow connectors to nearby outlying footprints. Do not shrink
    # any footprint with morphological closing or include a neighbouring village.
    joins = [LineString(nearest_points(metro,p)).buffer(5) for p in selected[1:] if not metro.intersects(p)]
    settlement = unary_union([*selected,*joins]).buffer(0.01)
    if settlement.geom_type != 'Polygon':
        raise ValueError('Review outlying settlement pieces before building')
    outline = transform(reverse,settlement)
    boundary_path = ROOT/'config/areas/rivne_mykolaiv.geojson'
    write(boundary_path,{'type':'FeatureCollection','supplementary_footprints':supplementary,'features':[
        {'type':'Feature','properties':{'role':'settlement','name':'Рівне',
         'source':'OpenStreetMap / Geofabrik 2026-09-18','osm_ways':ids,
         'provenance':'derived from residential/place outline + OSM and Microsoft footprints within 180 m; 5 m connectors',
         'note':'Working outline of village development, not an administrative boundary.'},'geometry':mapping(outline)}]})
    cfg = {'id':MID,'name':'Рівне · село та околиці','center':[31.5787,46.7665],
           'boundary':{'geojson':'config/areas/rivne_mykolaiv.geojson','buffer_m':1000},
           'chunk_size':250,'seed':311,'traffic_count':20,'demand_pool':300,'start_time':'12:00',
           'terrain_zoom':12,'visual_profile':'rural','activate_on_build':False,
           'spawn':{'lon':31.5787,'lat':46.7665,'heading':90},
           'shots_config':'config/rivne_shots.json',
           'overpass':'https://overpass.kumi.systems/api/interpreter',
           'geofabrik':{'url':'https://download.geofabrik.de/europe/ukraine-260918.osm.pbf',
                         'md5':'8357c720d91f72db3aa5feb6dea04bf3'},
           'building_enrichment':{'enabled':True,'offline':True,'strict':True,'default_height':4.8,
              'unknown_height_policy':'assume','road_margin':0.5,'water_margin':0.5,
              'sources_config':'config/building_sources.json','cache_dir':'.cache/buildings',
              'sources':{'microsoft':{}}},
           'note':'Whole village development + 1000 m outward buffer. Rural appearance and traffic are synthetic where untagged. Godot only.'}
    area = corridor.area(cfg)
    write(ROOT/f'config/{MID}.json',cfg)
    write(ROOT/'config/rivne_shots.json', {'shots':[
        {'name':'rivne_center','lon':31.5787,'lat':46.7665,'height':3.5,'heading':90,'pitch':-6,'snap':True},
        {'name':'rivne_north','lon':31.5784,'lat':46.7712,'height':5,'heading':180,'pitch':-15,'snap':True},
        {'name':'rivne_farms','lon':31.5885,'lat':46.7624,'height':18,'heading':95,'pitch':-25},
        {'name':'rivne_overview','lon':31.5787,'lat':46.751,'height':1600,'heading':0,'pitch':-48}]})
    # Reuse the complete survey to avoid another country-wide pass; retain source checksum.
    dest = ROOT/f'data/raw/{MID}.osm'
    osm_extract.extract(survey,dest,cfg['bbox'],area)
    write(dest.with_suffix('.osm.area.json'),{'digest':corridor.area_digest(cfg),
          'survey_sha256':hashlib.sha256(Path(survey).read_bytes()).hexdigest()})
    playable = transform(forward,area)
    write(ROOT/f'data/build/{MID}/area.geojson',{'type':'FeatureCollection','features':[
        {'type':'Feature','properties':{'role':'settlement'},'geometry':mapping(outline)},
        {'type':'Feature','properties':{'role':'area','buffer_m':1000,'area_km2':playable.area/1e6},'geometry':mapping(area)}]})
    print(json.dumps({'bbox':cfg['bbox'],'village_km2':metro.area/1e6,'playable_km2':playable.area/1e6},indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--survey',default='.cache/rivne-survey.osm')
    configure(ROOT/p.parse_args().survey)
