#!/usr/bin/env python3
"""Real SUMO processes: overlapping networks, red queue, internal lane, ego braking."""
import argparse
import json
import math
from pathlib import Path
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from akadem_maps.context import write_json
from akadem_maps.runtime import sumo_binary
from akadem_maps.traffic_handoff import transfer


def networks(folder):
    """The second window removes a western branch and adds an eastern one."""
    for name, side in [('old', 'W'), ('new', 'E')]:
        d = folder / name
        d.mkdir()
        (d / 'nodes.xml').write_text('<nodes><node id="W" x="-200" y="0"/>'
            '<node id="E" x="200" y="0"/><node id="N" x="0" y="200"/>'
            '<node id="S" x="0" y="-200"/><node id="J" x="0" y="0" type="traffic_light"/>'
            f'<node id="outer{side}" x="{ -400 if side == "W" else 400}" y="0"/></nodes>')
        (d / 'edges.xml').write_text('<edges><edge id="WJ" from="W" to="J" speed="15"/>'
            '<edge id="JE" from="J" to="E" speed="15"/><edge id="NJ" from="N" to="J" speed="15"/>'
            '<edge id="JS" from="J" to="S" speed="15"/>' +
            ('<edge id="outerW" from="outerW" to="W"/>' if side == 'W' else '<edge id="outerE" from="E" to="outerE"/>') + '</edges>')
        (d / 'connections.xml').write_text('<connections><connection from="WJ" to="JE"/>'
                                           '<connection from="NJ" to="JS"/></connections>')
        subprocess.run([str(sumo_binary('netconvert')), '-n', str(d / 'nodes.xml'),
            '-e', str(d / 'edges.xml'), '-x', str(d / 'connections.xml'),
            '--offset.disable-normalization', 'true', '-o', str(d / 'net.xml')], check=True, capture_output=True)


def start(network, label):
    import traci
    traci.start([str(sumo_binary('sumo')), '-n', str(network), '--step-length', '.1',
        '--seed', '311', '--no-step-log', 'true', '--duration-log.disable', 'true',
        '--time-to-teleport', '-1', '--collision.check-junctions', 'true'], label=label)
    c = traci.getConnection(label)
    c.vehicletype.setImperfection('DEFAULT_VEHTYPE', 0)
    c.vehicletype.setSpeedDeviation('DEFAULT_VEHTYPE', 0)
    return c


def add(c, vid, position, speed=0):
    c.vehicle.add(vid, 'main', departPos=str(position), departSpeed=str(speed))


def scenario(folder, name):
    label = uuid.uuid4().hex
    a = start(folder / 'old/net.xml', label + 'a')
    b = None
    try:
        b = start(folder / 'new/net.xml', label + 'b')
        a.route.add('main', ['WJ', 'JE'])
        # Program's controlled links are NJ->JS, WJ->JE. Pick by link identity.
        links = a.trafficlight.getControlledLinks('J')
        west_link = next(i for i, group in enumerate(links) if any(x[0] == 'WJ_0' for x in group))
        states = ''.join('r' if i == west_link else 'G' for i in range(len(links)))
        import traci
        green = ''.join('G' if i == west_link else 'r' for i in range(len(links)))
        logic = traci.trafficlight.Logic('probe', 0, 0, [traci.trafficlight.Phase(60, states),
                    traci.trafficlight.Phase(3, states.replace('G', 'y')),
                    traci.trafficlight.Phase(60, green), traci.trafficlight.Phase(3, green.replace('G', 'y'))])
        a.trafficlight.setProgramLogic('J', logic)
        a.trafficlight.setProgram('J', 'probe')
        if name == 'red_queue':
            for i in range(5):
                add(a, f'car{i}', 150 - i * 10, 8)
            for _ in range(150):
                a.simulationStep()
            assert len(a.vehicle.getIDList()) == 5 and max(a.vehicle.getSpeed(v) for v in a.vehicle.getIDList()) < .1
            a.trafficlight.setPhaseDuration('J', 2)  # verify the queue restarts after the same switch
        elif name == 'inside_junction':
            a.trafficlight.setPhase('J', 2)
            add(a, 'car', 170, 8)
            for _ in range(100):
                a.simulationStep()
                if a.vehicle.getRoadID('car').startswith(':'):
                    break
            assert a.vehicle.getRoadID('car').startswith(':'), 'Did not reach internal lane'
        else:
            a.trafficlight.setPhase('J', 2)
            add(a, 'ego', 140, 0)
            add(a, 'follower', 95, 12)
            a.simulationStep()
            a.vehicle.setSpeedMode('ego', 0)
            a.vehicle.setLaneChangeMode('ego', 0)
            a.vehicle.setSpeed('ego', 0)
            for _ in range(5):
                a.simulationStep()
        for _ in range(round(a.simulation.getTime() * 10)):
            b.simulationStep()
        result = transfer(a, b)
        source_ids = sorted(a.vehicle.getIDList())
        divergence = 0.
        collisions = teleports = 0
        for _ in range(100):
            a.simulationStep()
            b.simulationStep()
            assert sorted(a.vehicle.getIDList()) == sorted(b.vehicle.getIDList()), 'Vehicle disappeared at handoff'
            assert a.trafficlight.getRedYellowGreenState('J') == b.trafficlight.getRedYellowGreenState('J')
            for vid in a.vehicle.getIDList():
                divergence = max(divergence, math.dist(a.vehicle.getPosition(vid), b.vehicle.getPosition(vid)))
            collisions += b.simulation.getCollidingVehiclesNumber()
            teleports += b.simulation.getStartingTeleportNumber()
        if name == 'ego_braking':
            assert b.vehicle.getSpeed('follower') < .1, 'Follower did not brake for transferred ego'
        result.update(scenario=name, source_ids=source_ids, divergence_10s_m=divergence,
                      collisions=collisions, teleports=teleports,
                      passed=divergence < .05 and collisions == 0 and teleports == 0)
        return result
    finally:
        if b is not None:
            b.close()
        a.close()


def run(output):
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    networks(output)
    results = []
    for name in ('red_queue', 'inside_junction', 'ego_braking'):
        try:
            result = scenario(output, name)
        except Exception as exc:
            result = {'scenario': name, 'passed': False, 'error': f'{type(exc).__name__}: {exc}'}
        results.append(result)
        print(json.dumps(result), flush=True)
        write_json(output / 'report.json', {'results': results, 'synthetic': True,
                    'arbitrary_osm_handoff_verified': False, 'passed': all(r['passed'] for r in results)})
    return all(r['passed'] for r in results)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    raise SystemExit(0 if run(parser.parse_args().output) else 1)
