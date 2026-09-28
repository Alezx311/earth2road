"""Deterministic priority junction fixture; checks yield behavior and grade topology."""
from pathlib import Path
import json
import os
import subprocess
import tempfile
import traci
from traffic import ROOT
import runtime

def run():
    (ROOT/'data/build').mkdir(parents=True, exist_ok=True)
    (ROOT/'logs').mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=ROOT/'data/build') as tmp:
        d=Path(tmp)
        (d/'nodes.xml').write_text('<nodes><node id="W" x="-100" y="0"/><node id="E" x="100" y="0"/><node id="N" x="0" y="100"/><node id="S" x="0" y="-100"/><node id="J" x="0" y="0" type="priority"/></nodes>')
        (d/'edges.xml').write_text('<edges><edge id="WJ" from="W" to="J" priority="3" speed="10"/><edge id="JE" from="J" to="E" priority="3" speed="10"/><edge id="NJ" from="N" to="J" priority="1" speed="10"/><edge id="JS" from="J" to="S" priority="1" speed="10"/></edges>')
        (d/'connections.xml').write_text('<connections><connection from="WJ" to="JE"/><connection from="NJ" to="JS"/></connections>')
        netconvert = runtime.sumo_binary('netconvert')
        sumo = runtime.sumo_binary('sumo')
        os.environ['PATH'] = str(sumo.parent) + os.pathsep + os.environ.get('PATH', '')
        subprocess.run([str(netconvert),'-n',str(d/'nodes.xml'),'-e',str(d/'edges.xml'),'-x',str(d/'connections.xml'),'-o',str(d/'net.xml')],check=True,capture_output=True)
        traci.start([str(sumo),'-n',str(d/'net.xml'),'--step-length','0.1','--no-step-log','true','--seed','311'])
        c=traci.getConnection()
        try:
            c.route.add('major',['WJ','JE']);c.route.add('minor',['NJ','JS'])
            c.vehicle.add('major','major',departPos='60',departSpeed='10')
            c.vehicle.add('minor','minor',departPos='60',departSpeed='10')
            crossing={};minimum=100;collisions=0
            for i in range(150):
                c.simulationStep()
                collisions+=c.simulation.getCollidingVehiclesNumber()
                for vid in c.vehicle.getIDList():
                    if vid=='minor' and c.vehicle.getRoadID(vid)=='NJ':minimum=min(minimum,c.vehicle.getSpeed(vid))
                    if c.vehicle.getRoadID(vid).startswith(':') and vid not in crossing:crossing[vid]=c.simulation.getTime()
            assert crossing['major']<crossing['minor'],crossing
            assert minimum<8,minimum
            assert collisions==0,collisions
            report={'passed':True,'crossing_seconds':crossing,'minor_min_speed':minimum,'collisions':collisions}
            (ROOT/'logs/priority_validation.json').write_text(json.dumps(report,indent=2));print(report)
        finally:c.close()
if __name__=='__main__':run()
