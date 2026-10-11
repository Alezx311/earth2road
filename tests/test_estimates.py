import json
from pathlib import Path
import tempfile
import unittest

from akadem_maps import estimates


class EstimateTest(unittest.TestCase):
    def test_base_ranges_grow_with_size_and_v2_is_slower(self):
        small = estimates.estimate('build', 'legacy', 1.0)
        large = estimates.estimate('build', 'legacy', 16.0)
        self.assertLess(small[0], small[1])
        self.assertLess(small[1], large[1])
        self.assertLess(large[0], estimates.estimate('build', 'v2', 16.0)[0])
        self.assertLess(large[1], estimates.estimate('build', 'v2', 16.0)[1])

    def test_measured_runs_fall_inside_the_base_range(self):
        # Bilychi 4×4 km: legacy 14.6 min, v2 68 min; Khreshchatyk 2 km v2 44 min.
        for mode, km2, minutes in (('legacy', 16.0, 14.6), ('v2', 16.0, 68.0), ('v2', 4.07, 44.0)):
            low, high = estimates.estimate('build', mode, km2)
            self.assertTrue(low <= minutes <= high, (mode, km2, minutes, low, high))
        low, high = estimates.estimate('export', 'compact', 112)
        self.assertTrue(low <= 18.0 <= high)

    def test_export_modes_share_the_full_detail_base(self):
        self.assertEqual(estimates.estimate('export', 'balanced+kerbs', 50), estimates.estimate('export', 'balanced', 50))

    def test_history_replaces_base_rates_after_two_runs(self):
        one = [{'kind': 'build', 'mode': 'v2', 'size': 4.0, 'seconds': 600.0}]
        self.assertEqual(estimates.coefficients('build', 'v2', one)[1], 0)
        two = one + [{'kind': 'build', 'mode': 'v2', 'size': 4.0, 'seconds': 840.0}]
        (o_lo, _, r_lo, r_hi), runs = estimates.coefficients('build', 'v2', two)
        self.assertEqual(runs, 2)
        self.assertAlmostEqual(r_lo, (10 - o_lo) / 4)
        self.assertAlmostEqual(r_hi, max((14 - o_lo) / 4, (12 - o_lo) / 4 * 1.25))   # at least median × 1.25
        other = two + [{'kind': 'build', 'mode': 'legacy', 'size': 1.0, 'seconds': 9000.0}]
        self.assertEqual(estimates.coefficients('build', 'v2', other), estimates.coefficients('build', 'v2', two))

    def test_record_and_read_skip_broken_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'logs/timings.jsonl'
            estimates.record(path, 'export', 'compact', 34, 300.04, id='x')
            with path.open('a', encoding='utf8') as f:
                f.write('not json\n' + json.dumps({'kind': 'build', 'mode': 'v2', 'size': 0, 'seconds': 5}) + '\n')
            runs = estimates.read_history(path)
            self.assertEqual(runs, [{'kind': 'export', 'mode': 'compact', 'size': 34, 'seconds': 300.0, 'id': 'x'}])
            self.assertEqual(estimates.read_history(Path(tmp)/'missing.jsonl'), [])

    def test_table_lists_every_mode(self):
        table = estimates.table([{'kind': 'export', 'mode': 'balanced+terrain', 'size': 10, 'seconds': 60}])
        self.assertEqual(set(table['build']), {'legacy', 'v2'})
        self.assertIn('balanced+terrain', table['export'])
        self.assertEqual(table['build']['v2']['runs'], 0)


BASE = {'v2': {'download': {'const': 1.0, 'osm_fetch': 10.0, 'osm_fetch_knodes': 5.0, 'dem_missing': 0.5},
               'roads': {'const': 2.0, 'knodes': 60.0, 'kroads': 0.0},
               'buildings': {'const': 0.0, 'kbuildings': 10.0},
               'scenery': {'const': 3.0, 'area_km2': 4.0, 'knodes': 5.0, 'kbuildings': 2.0},
               'export': {'const': 1.0, 'knodes': 2.0, 'kbuildings': 1.0}}}
CITY = {'area_km2': .25, 'roads': 190, 'road_nodes': 516, 'buildings': 200, 'dem_missing': 0,
        'osm_ready': True, 'basis': 'osm_snapshot'}


class StageEstimateTest(unittest.TestCase):
    def test_stage_groups_cover_build_export_and_probe_names(self):
        self.assertEqual(estimates.stage_group('road_geometry'), 'roads')
        self.assertEqual(estimates.stage_group('godot_export_and_demand'), 'export')
        self.assertEqual(estimates.stage_group('install'), 'export')
        self.assertIsNone(estimates.stage_group('sumo_start_and_warmup'))

    def test_stage_seconds_from_iso_times_and_elapsed(self):
        iso = [{'event': 'stage', 'stage': 'sources', 'time': '2026-10-10T08:58:00+00:00'},
               {'event': 'download', 'time': '2026-10-10T08:58:05+00:00'},
               {'event': 'stage', 'stage': 'network', 'time': '2026-10-10T08:58:20+00:00'},
               {'event': 'stage', 'stage': 'roads', 'time': '2026-10-10T08:59:00+00:00'},
               {'event': 'result', 'time': '2026-10-10T09:00:00+00:00'}]
        self.assertEqual(estimates.stage_seconds(iso), {'download': 20.0, 'roads': 100.0})
        elapsed = [{'event': 'stage', 'stage': 'buildings', 'elapsed_s': 1.0},
                   {'event': 'stage', 'stage': 'export', 'elapsed_s': 4.0},
                   {'event': 'result', 'elapsed_s': 6.5}]
        self.assertEqual(estimates.stage_seconds(elapsed), {'buildings': 3.0, 'export': 2.5})

    def test_density_drives_the_prediction(self):
        sparse = {**CITY, 'roads': 10, 'road_nodes': 30, 'buildings': 5}
        dense = estimates.predict(CITY, 'v2', base=BASE)
        self.assertGreater(sum(dense.values()), sum(estimates.predict(sparse, 'v2', base=BASE).values()))
        self.assertAlmostEqual(dense['roads'], 2.0 + 60.0 * .516)
        fetching = estimates.predict({**CITY, 'osm_ready': False, 'dem_missing': 4}, 'v2', base=BASE)
        self.assertAlmostEqual(fetching['download'] - dense['download'], 10.0 + 5.0 * .516 + 2.0)

    def test_area_only_range_is_wider_than_counted(self):
        counted = estimates.build_estimate(CITY, 'v2', base=BASE)
        guess = estimates.build_estimate({'area_km2': .25, 'basis': 'area_only', 'osm_ready': True}, 'v2', base=BASE)
        width = lambda e: e['seconds'][1] / e['seconds'][0]
        self.assertGreater(width(guess), width(counted))
        self.assertEqual(guess['basis'], 'area_only')
        self.assertLessEqual(counted['seconds'][0], counted['expected_s'])
        self.assertLessEqual(counted['expected_s'], counted['seconds'][1])

    def test_machine_runs_rescale_groups(self):
        expected = estimates.predict(CITY, 'v2', base=BASE)
        slow = {g: s * 2.0 for g, s in expected.items()}
        history = [{'kind': 'build', 'mode': 'v2', 'size': .25, 'seconds': 1, 'features': CITY, 'stages': slow}] * 3
        history.append({'kind': 'build', 'mode': 'v2', 'size': 4, 'seconds': 900})   # old record: ignored
        tuned = estimates.build_estimate(CITY, 'v2', history, base=BASE)
        self.assertEqual(tuned['machine_runs'], 3)
        self.assertAlmostEqual(tuned['stages']['roads'], slow['roads'], delta=.05)
        self.assertAlmostEqual(tuned['stages']['scenery'], slow['scenery'], delta=.05)
        # Area-only runs say nothing about per-feature speed.
        vague = [{**history[0], 'features': {**CITY, 'basis': 'area_only'}}] * 3
        self.assertEqual(estimates.build_estimate(CITY, 'v2', vague, base=BASE)['machine_runs'], 0)

    def test_nnls_and_fit_recover_nonnegative_coefficients(self):
        import numpy as np
        a = np.array([[1, 0], [1, 1], [1, 2], [1, 3]], float)
        self.assertTrue(np.allclose(estimates.nnls(a, a @ [2.0, 3.0]), [2.0, 3.0]))
        self.assertTrue((estimates.nnls(a, a @ [5.0, -1.0]) >= 0).all())
        runs = []
        for nodes, buildings in ((100, 50), (500, 200), (1800, 360), (11000, 3300)):
            features = {**CITY, 'road_nodes': nodes, 'roads': nodes // 3, 'buildings': buildings}
            runs.append({'mode': 'v2', 'features': features, 'stages': estimates.predict(features, 'v2', base=BASE)})
        fitted = estimates.fit(runs, 'v2')
        for run in runs:
            self.assertAlmostEqual(sum(estimates.predict(run['features'], 'v2', base={'v2': fitted}).values()),
                                   sum(run['stages'].values()), delta=1.0)

    def test_shipped_base_covers_both_road_builders(self):
        for mode in ('legacy', 'v2'):
            self.assertEqual(set(estimates.STAGE_BASE[mode]), set(estimates.GROUP_ORDER))
            self.assertGreater(sum(estimates.predict(CITY, mode).values()), 0)


if __name__ == '__main__':
    unittest.main()
