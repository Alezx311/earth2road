#!/usr/bin/env python3
"""Scripted road situations: config/scenarios/<id>.json played back by the bridge.

A scenario is invented. It is not a recorded Kyiv incident and not measured demand; it
only decides when the bridge applies the same commands the control panel would send.

Places are addressed by longitude and latitude, not by SUMO edge ids: edge ids are
netconvert output and change on every rebuild, so an edge-addressed scenario silently
stops matching the map it was written for. Edge ids stay allowed for quick debugging.
"""
import json
import math
from pathlib import Path

VERBS = ('incident', 'incident_remove', 'incident_clear', 'tls', 'density', 'speed', 'stop')


def path_for(name, root):
    """A scenario by id ('morning_accident') or by path."""
    candidate = Path(name)
    if candidate.suffix == '.json' and candidate.exists():
        return candidate
    return Path(root) / 'config/scenarios' / f'{name}.json'


def load(name, root):
    spec = json.loads(path_for(name, root).read_text())
    validate_shape(spec)
    return spec


def validate_shape(spec):
    """Everything checkable without a network. Raises ValueError with an English message."""
    if not isinstance(spec, dict):
        raise ValueError('A scenario must be a JSON object')
    for key in ('id', 'name'):
        if not isinstance(spec.get(key), str) or not spec[key]:
            raise ValueError(f'Scenario has no "{key}" field')
    events = spec.get('timeline')
    if not isinstance(events, list) or not events:
        raise ValueError('Scenario has no events in "timeline"')
    for i, event in enumerate(events):
        where = f'event {i + 1}'
        if not isinstance(event, dict):
            raise ValueError(f'{where}: expected an object')
        at = event.get('at')
        if not isinstance(at, (int, float)) or not math.isfinite(at) or at < 0:
            raise ValueError(f'{where}: "at" must be a non-negative number of seconds')
        if event.get('do') not in VERBS:
            raise ValueError(f'{where}: unknown action "{event.get("do")}"')
        if event['do'] == 'incident':
            if not (_lonlat(event) or isinstance(event.get('edge'), str)):
                raise ValueError(f'{where}: "lonlat" or "edge" is required')
    for key, limits in (('density', (0, 100000)), ('speed', (0, 16))):
        if key in spec and not (isinstance(spec[key], int) and limits[0] <= spec[key] <= limits[1]):
            raise ValueError(f'Field "{key}" is outside {limits}')
    return True


def _lonlat(event):
    value = event.get('lonlat')
    return (isinstance(value, list) and len(value) == 2
            and all(isinstance(v, (int, float)) and math.isfinite(v) for v in value))


class Timeline:
    """Events of one scenario, each fired exactly once, in order, when its time comes."""

    def __init__(self, spec):
        self.spec = spec
        self.events = sorted(spec['timeline'], key=lambda e: e['at'])
        self.index = 0
        self.log = []
        self.finished = False

    def due(self, elapsed):
        out = []
        while self.index < len(self.events) and self.events[self.index]['at'] <= elapsed:
            event = self.events[self.index]
            self.index += 1
            if event['do'] == 'stop':
                self.finished = True
                self.log.append((round(elapsed, 1), 'stop'))
                break
            out.append(event)
            self.log.append((round(elapsed, 1), event['do']))
        if self.index >= len(self.events):
            self.finished = True
        return out


def to_command(event, to_game_point=None):
    """One timeline event -> the control message the bridge already understands."""
    verb = event['do']
    if verb == 'incident':
        msg = {'type': 'incident', 'action': 'add', 'kind': event.get('kind', 'accident'),
               'duration': event.get('duration', 0)}
        if _lonlat(event) and to_game_point is not None:
            msg['p'] = to_game_point(*event['lonlat'])
        else:
            msg['edge'] = event['edge']
            msg['pos'] = event.get('pos', 10.0)
            msg['lane_index'] = event.get('lane_index', 0)
        if 'value_kmh' in event:
            msg['value_kmh'] = event['value_kmh']
        if 'id' in event:
            msg['id'] = event['id']
        return msg
    if verb == 'incident_remove':
        return {'type': 'incident', 'action': 'remove', 'id': event.get('id', '')}
    if verb == 'incident_clear':
        return {'type': 'incident', 'action': 'clear'}
    if verb == 'tls':
        msg = {'type': 'tls', 'action': event.get('action', 'restore'), 'id': event.get('tls', '')}
        if 'value' in event:
            msg['value'] = event['value']
        return msg
    return None
