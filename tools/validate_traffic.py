#!/usr/bin/env python3
"""Real SUMO integration: ego braking, red light and 30 simulated minutes.
--stress N: instead, N cars for --minutes simulated minutes in spectator mode (throughput,
teleports, collisions, frame build time) -> logs/traffic_stress.json.
--incidents: instead, every road situation (tools/situations.py) applied and cancelled
against a live simulation -> logs/traffic_incidents.json."""
import argparse
import json
import math
from pathlib import Path
import time
from traffic import Simulation, ROOT

args=argparse.ArgumentParser()
args.add_argument('--stress',type=int,default=0)
args.add_argument('--minutes',type=float,default=10)
args.add_argument('--threads',type=int,default=8)
args.add_argument('--incidents',action='store_true',help='road situations: apply, measure, cancel')
args=args.parse_args()

def stress(count,minutes):
    sim=Simulation(density=count,threads=args.threads)
    sim.spectating=True
    report={'cars':count,'simulated_minutes':minutes,'threads':args.threads,'samples':[]}
    started=time.monotonic(); steps=int(minutes*600); frame_ms=[]
    try:
        for i in range(steps):
            sim.step()
            if i%100==0:
                t=time.perf_counter(); size=len(sim.frame()); frame_ms.append((time.perf_counter()-t)*1000)
            if i%3000==0:
                wall=time.monotonic()-started
                sample={'sim_s':i/10,'wall_s':round(wall,1),'cars':sim.count(),'teleports':sim.teleports,'collisions':sim.collisions,'frame_bytes':size}
                report['samples'].append(sample); print(sample,flush=True)
    finally:
        wall=time.monotonic()-started
        report.update({'wall_seconds':round(wall,1),'realtime_factor':round(steps/10/wall,2),'teleports':sim.teleports,'collisions':sim.collisions,'last_count':sim.count(),'median_frame_build_ms':round(sorted(frame_ms)[len(frame_ms)//2],1) if frame_ms else None})
        (ROOT/'logs/traffic_stress.json').write_text(json.dumps(report,indent=2))
        print(json.dumps({k:v for k,v in report.items() if k!='samples'},indent=2))
        sim.close()

def incidents():
    """Each situation must do something measurable while active and leave no trace after."""
    import situations
    sim=Simulation(density=400,threads=args.threads); c=sim.c
    sim.spectating=True
    S=sim.situations
    out={}
    def run(n):
        for _ in range(n): sim.step()
    def add(kind,point,**extra):
        cmd=situations.parse_command({'type':'incident','action':'add','kind':kind,'p':point,**extra},S.next_id)
        assert cmd is not None,kind
        return S.add(cmd,c.simulation.getTime())
    try:
        run(900)                                    # fill the network first
        # A long, multi-lane street: the same kind of road a user would click.
        lane=max((l for e in sim.net.getEdges() if e.getFunction()!='internal'
                  for l in e.getLanes() if l.allows('passenger') and l.getLength()>150
                  and len([x for x in e.getLanes() if x.allows('passenger')])>1),
                 key=lambda l:l.getLength())
        edge=lane.getEdge().getID()
        point=S.index.point_at(lane.getID(),lane.getLength()/2)[0]
        base_speed=c.edge.getLastStepMeanSpeed(edge)

        item=add('speed_limit',point,value_kmh=20,duration=0)
        active=[round(c.lane.getMaxSpeed(l),2) for l in item.lanes]
        assert all(abs(v-20/3.6)<0.05 for v in active),active
        S.remove(item.id)
        restored=[round(c.lane.getMaxSpeed(l),2) for l in item.lanes]
        original=[round(sim.net.getLane(l).getSpeed(),2) for l in item.lanes]
        assert restored==original,(restored,original)
        out['speed_limit']={'passed':True,'edge':edge,'active_mps':active,'restored_mps':restored}
        checkpoint(out)

        item=add('lane_closed',point,duration=0)
        closed=[l for l in item.lanes if 'passenger' not in c.lane.getAllowed(l)]
        assert len(closed)==1,closed
        run(600)
        on_closed=sum(c.lane.getLastStepVehicleNumber(l) for l in closed)
        on_open=sum(c.lane.getLastStepVehicleNumber(l) for l in item.lanes if l not in closed)
        assert on_closed==0,on_closed
        S.remove(item.id)
        assert all('passenger' in c.lane.getAllowed(l) for l in item.lanes)
        out['lane_closed']={'passed':True,'lane':closed[0],'cars_on_closed':on_closed,'cars_on_open':on_open}
        checkpoint(out)

        item=add('accident',point,duration=0)
        run(600)
        alive=[v for v in item.vehicles if v in c.vehicle.getIDList()]
        halting=c.edge.getLastStepHaltingNumber(edge)
        mean=c.edge.getLastStepMeanSpeed(edge)
        # The density controller must not treat incident cars as surplus traffic.
        assert len(alive)==len(item.vehicles),(alive,item.vehicles)
        assert all(c.vehicle.getSpeed(v)<0.1 for v in alive)
        assert halting>=len(alive),(halting,alive)
        S.remove(item.id)
        assert not [v for v in item.vehicles if v in c.vehicle.getIDList()]
        out['accident']={'passed':True,'vehicles':item.vehicles,'blocking':item.blocking,
                         'halting':halting,'mean_speed':round(mean,2),'baseline_speed':round(base_speed,2)}
        checkpoint(out)

        item=add('roadworks',point,value_kmh=20,duration=3)
        assert item.ends_at is not None
        run(60)                                     # 6 s: past the 3 s duration
        assert item.id not in S.items,'expired incident was not retired'
        assert all(abs(c.lane.getMaxSpeed(l)-sim.net.getLane(l).getSpeed())<0.05 for l in item.lanes)
        out['roadworks_expiry']={'passed':True,'edge':edge}
        checkpoint(out)

        # Signals: an override must survive the phase switches of the running program.
        tid=c.trafficlight.getIDList()[0]
        program=c.trafficlight.getProgram(tid)
        modes={}
        for mode,letter in (('allred','r'),('amber','y'),('off','O')):
            S.tls_apply({'type':'tls','action':mode,'id':tid})
            run(1200)                               # 120 s, well past any phase boundary
            S.tick(c.simulation.getTime())
            state=c.trafficlight.getRedYellowGreenState(tid)
            modes[mode]=state
            assert set(state)<=set(letter+'yO'),(mode,state)
        S.tls_apply({'type':'tls','action':'restore','id':tid})
        run(50)
        assert c.trafficlight.getProgram(tid)==program
        assert not S.overrides()
        out['traffic_light']={'passed':True,'tls':tid,'modes':modes,'program':program,
                              'note':'amber blinking is driven by the bridge; SUMO has no flashing model'}
        checkpoint(out)
        print(json.dumps(out,indent=2,ensure_ascii=False),flush=True)
    finally:
        checkpoint(out)
        sim.close()

def checkpoint(data=None):
    if data is None:
        (ROOT/'logs/traffic_validation.json').write_text(json.dumps(report,indent=2))
    else:
        (ROOT/'logs/traffic_incidents.json').write_text(json.dumps(data,indent=2,ensure_ascii=False))

if args.stress:
    stress(args.stress,args.minutes); raise SystemExit
if args.incidents:
    incidents(); raise SystemExit

report={}
# Same SUMO settings as the original validation: junction collision checks, one thread.
sim=Simulation(density=0,teleport=-1,threads=1,check_junctions=True)
c=sim.c
try:
    # A long, valid real lane; explicit leader ego and following vehicle.
    candidates=[l for e in sim.net.getEdges() if e.getFunction()!='internal' for l in e.getLanes() if l.allows('passenger') and l.getLength()>150]
    lane=min(candidates,key=lambda l:abs(l.getLength()-220))
    edge=lane.getEdge().getID();length=lane.getLength()
    c.route.add('follow_test',[edge])
    leadpos=min(100,length-40);trailpos=leadpos-35
    c.vehicle.add('lead','follow_test',typeID='ego_type',departLane=str(lane.getIndex()),departPos=str(leadpos),departSpeed='0')
    c.vehicle.add('follow','follow_test',typeID='car',departLane=str(lane.getIndex()),departPos=str(trailpos),departSpeed='8')
    c.vehicle.setSpeed('lead',0)
    c.vehicle.setLaneChangeMode('follow',0)
    for _ in range(120): c.simulationStep()
    gap=c.vehicle.getLanePosition('lead')-c.vehicle.getLanePosition('follow')-c.vehicle.getLength('lead')
    speed=c.vehicle.getSpeed('follow')
    assert speed<0.1 and gap>=2.0,(speed,gap)
    report['following_stationary_leader']={'passed':True,'speed':speed,'bumper_gap':gap,'lane':lane.getID()}
    checkpoint()
    c.vehicle.remove('lead');c.vehicle.remove('follow')
    # Test the actual moveToXY bridge with Godot center coordinates.
    x,y=__import__('sumolib').geomhelper.positionAtShapeOffset(lane.getShape(),leadpos)
    xa,ya=__import__('sumolib').geomhelper.positionAtShapeOffset(lane.getShape(),leadpos+1)
    angle=math.degrees(math.atan2(xa-x,ya-y))%360
    ox,oy=sim.world['offset']
    state={'position':[x-ox-math.sin(math.radians(angle))*2.2,0,-(y-oy-math.cos(math.radians(angle))*2.2)],'angle':angle,'speed':0}
    sim.update_ego(state);c.simulationStep()
    c.vehicle.add('follow2','follow_test',typeID='car',departLane=str(lane.getIndex()),departPos=str(trailpos),departSpeed='8')
    c.vehicle.setLaneChangeMode('follow2',0)
    sim.density=1
    for _ in range(120):sim.step(state)
    speed=c.vehicle.getSpeed('follow2')
    assert speed<0.1,speed
    report['godot_ego_proxy']={'passed':True,'follower_speed':speed,'ego_lane':c.vehicle.getLaneID('ego')}
    checkpoint()
    c.vehicle.remove('follow2');sim.reset_ego();sim.density=0
    # Force a real signal red and ensure a vehicle stops before its stop line.
    chosen=None
    for tls in sim.net.getTrafficLights():
        for incoming,outgoing,index in tls.getConnections():
            if incoming.allows('passenger') and outgoing.allows('passenger') and incoming.getLength()>60:
                chosen=(tls,incoming,outgoing);break
        if chosen:break
    tls,inc,out=chosen
    old=c.trafficlight.getProgram(tls.getID())
    c.trafficlight.setRedYellowGreenState(tls.getID(),'r'*len(c.trafficlight.getRedYellowGreenState(tls.getID())))
    c.route.add('red_route',[inc.getEdge().getID(),out.getEdge().getID()])
    c.vehicle.add('red_test','red_route',typeID='car',departLane=str(inc.getIndex()),departPos=str(inc.getLength()-45),departSpeed='8')
    for _ in range(150):c.simulationStep()
    stopped=c.vehicle.getSpeed('red_test');at=c.vehicle.getLaneID('red_test');remaining=inc.getLength()-c.vehicle.getLanePosition('red_test')
    assert stopped<0.1 and at==inc.getID() and remaining>=0,(stopped,at,remaining)
    report['red_signal']={'passed':True,'speed':stopped,'distance_to_line':remaining,'tls':tls.getID()}
    checkpoint()
    c.vehicle.remove('red_test');c.trafficlight.setProgram(tls.getID(),old)
    sim.density=100
    started=time.monotonic();peak=0;min_running=200
    for i in range(18000):
        sim.step(); running=sim.count()
        if i%3000==0: print(f'Soak progress {i/10:.0f}/1800 simulated seconds',flush=True)
        peak=max(peak,running)
        if i>100:min_running=min(min_running,running)
    report['soak']={'simulated_seconds':1800,'wall_seconds':time.monotonic()-started,'peak_vehicles':peak,'min_after_warmup':min_running,'teleports':sim.teleports,'collisions':sim.collisions,'last_count':sim.count()}
    assert sim.teleports==0
    print(json.dumps(report,indent=2),flush=True)
finally:
    sim.close()
    (ROOT/'logs/traffic_validation.json').write_text(json.dumps(report,indent=2))
