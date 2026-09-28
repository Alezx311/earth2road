#!/usr/bin/env python3
"""Local, single-client SUMO bridge. SI units; SUMO heading clockwise from north.

Modes: *driving* (Godot streams the player as SUMO vehicle 'ego'; SUMO steps only while
that stream is fresh, always at x1) and *spectating* (no ego; SUMO steps every tick at
the requested time multiplier). Every tick (0.1 s wall time) one binary frame goes out:

    u32 header_length | header JSON (utf-8, padded to 4 bytes) | float32 blocks

The header lists the few cars near the focus point (camera or player) as full records for
detailed vehicles with physics, and for every other car the per-model float32 blocks are a
ready Godot MultiMesh buffer (TRANSFORM_3D + colors + custom data, 20 floats/instance):
transform = pose in the previous frame, custom = (dx, dy, dz, dyaw) to the current pose,
color = (brake, indicator, 0, 1). The far-car shader interpolates on the GPU."""
import argparse
import asyncio
import collections
import faulthandler
import json
import hashlib
import math
import os
from pathlib import Path
import random
import signal
import struct
import sys
import time
import urllib.parse

import numpy as np
import sumolib

import paths
import runtime
import scenario as scenarios
import situations

try:
    _SUMO = runtime.sumo_binary('sumo')
    os.environ['PATH'] = str(_SUMO.parent) + os.pathsep + os.environ.get('PATH', '')
    if 'SUMO_HOME' not in os.environ and (_SUMO.parent.parent / 'bin').is_dir():
        os.environ['SUMO_HOME'] = str(_SUMO.parent.parent)
except FileNotFoundError:
    _SUMO = None

try:
    import libsumo as traci      # in-process SUMO: no socket per call, needed for thousands of cars
    BACKEND = 'libsumo'
    runtime.preload_libsumo()
except ImportError:
    import traci
    BACKEND = 'traci'
import traci.constants as tc
from websockets.asyncio.server import serve

ROOT=Path(__file__).resolve().parents[1]
TICK=0.1                 # wall seconds per bridge tick; SUMO step length is also 0.1 s
MAX_DENSITY=10000
SPEEDS=(0,1,2,4,8,16)
NEAR_MAX=120             # detailed cars (wheels, lamps, collision) around the focus
NEAR_RADIUS=220.0
FLOATS=20                # MultiMesh floats per instance
SIGNAL_RIGHT,SIGNAL_LEFT,SIGNAL_BRAKE=1,2,8
VARS=[tc.VAR_POSITION,tc.VAR_ANGLE,tc.VAR_LANE_ID,tc.VAR_LANEPOSITION,tc.VAR_SPEED,tc.VAR_SIGNALS,tc.VAR_TYPE]

class LaneHeights:
    """Height along every lane polyline from the world index, vectorised: all lanes are laid
    end to end on one axis (with gaps), so one np.interp serves any number of cars."""
    GAP=1000.0
    def __init__(self, lanes):
        self.index={}; starts=[]; lengths=[]; xs=[]; zs=[]
        cursor=0.0
        for i,lane in enumerate(lanes):
            pts=lane['points']
            d=[0.0]
            for a,b in zip(pts,pts[1:]):
                d.append(d[-1]+math.hypot(b[0]-a[0],b[2]-a[2]))
            self.index[lane['id']]=i; starts.append(cursor); lengths.append(d[-1])
            xs.extend(cursor+v for v in d); zs.extend(p[1] for p in pts)
            cursor+=d[-1]+self.GAP
        self.starts=np.array(starts); self.lengths=np.array(lengths)
        self.xs=np.array(xs); self.zs=np.array(zs)
    def at(self, lane_idx, pos):
        """lane_idx: int array (-1 = unknown lane -> 0 m); pos: metres along the lane."""
        known=lane_idx>=0
        i=np.where(known,lane_idx,0)
        z=np.interp(self.starts[i]+np.clip(pos,0,self.lengths[i]),self.xs,self.zs)
        return np.where(known,z,0.0)

def far_rows(prev, cur, brake, indicator):
    """MultiMesh rows (N x 20). prev/cur: N x 5 arrays of (x, y, z, yaw, pitch) in Godot
    space. Basis = RotY(yaw) * RotX(pitch), stored row-major 3x4 as Godot expects."""
    yaw=prev[:,3]; pitch=prev[:,4]
    c,s=np.cos(yaw),np.sin(yaw); cp,sp=np.cos(pitch),np.sin(pitch)
    out=np.zeros((len(prev),FLOATS),dtype=np.float32)
    out[:,0]=c;  out[:,1]=s*sp; out[:,2]=s*cp;  out[:,3]=prev[:,0]
    out[:,4]=0;  out[:,5]=cp;   out[:,6]=-sp;   out[:,7]=prev[:,1]
    out[:,8]=-s; out[:,9]=c*sp; out[:,10]=c*cp; out[:,11]=prev[:,2]
    out[:,12]=brake; out[:,13]=indicator; out[:,15]=1.0
    out[:,16:19]=cur[:,:3]-prev[:,:3]
    out[:,19]=(cur[:,3]-prev[:,3]+np.pi)%(2*np.pi)-np.pi
    return out

def pack_frame(header, blocks):
    """Binary frame: u32 length, JSON header padded to 4 bytes, then float32 blocks."""
    raw=json.dumps(header,separators=(',',':'),ensure_ascii=False).encode()
    raw+=b' '*(-len(raw)%4)
    return b''.join([struct.pack('<I',len(raw)),raw]+[b.astype('<f4',copy=False).tobytes() for b in blocks])

def unpack_frame(data):
    """Inverse of pack_frame (tests, tools): header dict and {model_index: N x 20 array}."""
    n=struct.unpack_from('<I',data)[0]
    header=json.loads(data[4:4+n]); floats=np.frombuffer(data,dtype='<f4',offset=4+n)
    blocks={}; at=0
    for model,count in header['far']:
        blocks[model]=floats[at:at+count*FLOATS].reshape(count,FLOATS); at+=count*FLOATS
    return header,blocks

class Simulation:
    def __init__(self, density=100, seed=311, teleport=300, threads=8, check_junctions=False, map_id=None):
        build=paths.build_dir(map_id); network=build/'network.net.xml'
        self.world=paths.load_world(map_id)
        if hashlib.sha256(network.read_bytes()).hexdigest()!=self.world.get('network_sha256'):
            raise RuntimeError('World/network revisions differ; rerun tools/prepare.py')
        self.routes=json.loads((build/'routes.json').read_text())
        # Demand by trip category and hour of day (tools/demand.py); fallback: random routes.
        demand_path=build/'demand.json'
        self.demand=json.loads(demand_path.read_text()) if demand_path.exists() else None
        hh,mm=(self.demand or {}).get('start_time','07:30').split(':')
        self.clock0=int(hh)*3600+int(mm)*60
        self.net=sumolib.net.readNet(str(network),withInternal=True)
        self.heights=LaneHeights(self.world['lanes'])
        self.rng=random.Random(seed)
        self.density=max(0,min(MAX_DENSITY,density)); self.serial=0; self.ego_added=False
        self.subscribed=set(); self.route_ids=set()
        self.teleports=0; self.collisions=0; self.paused=False
        self.spectating=False; self.speed=1
        self.focus=np.array(self.world['spawn']['position'],dtype=float)
        self.last_pose=({},np.zeros((0,5))); self.last_tls={}; self.step_ms=0.0
        # Road situations (tools/situations.py): commands are queued here and applied
        # between steps, because libsumo runs in-process and is not re-entrant.
        self.commands=collections.deque(); self.replies=collections.deque()
        self.situations=None
        self.timeline=None; self.timeline_t0=0.0
        # teleport: seconds a car may stand blocked before SUMO removes the jam (-1 = never).
        # Dense traffic can gridlock; the counter is reported, never hidden.
        # threads: SUMO parallel simulation (~2x faster at 5000 cars). Junction collision
        # checks cost ~20% more per step; validate_traffic.py turns them on.
        traci.start([str(_SUMO or runtime.sumo_binary('sumo')),'-n',str(network),'--step-length',str(TICK),'--seed',str(seed),'--no-step-log','true','--duration-log.disable','true','--time-to-teleport',str(teleport),'--max-depart-delay','20','--collision.action','warn','--collision.check-junctions',str(check_junctions).lower(),'--threads',str(threads),'--lanechange.duration','3','--device.rerouting.probability','0.3','--device.rerouting.period','120','--device.rerouting.threads','4','--log',str(ROOT/'logs/sumo.log')])
        self.c=traci if BACKEND=='libsumo' else traci.getConnection()
        self.c.vehicletype.copy('DEFAULT_VEHTYPE','car')
        self.c.vehicletype.setLength('car',4.4)
        self.c.vehicletype.setWidth('car',1.8)
        self.c.vehicletype.setMinGap('car',2.5)
        self.c.vehicletype.setMaxSpeed('car',16.67)
        # One vType per model (config/vehicles.json): real size from the rescaled model,
        # behaviour per class. All use vClass passenger (the network is built for it).
        catalogue=json.loads((ROOT/'config/vehicles.json').read_text())
        self.models,self.shares,self.lengths=[],[],{}
        for name,spec in catalogue['models'].items():
            behaviour=catalogue['sumo'][spec['class']]
            self.c.vehicletype.copy('DEFAULT_VEHTYPE',name)
            w,h,l=spec['size']
            self.c.vehicletype.setLength(name,l); self.c.vehicletype.setWidth(name,w); self.c.vehicletype.setHeight(name,h)
            self.c.vehicletype.setAccel(name,behaviour['accel']); self.c.vehicletype.setDecel(name,behaviour['decel'])
            self.c.vehicletype.setMaxSpeed(name,behaviour['maxSpeed']); self.c.vehicletype.setMinGap(name,behaviour['minGap'])
            self.c.vehicletype.setImperfection(name,behaviour['sigma']); self.c.vehicletype.setTau(name,behaviour['tau'])
            self.c.vehicletype.setSpeedDeviation(name,behaviour['speedDev'])
            # Yield carefully at minor links: no dawdling there and a wider time gap.
            self.c.vehicletype.setParameter(name,'junctionModel.jmSigmaMinor','0')
            self.c.vehicletype.setParameter(name,'junctionModel.jmTimegapMinor','2')
            self.models.append(name); self.shares.append(spec['share']); self.lengths[name]=l
        self.lengths['car']=4.4
        self.model_index={m:i for i,m in enumerate(self.models)}
        self.model_lengths=np.array([self.lengths[m] for m in self.models])
        for i,r in enumerate(self.routes): self.c.route.add('r'+str(i),r); self.route_ids.add('r'+str(i))
        self.pools={}
        if self.demand:
            pools=dict(self.demand['categories'])
            pools.update({'cal'+h:r for h,r in self.demand.get('calibrated',{}).items()})
            for cat,routes in pools.items():
                self.pools[cat]=[]
                for i,r in enumerate(routes):
                    rid=f'{cat}:{i}'; self.c.route.add(rid,r); self.route_ids.add(rid); self.pools[cat].append(r)
            for w in self.demand.get('roadworks',[]):
                self.c.edge.setMaxSpeed(w['edge'],w['speed'])
        self.situations=situations.Situations(self.c,self.net,situations.LaneIndex(self.world['lanes']))
        spawn=self.world['spawn']; edge=spawn['edge']
        self.c.route.add('ego_route',[edge])
        self.c.vehicletype.copy('car','ego_type')
        self.c.vehicletype.setColor('ego_type',(250,180,40,255))
        # Warm traffic without a player, then insert ego.
        for _ in range(30): self.step()
        self.reset_ego()
    def reset_ego(self):
        if 'ego' in self.c.vehicle.getIDList(): self.c.vehicle.remove('ego')
        self.ego_added=False
    def update_ego(self,state):
        x,y,z=state['position']; ox,oy=self.world['offset']
        angle=float(state['angle'])%360
        # Godot reports center; SUMO reports front-bumper position.
        half=float(state.get('length',4.4))/2
        sx=x+ox+math.sin(math.radians(angle))*half
        sy=-z+oy+math.cos(math.radians(angle))*half
        if not self.ego_added:
            sp=self.world['spawn']
            self.c.vehicle.add('ego','ego_route',typeID='ego_type',departLane=str(sp['lane_index']),departPos=str(sp['lane_position']),departSpeed='0')
            self.c.vehicle.setSpeedMode('ego',0); self.c.vehicle.setLaneChangeMode('ego',0)
            self.ego_added=True
        try:
            self.c.vehicle.moveToXY('ego','',-1,sx,sy,angle=angle,keepRoute=2,matchThreshold=50)
            self.c.vehicle.setSpeed('ego',max(0,float(state.get('speed',0))))
        except traci.TraCIException:
            self.reset_ego()
    def elevation(self,lane_id,pos):
        i=self.heights.index.get(lane_id,-1)
        return float(self.heights.at(np.array([i]),np.array([float(pos)]))[0])
    def count(self):
        ids=self.c.vehicle.getIDList()
        return len(ids)-('ego' in ids)
    def clock(self):
        """Seconds since midnight in the simulated day."""
        return (self.clock0+self.c.simulation.getTime())%86400
    def pick_route(self):
        """(route id prefix, edges): a trip for the current hour (demand.json), else random."""
        if not self.pools:
            index=self.rng.randrange(len(self.routes)); return 'r'+str(index),self.routes[index]
        hour=int(self.clock()//3600)
        cal=self.pools.get(f'cal{hour}')
        if cal:
            cat=f'cal{hour}'
        else:
            mix=self.demand['profile'][hour]
            cats=[c for c in mix if self.pools.get(c) and mix[c]>0]
            if not cats:
                # Sparse maps (no homes/workplaces this hour): random validation routes.
                index=self.rng.randrange(len(self.routes)); return 'r'+str(index),self.routes[index]
            cat=self.rng.choices(cats,[mix[c] for c in cats])[0]
        index=self.rng.randrange(len(self.pools[cat]))
        return f'{cat}:{index}',self.pools[cat][index]
    def insert(self):
        """Keep the network at the requested density. Cars inserted while filling up start
        on a random edge of a random route, so the whole network fills at once, not only
        the route origins."""
        ids=self.c.vehicle.getIDList()
        held=self.situations.protected if self.situations else set()
        count=len(ids)-('ego' in ids)-len(held.intersection(ids))
        if count>self.density:
            for v in [v for v in ids if v!='ego' and v not in held][:count-self.density]:
                self.subscribed.discard(v)
                self.c.vehicle.remove(v)
            return
        pending=len(self.c.simulation.getPendingVehicles())
        missing=self.density-count-pending
        filling=missing>max(20,self.density//10)
        for _ in range(min(missing,max(4,self.density//40))):
            rid,edges=self.pick_route()
            if filling and len(edges)>2:
                k=self.rng.randrange(len(edges)-1)
                if k:
                    base=rid; rid=f'{base}_{k}'
                    if rid not in self.route_ids:
                        self.c.route.add(rid,edges[k:]); self.route_ids.add(rid)
            vid=f'car{self.serial}'; self.serial+=1
            model=self.rng.choices(self.models,self.shares)[0]
            try:
                self.c.vehicle.add(vid,rid,typeID=model,departLane='best',departPos='random_free' if filling else 'base',departSpeed='max')
            except traci.TraCIException:
                # A lane closed by a road situation can disconnect a stored route
                # ("no valid route"): skip this trip, the next pick will do.
                continue
    def game_point(self,lon,lat):
        """Longitude/latitude -> a point in Godot coordinates (scenarios address places
        this way: SUMO edge ids change whenever the network is rebuilt)."""
        x,y=self.net.convertLonLat2XY(lon,lat); ox,oy=self.world['offset']
        return [x-ox,0.0,-(y-oy)]

    def start_scenario(self,spec):
        """Play a scripted sequence of invented road situations (tools/scenario.py)."""
        self.timeline=scenarios.Timeline(spec)
        self.timeline_t0=self.c.simulation.getTime()
        if 'density' in spec: self.density=max(0,min(MAX_DENSITY,int(spec['density'])))
        if spec.get('speed') in SPEEDS: self.speed=spec['speed']
        if 'start_time' in spec:
            hh,mm=str(spec['start_time']).split(':'); self.clock0=int(hh)*3600+int(mm)*60
        print(f"Scenario: {spec['name']} ({len(self.timeline.events)} events)",flush=True)

    def run_timeline(self,now):
        for event in self.timeline.due(now-self.timeline_t0):
            verb=event['do']
            if verb=='density': self.density=max(0,min(MAX_DENSITY,int(event.get('value',self.density))))
            elif verb=='speed':
                if event.get('value') in SPEEDS: self.speed=event['value']
            else:
                if verb=='tls' and not event.get('tls') and scenarios._lonlat(event):
                    # Traffic lights are addressed by place too: their ids are netconvert output.
                    try:
                        found=self.situations.pick(self.game_point(*event['lonlat']))['tls']
                        if not found: raise ValueError('No traffic light at this place')
                        event={**event,'tls':found}
                    except Exception as e:
                        self.replies.append({'type':'error','text':f'Scenario: {e}'}); continue
                cmd=situations.parse_command(scenarios.to_command(event,self.game_point),self.situations.next_id)
                if cmd: self.commands.append(cmd)

    def apply_commands(self):
        """Run queued control commands between steps and retire expired incidents.
        A failing command answers the client instead of killing the bridge."""
        now=self.c.simulation.getTime()
        if self.timeline and not self.timeline.finished: self.run_timeline(now)
        while self.commands:
            cmd=self.commands.popleft()
            try:
                if cmd['type']=='incident':
                    if cmd['action']=='add': self.situations.add(cmd,now)
                    elif cmd['action']=='remove': self.situations.remove(cmd['id'])
                    else: self.situations.clear()
                elif cmd['type']=='tls':
                    self.replies.append(self.situations.tls_apply(cmd))
                elif cmd['type']=='pick':
                    self.replies.append(self.situations.pick(cmd['p']))
            except Exception as e:
                self.replies.append({'type':'error','text':str(e) or e.__class__.__name__})
        self.situations.expire(now)
        self.situations.tick(now)

    def step(self,ego=None):
        """One SUMO step (0.1 s simulated)."""
        if self.paused: return
        self.apply_commands()
        if ego: self.update_ego(ego)
        self.insert()
        self.c.simulationStep()
        self.teleports+=self.c.simulation.getStartingTeleportNumber()
        self.collisions+=self.c.simulation.getCollidingVehiclesNumber()
    def advance(self,ego=None):
        """One bridge tick: 1 step while driving, `speed` steps while spectating."""
        n=self.speed if self.spectating else 1
        t=time.perf_counter()
        for _ in range(n): self.step(None if self.spectating else ego)
        if n: self.step_ms=(time.perf_counter()-t)*1000/n
        return n
    def states(self):
        """(ids, [(position, angle, lane, lane position, speed, signals, type)]) of all NPCs.
        libsumo: direct getters (no per-step cost; subscriptions cost ~11 ms every step at
        5000 cars). TraCI over a socket: subscriptions, one round trip."""
        live=[v for v in self.c.vehicle.getIDList() if v!='ego']
        if BACKEND=='libsumo':
            v=self.c.vehicle
            return live,[(v.getPosition(i),v.getAngle(i),v.getLaneID(i),v.getLanePosition(i),v.getSpeed(i),v.getSignals(i),v.getTypeID(i)) for i in live]
        self.subscribed.intersection_update(live)
        for vid in set(live)-self.subscribed:
            self.c.vehicle.subscribe(vid,VARS); self.subscribed.add(vid)
        res=self.c.vehicle.getAllSubscriptionResults()
        ids=[v for v in live if v in res]
        return ids,[tuple(res[i].get(k,0) for k in VARS) for i in ids]
    def frame(self,extra=None):
        """Binary frame for the current simulation state (see module docstring)."""
        ids,rows=self.states(); n=len(ids)
        # Column-wise list comprehensions: far cheaper than per-element numpy writes.
        lane_index=self.heights.index; model_index=self.model_index
        xy=np.array([r[0] for r in rows],dtype=float).reshape(n,2)
        ang=np.array([r[1] for r in rows],dtype=float)
        lane=np.array([lane_index.get(r[2],-1) for r in rows],dtype=np.int64)
        pos=np.array([r[3] for r in rows],dtype=float)
        speed=np.array([r[4] for r in rows],dtype=float)
        sig=np.array([r[5] for r in rows],dtype=np.int64)
        model=np.array([model_index.get(r[6],0) for r in rows],dtype=np.int64)
        length=self.model_lengths[model] if n else np.zeros(0)
        # SUMO reports the front bumper; Godot places the body centre.
        rad=np.radians(ang); ox,oy=self.world['offset']
        x=xy[:,0]-np.sin(rad)*length/2; y=xy[:,1]-np.cos(rad)*length/2
        front=self.heights.at(lane,pos); rear=self.heights.at(lane,pos-length)
        cur=np.column_stack([x-ox,(front+rear)/2,-(y-oy),-rad,np.arctan2(front-rear,length)]) if n else np.zeros((0,5))
        last_ids,last_cur=self.last_pose
        idx=np.array([last_ids.get(v,-1) for v in ids],dtype=np.int64)
        prev=np.where((idx>=0)[:,None],last_cur[np.maximum(idx,0)] if len(last_cur) else cur,cur)
        self.last_pose=({v:i for i,v in enumerate(ids)},cur)
        # Detailed cars: the nearest to the focus within NEAR_RADIUS.
        dist=np.linalg.norm(cur[:,:3]-self.focus,axis=1) if n else np.zeros(0)
        near=np.zeros(n,dtype=bool)
        if n:
            order=np.argsort(dist)[:NEAR_MAX]
            near[order[dist[order]<NEAR_RADIUS]]=True
        cars=[{'id':ids[i],'m':self.models[model[i]],'p':[round(float(cur[i,0]),3),round(float(cur[i,1]),3),round(float(cur[i,2]),3)],'a':round(float(ang[i]),2),'pt':round(float(cur[i,4]),4),'speed':round(float(speed[i]),2),'s':int(sig[i])} for i in np.flatnonzero(near)]
        brake=((sig&SIGNAL_BRAKE)!=0).astype(np.float32)
        indicator=np.where(sig&SIGNAL_LEFT,-1.0,np.where(sig&SIGNAL_RIGHT,1.0,0.0))
        rows=far_rows(prev,cur,brake,indicator)
        far=[]; blocks=[]
        for m in range(len(self.models)):
            sel=(~near)&(model==m)
            k=int(sel.sum())
            if k: far.append([m,k]); blocks.append(rows[sel])
        tls={}
        for t in self.c.trafficlight.getIDList():
            state=self.c.trafficlight.getRedYellowGreenState(t)
            if self.last_tls.get(t)!=state: tls[t]=state; self.last_tls[t]=state
        header={'type':'frame','time':self.c.simulation.getTime(),'clock':self.clock(),'cars':cars,'far':far,'total':n,'signals':tls,'teleports':self.teleports,'collisions':self.collisions,'step_ms':round(self.step_ms,2)}
        if self.situations:
            # Full list every frame, not a delta: the client keeps only the newest packet
            # per rendered frame (main.gd), so a delta sent during a slow frame is lost.
            header['incidents']=self.situations.snapshot(self.c.simulation.getTime())
            header['tls_over']=self.situations.overrides()
        if extra: header.update(extra)
        return pack_frame(header,blocks)
    def close(self):
        try: traci.close()
        except Exception: pass

def requested_map(path):
    """Map id from the handshake path (/?map=<id>) when it is a prepared map, else None."""
    mid=urllib.parse.parse_qs(urllib.parse.urlsplit(path or '').query).get('map',[''])[0]
    if not mid or not mid.replace('_','').isalnum() or not mid.isascii():
        return None
    if not (paths.game_dir(mid)/'index.json').exists() or not (paths.build_dir(mid)/'network.net.xml').exists():
        return None
    return mid

async def run(port,density,teleport,threads,near,map_id,scenario=None):
    global NEAR_MAX
    NEAR_MAX=near
    sim=Simulation(density,teleport=teleport,threads=threads,map_id=map_id)
    current=paths.map_id(map_id)
    if scenario: sim.start_scenario(scenarios.load(scenario,ROOT))
    print(f'SUMO backend: {BACKEND}, map: {paths.map_id(map_id)}',flush=True)
    stop=asyncio.Event()
    loop=asyncio.get_running_loop()
    try:
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, stop.set)
    except NotImplementedError:
        # Windows: ProactorEventLoop has no signal handlers. start.ps1 kills the process.
        pass
    active=None
    async def handler(ws):
        nonlocal active,sim,current
        if active is not None:
            await ws.close(1008,'Only one driver is allowed'); return
        active=ws
        # The game's map menu reconnects with ?map=<id>: restart SUMO on that network.
        # Blocking on purpose: libsumo lives in this thread and the only client waits anyway.
        want=requested_map(ws.request.path if ws.request else '')
        print(f'Client connected (map={want or current})',flush=True)
        if want and want!=current:
            print(f'Switching map: {current} -> {want}',flush=True)
            started=time.monotonic()
            sim.close()
            try:
                sim=Simulation(paths.load_world(want).get('traffic_count',100),teleport=teleport,threads=threads,map_id=want); current=want
                print(f'Map switch done in {time.monotonic()-started:.1f} s',flush=True)
            except Exception as e:
                print(f'Map switch failed: {e!r}',flush=True)
                sim=Simulation(density,teleport=teleport,threads=threads,map_id=current)
                await ws.send(json.dumps({'type':'error','text':f'Map {want}: {e}'}))
        state=None; last_input=time.monotonic(); sim.paused=False; sim.last_tls={}
        await ws.send(json.dumps({'type':'ready','map':current,'spawn':sim.world['spawn'],'models':sim.models,'speeds':SPEEDS,'max_density':MAX_DENSITY,'backend':BACKEND}))
        async def receive():
            nonlocal state,last_input
            async for raw in ws:
                try:
                    msg=json.loads(raw); kind=msg.get('type')
                    if kind=='ego':
                        p=msg.get('position'); a=msg.get('angle'); speed=msg.get('speed')
                        length=msg.get('length',4.4)
                        if not isinstance(p,list) or len(p)!=3 or not all(isinstance(v,(int,float)) and math.isfinite(v) for v in p+[a,speed,length]) or not 2<=length<=12:
                            continue
                        state=msg; last_input=time.monotonic()
                    elif kind=='focus':
                        p=msg.get('p')
                        if isinstance(p,list) and len(p)==3 and all(isinstance(v,(int,float)) and math.isfinite(v) for v in p):
                            sim.focus=np.array(p,dtype=float)
                    elif kind=='spectate':
                        sim.spectating=bool(msg.get('on')); sim.reset_ego(); state=None
                        if not sim.spectating: sim.speed=1
                    elif kind=='speed':
                        x=int(msg.get('x',1))
                        if x in SPEEDS: sim.speed=x
                    elif kind=='pause': sim.paused=bool(msg.get('paused'))
                    elif kind=='density': sim.density=max(0,min(MAX_DENSITY,int(msg.get('count',100))))
                    elif kind=='reset': sim.reset_ego(); sim.paused=False; state=None
                    elif kind in ('incident','tls','pick'):
                        cmd=situations.parse_command(msg,sim.situations.next_id)
                        if cmd: sim.commands.append(cmd)
                except (ValueError,TypeError,KeyError):
                    continue
        receiver=asyncio.create_task(receive())
        sim_clock=time.monotonic(); sim_start=sim.c.simulation.getTime()
        try:
            while not receiver.done():
                t=time.monotonic()
                driving=state is not None and t-last_input<1.5
                while sim.replies:
                    await ws.send(json.dumps(sim.replies.popleft()))
                if sim.spectating or driving:
                    try:
                        steps=sim.advance(state)
                        # Achieved multiplier over the last ~2 s: SUMO may not keep up with x16.
                        if t-sim_clock>2.0:
                            now=sim.c.simulation.getTime()
                            sim.actual=(now-sim_start)/(t-sim_clock); sim_clock=t; sim_start=now
                        frame=sim.frame({'speed':sim.speed if sim.spectating else 1,'actual':round(getattr(sim,'actual',1.0),2),'spectating':sim.spectating,'paused':sim.paused,'steps':steps})
                    except Exception as e:
                        # libsumo cannot go on after an error inside the simulation (the next
                        # step crashes the whole process): rebuild SUMO on the same map and
                        # keep the client connected.
                        print(f'SUMO error, restarting the simulation: {e!r}',flush=True)
                        await ws.send(json.dumps({'type':'error','text':f'Traffic restarted after a SUMO error: {e}'}))
                        keep=(sim.spectating,sim.speed,sim.density)
                        sim.close()
                        sim=Simulation(keep[2],teleport=teleport,threads=threads,map_id=current)
                        sim.spectating,sim.speed=keep[0],keep[1]
                        state=None; sim_clock=time.monotonic(); sim_start=sim.c.simulation.getTime()
                        continue
                    await ws.send(frame)
                else:
                    sim_clock=t; sim_start=sim.c.simulation.getTime()
                await asyncio.sleep(max(0,TICK-(time.monotonic()-t)))
        finally:
            receiver.cancel(); await asyncio.gather(receiver,return_exceptions=True)
            print(f'Client disconnected: {ws.close_code} {ws.close_reason or ""}'.rstrip(),flush=True)
            sim.paused=True; active=None; sim.reset_ego(); sim.spectating=False; sim.speed=1
    try:
        # No handshake timeout and no keepalive: the game polls the socket only after it has
        # built the world (a large map + first shader compile can take well over the default
        # 10 s, and websockets then drops the connection silently), and the bridge itself
        # blocks while it rebuilds SUMO for another map. The game detects a stale stream by
        # frame age and reconnects on its own.
        async with serve(handler,'127.0.0.1',port,max_size=8192,max_queue=4,open_timeout=None,ping_interval=None):
            print(f'Traffic bridge ready ws://127.0.0.1:{port}',flush=True)
            await stop.wait()
    finally: sim.close()

if __name__=='__main__':
    # SUMO runs in-process (libsumo): a native crash kills the bridge without a Python
    # traceback. faulthandler still writes the Python stack to stderr (logs/bridge.err.log).
    faulthandler.enable()
    p=argparse.ArgumentParser()
    p.add_argument('--port',type=int,default=8765)
    p.add_argument('--density',type=int,default=None)
    p.add_argument('--teleport',type=int,default=300,help='SUMO --time-to-teleport, s (-1 never)')
    p.add_argument('--threads',type=int,default=8,help='SUMO parallel simulation threads')
    p.add_argument('--near',type=int,default=NEAR_MAX,help='detailed cars around the focus (0 = all MultiMesh)')
    p.add_argument('--map',help='map id (default: AKADEM_MAP or the last prepared map)')
    p.add_argument('--scenario',help='scripted road situations: config/scenarios/<id>.json')
    a=p.parse_args()
    if a.density is None:
        a.density = paths.load_world(a.map).get('traffic_count',100)
    try: asyncio.run(run(a.port,a.density,a.teleport,a.threads,a.near,a.map,a.scenario))
    except KeyboardInterrupt: pass
