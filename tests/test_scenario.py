"""Scripted road situations: schema checks and the timeline, both pure."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))

import scenario

MINIMAL = {'id': 'x', 'name': 'x', 'timeline': [
    {'at': 10, 'do': 'incident', 'kind': 'jam', 'lonlat': [30.3, 50.4]}]}


class ShapeTests(unittest.TestCase):
    def test_minimal_scenario_is_valid(self):
        self.assertTrue(scenario.validate_shape(MINIMAL))

    def test_shipped_scenarios_are_valid(self):
        files = sorted((ROOT / 'config/scenarios').glob('*.json'))
        self.assertTrue(files, 'no scenarios shipped')
        for path in files:
            scenario.validate_shape(scenario.json.loads(path.read_text()))

    def test_unknown_verb_is_rejected(self):
        bad = {**MINIMAL, 'timeline': [{'at': 0, 'do': 'launch_rocket'}]}
        with self.assertRaises(ValueError):
            scenario.validate_shape(bad)

    def test_incident_needs_a_place(self):
        bad = {**MINIMAL, 'timeline': [{'at': 0, 'do': 'incident', 'kind': 'jam'}]}
        with self.assertRaises(ValueError):
            scenario.validate_shape(bad)

    def test_negative_time_is_rejected(self):
        bad = {**MINIMAL, 'timeline': [{'at': -5, 'do': 'incident_clear'}]}
        with self.assertRaises(ValueError):
            scenario.validate_shape(bad)

    def test_empty_timeline_is_rejected(self):
        with self.assertRaises(ValueError):
            scenario.validate_shape({'id': 'x', 'name': 'x', 'timeline': []})

    def test_density_out_of_range_is_rejected(self):
        with self.assertRaises(ValueError):
            scenario.validate_shape({**MINIMAL, 'density': -1})


class TimelineTests(unittest.TestCase):
    def setUp(self):
        self.timeline = scenario.Timeline({'id': 'x', 'name': 'x', 'timeline': [
            {'at': 30, 'do': 'incident_clear'},
            {'at': 0, 'do': 'density', 'value': 500},
            {'at': 10, 'do': 'incident', 'kind': 'jam', 'edge': 'e1'},
            {'at': 40, 'do': 'stop'},
        ]})

    def test_events_fire_in_time_order_and_only_once(self):
        self.assertEqual([e['do'] for e in self.timeline.due(0)], ['density'])
        self.assertEqual(self.timeline.due(5), [])
        self.assertEqual([e['do'] for e in self.timeline.due(12)], ['incident'])
        self.assertEqual([e['do'] for e in self.timeline.due(35)], ['incident_clear'])

    def test_late_first_call_fires_everything_due(self):
        self.assertEqual([e['do'] for e in self.timeline.due(31)],
                         ['density', 'incident', 'incident_clear'])

    def test_stop_ends_the_timeline(self):
        self.timeline.due(100)
        self.assertTrue(self.timeline.finished)
        self.assertEqual(self.timeline.log[-1][1], 'stop')

    def test_running_out_of_events_finishes_too(self):
        timeline = scenario.Timeline({'id': 'x', 'name': 'x', 'timeline': [
            {'at': 1, 'do': 'incident_clear'}]})
        timeline.due(2)
        self.assertTrue(timeline.finished)


class CommandTests(unittest.TestCase):
    def test_lonlat_is_resolved_through_the_caller(self):
        event = {'at': 0, 'do': 'incident', 'kind': 'accident', 'lonlat': [30.3, 50.4],
                 'duration': 60}
        msg = scenario.to_command(event, lambda lon, lat: [lon, 0.0, lat])
        self.assertEqual(msg['p'], [30.3, 0.0, 50.4])
        self.assertEqual(msg['kind'], 'accident')
        self.assertEqual(msg['duration'], 60)

    def test_edge_addressing_still_works(self):
        msg = scenario.to_command({'at': 0, 'do': 'incident', 'kind': 'jam', 'edge': 'e1',
                                   'pos': 25, 'lane_index': 2}, None)
        self.assertEqual((msg['edge'], msg['pos'], msg['lane_index']), ('e1', 25, 2))

    def test_traffic_light_command(self):
        msg = scenario.to_command({'at': 0, 'do': 'tls', 'action': 'allred', 'tls': 'j1'}, None)
        self.assertEqual(msg, {'type': 'tls', 'action': 'allred', 'id': 'j1'})


if __name__ == '__main__':
    unittest.main()
