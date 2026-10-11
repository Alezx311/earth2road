"""Feasibility gates must not confuse missing evidence with a passed runtime test."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from akadem_maps.streaming_probe import StageClock, acceptance, square
from akadem_maps.traffic_handoff import HandoffRejected, transfer


class MeasurementTests(unittest.TestCase):
    def test_monotonic_exclusive_intervals_and_repeated_stage(self):
        now = [0.]
        events = []
        clock = StageClock(events.append, lambda: now[0])
        now[0] = 1
        clock.emit('stage', stage='sources')
        now[0] = 3
        clock.emit('download', source='terrain')
        now[0] = 5
        clock.emit('stage', stage='sources')
        now[0] = 7
        clock.emit('stage', stage='network')
        now[0] = 10
        self.assertEqual(clock.finish(), {'setup': 1, 'sources': 6, 'network': 3})
        self.assertEqual([r['elapsed_s'] for r in events], [1, 3, 5, 7])

    def test_fast_geometry_is_not_a_pass_without_collision_and_traffic(self):
        self.assertFalse(acceptance(1, None, None, 'cold')['pipeline_ready'])
        self.assertFalse(acceptance(1, {'spawn_supported': True}, {'vehicles': 0}, 'cold')['pipeline_ready'])
        good = acceptance(1, {'spawn_supported': True}, {'vehicles': 4}, 'geometry')
        self.assertTrue(good['pipeline_within_30s'])
        self.assertEqual(good['cold_start_to_control'], 'not_tested')
        self.assertFalse(good['streaming_release'])
        self.assertFalse(acceptance(31, {'spawn_supported': True}, {'vehicles': 4}, 'cold')['pipeline_within_30s'])

    def test_metric_area_and_antimeridian_rejection(self):
        from pyproj import Geod
        w, s, e, n = square(30., 50., 500)
        distance = Geod(ellps='WGS84').inv(w, 50, e, 50)[2]
        self.assertAlmostEqual(distance, 500, places=3)
        for point in [(179.9999, 50, 2000), (0, 85, 500), (0, 0, float('nan'))]:
            with self.assertRaises(ValueError):
                square(*point)

    def test_handoff_rejects_dirty_destination_without_touching_source(self):
        from unittest.mock import Mock
        source, destination = Mock(), Mock()
        destination.vehicle.getIDList.return_value = ['already_here']
        with self.assertRaisesRegex(HandoffRejected, 'empty shadow'):
            transfer(source, destination)
        self.assertFalse(source.mock_calls)

    def test_missing_route_and_different_lane_reject_before_import(self):
        from unittest.mock import Mock
        a, b = Mock(), Mock()
        b.vehicle.getIDList.return_value = []
        b.simulation.getPendingVehicles.return_value = []
        b.simulation.getTime.return_value = 1.
        b.edge.getIDList.return_value = ['edge']
        b.lane.getIDList.return_value = ['edge_0']
        b.vehicletype.getIDList.return_value = ['car']
        row = {'id': 'visible', 'lane': 'edge_0', 'type': 'car', 'route': ['edge', 'gone']}
        state = {'time': 1., 'vehicles': [row], 'signals': []}
        with patch('akadem_maps.traffic_handoff.snapshot', return_value=state):
            with self.assertRaisesRegex(HandoffRejected, 'remaining route'):
                transfer(a, b)
        b.vehicle.add.assert_not_called()
        row['route'] = ['edge']
        a.lane.getShape.return_value = [(0, 0), (20, 0)]
        b.lane.getShape.return_value = [(0, 0), (20, 1)]
        with patch('akadem_maps.traffic_handoff.snapshot', return_value=state), \
                patch('akadem_maps.traffic_handoff._type_signature', return_value=('car',)):
            with self.assertRaisesRegex(HandoffRejected, 'lane geometry'):
                transfer(a, b)
        b.vehicle.add.assert_not_called()

    def test_changed_signal_link_order_rejects_before_modifying_signal(self):
        from unittest.mock import Mock
        a, b = Mock(), Mock()
        b.vehicle.getIDList.return_value = []
        b.simulation.getPendingVehicles.return_value = []
        b.simulation.getTime.return_value = 1.
        b.edge.getIDList.return_value = []
        b.lane.getIDList.return_value = []
        b.vehicletype.getIDList.return_value = []
        b.trafficlight.getIDList.return_value = ['J']
        b.trafficlight.getControlledLinks.return_value = [('other_0', 'exit_0', ':via_0')]
        state = {'time': 1., 'vehicles': [], 'signals': [{'id': 'J', 'links': [('entry_0', 'exit_0', ':via_0')]}]}
        with patch('akadem_maps.traffic_handoff.snapshot', return_value=state):
            with self.assertRaisesRegex(HandoffRejected, 'controlled link order'):
                transfer(a, b)
        b.trafficlight.setProgramLogic.assert_not_called()


class SumoHandoffIntegration(unittest.TestCase):
    def test_two_process_overlap_red_queue_internal_lane_and_ego(self):
        from tools.streaming_traffic_lab import run
        with tempfile.TemporaryDirectory() as directory:
            self.assertTrue(run(Path(directory) / 'lab'))


class SurfaceProbeTests(unittest.TestCase):
    def test_height_delta_missing_surface_and_bridge_identity_are_failures(self):
        from akadem_maps.streaming_probe import compare_surfaces
        from types import SimpleNamespace
        reference = SimpleNamespace(index={'offset': [0, 0], 'base_height': 100,
            'lanes': [{'id': 'lane', 'points': [[0, 2, 0], [4, 2, 0]], 'width': 3}],
            'bbox': [-1, -1, 5, 1]}, geo=lambda p: p)
        meta = {'ways': ['observed_way'], 'levels': [[1, True, False]]}
        reference.hits = lambda x, y: [(102, 'lane:a', meta)]
        candidate = SimpleNamespace(index=reference.index)
        for hits, field in [([], 'candidate_missing'), ([(103, 'lane:a', meta)], 'over_tolerance'),
                            ([(102, 'lane:ground', {'ways': ['other'], 'levels': [[0, False, False]]})], 'topology_unmatched')]:
            candidate.hits = lambda x, y: hits
            with patch('akadem_maps.streaming_probe.SurfaceWorld', side_effect=[reference, candidate]):
                result = compare_surfaces('reference', 'candidate')
            self.assertFalse(result['passed'])
            self.assertGreater(result[field], 0)
        candidate.hits = reference.hits
        with patch('akadem_maps.streaming_probe.SurfaceWorld', side_effect=[reference, candidate]):
            self.assertTrue(compare_surfaces('reference', 'candidate')['passed'])

    def test_zero_samples_do_not_pass(self):
        from types import SimpleNamespace
        from akadem_maps.streaming_probe import compare_surfaces
        fake = SimpleNamespace(index={'lanes': [], 'bbox': [0, 0, 1, 1]})
        with patch('akadem_maps.streaming_probe.SurfaceWorld', return_value=fake):
            self.assertFalse(compare_surfaces('a', 'b')['passed'])
