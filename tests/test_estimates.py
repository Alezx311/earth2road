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


if __name__ == '__main__':
    unittest.main()
