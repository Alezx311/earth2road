"""Experimental two-process TraCI handoff for a compatible overlap.

The source is never mutated. A rejected or partially imported destination must be
discarded; the caller keeps the source active. This is intentionally not wired to
the game bridge: arbitrary rebuilt OSM networks do not yet have stable identities.
"""
import math


class HandoffRejected(ValueError):
    pass


def _require(condition, reason):
    if not condition:
        raise HandoffRejected(reason)


def _type_signature(c, name):
    return tuple(getattr(c.vehicletype, 'get' + field)(name) for field in
                 ('VehicleClass', 'Length', 'Width', 'Height', 'MinGap', 'MaxSpeed',
                  'Accel', 'Decel', 'EmergencyDecel', 'Imperfection', 'Tau'))


def snapshot(c, vehicles=None):
    ids = sorted(c.vehicle.getIDList() if vehicles is None else vehicles)
    now = c.simulation.getTime()
    rows = []
    for vid in ids:
        v = c.vehicle
        _require(not v.getStops(vid), f'{vid}: scheduled stops are not supported by this prototype')
        _require(abs(v.getLateralLanePosition(vid)) < .001, f'{vid}: lateral manoeuvre in progress')
        route = list(v.getRoute(vid))[v.getRouteIndex(vid):]
        _require(bool(route), f'{vid}: no remaining route')
        rows.append({'id': vid, 'type': v.getTypeID(vid), 'route': route,
                     'lane': v.getLaneID(vid), 'position': v.getLanePosition(vid),
                     'xy': v.getPosition(vid), 'speed': v.getSpeed(vid),
                     'acceleration': v.getAcceleration(vid), 'angle': v.getAngle(vid),
                     'speed_factor': v.getSpeedFactor(vid), 'signals': v.getSignals(vid),
                     'speed_mode': v.getSpeedMode(vid), 'lane_change_mode': v.getLaneChangeMode(vid),
                     'color': v.getColor(vid)})
    signals = []
    for tid in sorted(c.trafficlight.getIDList()):
        program = c.trafficlight.getProgram(tid)
        logic = next((l for l in c.trafficlight.getAllProgramLogics(tid) if l.programID == program), None)
        _require(logic is not None and logic.type == 0, f'{tid}: only fixed-time signal programs supported')
        signals.append({'id': tid, 'program': program, 'logic': logic,
                        'links': c.trafficlight.getControlledLinks(tid),
                        'phase': c.trafficlight.getPhase(tid),
                        'state': c.trafficlight.getRedYellowGreenState(tid),
                        'remaining': c.trafficlight.getNextSwitch(tid) - now})
    return {'time': now, 'vehicles': rows, 'signals': signals}


def transfer(source, destination, *, vehicles=None, xy_shift=(0., 0.), tolerance=.02):
    """Transfer at a paused step boundary; return measured immediate state errors.

    xy_shift maps source SUMO XY to destination SUMO XY (not Godot coordinates).
    Types must already be configured identically. Imported cars are released back
    to SUMO, except the externally controlled ego, whose speed remains commanded.
    Hidden driver RNG, waiting time and lane-change model state are NOT preserved.
    """
    _require(all(math.isfinite(x) for x in xy_shift) and len(xy_shift) == 2,
             'xy_shift must contain two finite values')
    _require(math.isfinite(tolerance) and tolerance >= 0, 'invalid tolerance')
    _require(not destination.vehicle.getIDList() and not destination.simulation.getPendingVehicles(),
             'Destination must be an empty shadow simulation')
    state = snapshot(source, vehicles)
    _require(abs(destination.simulation.getTime() - state['time']) < 1e-6,
             'Simulation clocks must agree at the handoff boundary')
    edges = set(destination.edge.getIDList())
    lanes = set(destination.lane.getIDList())
    types = set(destination.vehicletype.getIDList())
    checked_lanes, checked_types = set(), set()
    for row in state['vehicles']:
        vid, lane, kind = row['id'], row['lane'], row['type']
        _require(set(row['route']) <= edges, f'{vid}: remaining route leaves destination network')
        _require(lane in lanes, f'{vid}: lane identity missing: {lane}')
        _require(kind in types, f'{vid}: vehicle type missing: {kind}')
        if kind not in checked_types:
            _require(_type_signature(source, kind) == _type_signature(destination, kind),
                     f'{vid}: vehicle type differs: {kind}')
            checked_types.add(kind)
        if lane not in checked_lanes:
            a, b = source.lane.getShape(lane), destination.lane.getShape(lane)
            _require(len(a) == len(b) and all(math.dist((p[0] + xy_shift[0], p[1] + xy_shift[1]), q) <= tolerance
                     for p, q in zip(a, b)), f'{vid}: lane geometry differs: {lane}')
            _require(abs(source.lane.getLength(lane) - destination.lane.getLength(lane)) <= tolerance,
                     f'{vid}: lane length differs: {lane}')
            checked_lanes.add(lane)
    target_signals = set(destination.trafficlight.getIDList())
    for signal in state['signals']:
        tid = signal['id']
        _require(tid in target_signals, f'{tid}: signal identity missing')
        _require(destination.trafficlight.getControlledLinks(tid) == signal['links'],
                 f'{tid}: controlled link order differs')
    # No destination or source mutation above this line.
    try:
        for signal in state['signals']:
            tid = signal['id']
            destination.trafficlight.setProgramLogic(tid, signal['logic'])
            destination.trafficlight.setProgram(tid, signal['program'])
            destination.trafficlight.setPhase(tid, signal['phase'])
            destination.trafficlight.setPhaseDuration(tid, max(0., signal['remaining']))
        for i, row in enumerate(state['vehicles']):
            vid = row['id']
            rid = f'__handoff_{i}'
            destination.route.add(rid, row['route'])
            v = destination.vehicle
            v.add(vid, rid, typeID=row['type'], depart='now', departSpeed=str(row['speed']))
            v.moveTo(vid, row['lane'], row['position'])
            v.setSpeedFactor(vid, row['speed_factor'])
            v.setPreviousSpeed(vid, row['speed'], row['acceleration'])
            v.setSpeedMode(vid, row['speed_mode'])
            v.setLaneChangeMode(vid, row['lane_change_mode'])
            v.setColor(vid, row['color'])
            v.setSignals(vid, row['signals'])
            v.setSpeed(vid, row['speed'] if vid == 'ego' else -1)
        errors = []
        for row in state['vehicles']:
            vid, v = row['id'], destination.vehicle
            xy = (row['xy'][0] + xy_shift[0], row['xy'][1] + xy_shift[1])
            errors.append({'id': vid, 'position_m': math.dist(v.getPosition(vid), xy),
                           'speed_mps': abs(v.getSpeed(vid) - row['speed']),
                           'angle_deg': abs((v.getAngle(vid) - row['angle'] + 180) % 360 - 180),
                           'lane_equal': v.getLaneID(vid) == row['lane']})
        _require(all(e['position_m'] <= tolerance and e['speed_mps'] < .001 and
                     e['angle_deg'] < .1 and e['lane_equal'] for e in errors),
                 f'Imported state differs: {errors}')
        _require(all(destination.trafficlight.getRedYellowGreenState(s['id']) == s['state'] and
                     abs(destination.trafficlight.getNextSwitch(s['id']) - state['time'] - s['remaining']) < .001
                     for s in state['signals']), 'Imported signal state differs')
    except Exception as exc:
        raise HandoffRejected(f'Discard shadow simulation; source is unchanged: {exc}') from exc
    return {'vehicles': len(errors), 'signals': len(state['signals']), 'errors': errors,
            'full_driver_state_preserved': False}
