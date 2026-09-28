"""Godot data and synthetic traffic preparation from a verified world package."""
from pathlib import Path
import shutil
import xml.etree.ElementTree as ET
import sumolib
from akadem_maps.context import BuildContext, atomic_directory, read_json, write_json
from akadem_maps.world import validate_world
from . import demand

YARD_TRIP_SHARE = 0.3

def routes(cfg, net, index, context):
    lane_points = {lane['id']:lane['points'] for lane in index['lanes']}
    route_edges=[e for e in net.getEdges() if e.getFunction()=='' and any(l.allows('passenger') for l in e.getLanes())]
    street_edges=[e for e in route_edges if e.getType()!='highway.service']
    service_edges=[e for e in route_edges if e.getType()=='highway.service']
    import random
    rng=random.Random(cfg['seed']); routes=[]
    # Synthetic demand: most trips street to street; YARD_TRIP_SHARE start or end in a yard.
    yard_trips=0
    for _ in range(3000 if len(street_edges) >= 2 else 0):
        yard=bool(service_edges) and rng.random()<YARD_TRIP_SHARE
        a,b=rng.sample(street_edges,2)
        if yard:
            if rng.random()<0.5: a=rng.choice(service_edges)
            else: b=rng.choice(service_edges)
        path,cost=net.getShortestPath(a,b,vClass='passenger')
        if path and cost>400 and len(path)>3:
            routes.append([e.getID() for e in path if e.getFunction()!='internal'])
            yard_trips+=yard
        if len(routes)>=300: break
    # yard trips remain explicitly synthetic
    write_json(context.build/'routes.json',routes)
    validation=[]
    candidates=sorted(routes,key=lambda r:sum(net.getEdge(e).getLength() for e in r))
    yard_routes=[r for r in candidates if any(net.getEdge(e).getType()=='highway.service' for e in r)]
    chosen=([candidates[i] for i in (len(candidates)//5,len(candidates)//2,4*len(candidates)//5)]+yard_routes[len(yard_routes)//2:len(yard_routes)//2+1]) if candidates else []
    for route in chosen:
        points=[];lane_ids=[]
        for a,b in zip(route,route[1:]):
            connections=net.getEdge(a).getOutgoing()[net.getEdge(b)]
            valid=[c for c in connections if c.getFromLane().allows('passenger') and c.getToLane().allows('passenger')]
            c=valid[0]; selected=c.getFromLane()
            lane_ids.append(selected.getID())
            points.extend(lane_points.get(selected.getID(), []))
            via=c.getViaLaneID()
            visited=set()
            while via and via not in visited:
                visited.add(via); il=net.getLane(via);lane_ids.append(via)
                points.extend(lane_points.get(il.getID(), []))
                via=il.getOutgoing()[0].getViaLaneID() if il.getOutgoing() else ''
        validation.append({'edges':route,'lanes':lane_ids,'points':points})
    return validation

def export_world(world, output, *, offline=False):
    world = Path(world).resolve()
    validate_world(world)
    cfg = read_json(world/'config.json')
    mid = cfg['id']
    with atomic_directory(output) as stage:
        game = stage/'game/data'/mid
        build = stage/'data/build'/mid
        game.mkdir(parents=True)
        build.mkdir(parents=True)
        shutil.copytree(world/'tiles', game/'tiles')
        # Sign faces are Ukrainian artwork; other regions get no posted signs.
        skipped = 0
        if cfg.get('region_profile') != 'ukraine':
            for path in sorted((game/'tiles').glob('*.json')):
                tile = read_json(path)
                if tile.get('signs'):
                    skipped += len(tile['signs'])
                    tile['signs'] = []
                    write_json(path, tile)
        for name in ('network.net.xml','corrected.osm','sources.json','audit.json','corridor.geojson'):
            if (world/name).exists():
                shutil.copy2(world/name, build/name)
        index = read_json(world/'index.json')
        net = sumolib.net.readNet(str(build/'network.net.xml'), withInternal=True, withPrograms=True)
        raw = stage/'data/raw'
        raw.mkdir(parents=True)
        source_raw = world/'inputs/raw/roadworks.geojson'
        if source_raw.exists():
            shutil.copy2(source_raw, raw/source_raw.name)
        context = BuildContext(build, raw, world/'inputs/config_root', offline)
        index['validation_routes'] = routes(cfg, net, index, context)
        traffic = demand.build(cfg, ET.parse(build/'corrected.osm').getroot(), net, cfg['seed'], context=context)
        write_json(build/'traffic-audit.json', traffic)
        write_json(game/'index.json', index)
        write_json(stage/'godot-export.json', {'id':mid,'activation':'explicit','signs_skipped_region':skipped,'world':read_json(world/'world.json')['files']['index.json']})
    return {'id':mid,'output':str(Path(output).resolve()),'activation':'not activated'}
