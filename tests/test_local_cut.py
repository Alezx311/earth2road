import random
import unittest

import shapely
from shapely.geometry import LineString, Point, Polygon, box
from shapely.ops import unary_union

from akadem_maps.core import scene


def road_grid():
    """A district-like cut: a 4 km street grid and round plazas between the streets (> LOCAL_CUT_COORDS)."""
    lines = [LineString([(x, 0), (x + 37, 4000)]) for x in range(0, 4000, 90)]
    lines += [LineString([(0, y), (4000, y + 23)]) for y in range(0, 4000, 110)]
    plazas = [Point(x + 45, y + 55).buffer(15, quad_segs=64) for x in range(0, 4000, 90) for y in range(0, 4000, 110)]
    return unary_union([l.buffer(6, quad_segs=64) for l in lines] + plazas)


class LocalCutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cut = road_grid()
        cls.local = scene.LocalCut(cls.cut)

    def test_large_geometry_is_tiled(self):
        self.assertGreater(shapely.get_num_coordinates(self.cut), scene.LOCAL_CUT_COORDS)
        self.assertIsNotNone(self.local.tree)

    def test_small_geometry_keeps_the_exact_operation(self):
        small = box(0, 0, 10, 10)
        self.assertIs(scene.LocalCut(small).around(LineString([(1, 1), (2, 2)])), small)

    def test_area_fully_under_the_cut_chains_into_the_next_cut(self):
        # Detroit 4 km 07.10.2026: a 44 m² green fully under the road cover became empty,
        # then the parking cut built box(NaN...) from its bounds and stopped the build.
        green = Point(45, 0).buffer(3)               # inside the first street of the grid
        left = self.local.subtract_from(green)
        self.assertTrue(left.is_empty)
        self.assertTrue(self.local.subtract_from(left).is_empty)
        self.assertTrue(self.local.around(left).is_empty)

    def test_lines_match_direct_difference(self):
        rng = random.Random(311)
        for _ in range(200):
            x, y = rng.uniform(0, 3900), rng.uniform(0, 3900)
            line = LineString([(x, y), (x + rng.uniform(-300, 300), y + rng.uniform(-300, 300))])
            direct, tiled = line.difference(self.cut), self.local.subtract_from(line)
            self.assertAlmostEqual(direct.length, tiled.length, delta=1e-6)
            self.assertEqual(direct.is_empty, tiled.is_empty)
            if not direct.is_empty:
                self.assertLess(direct.hausdorff_distance(tiled), 1e-6)

    def test_polygons_match_direct_difference(self):
        rng = random.Random(7)
        for _ in range(40):
            x, y, r = rng.uniform(0, 3500), rng.uniform(0, 3500), rng.uniform(20, 900)
            green = Polygon([(x, y), (x + r, y + r / 3), (x + r / 2, y + r)])
            direct, tiled = green.difference(self.cut), self.local.subtract_from(green)
            self.assertTrue(tiled.is_valid)
            self.assertAlmostEqual(direct.area, tiled.area, delta=1e-3)
            self.assertLess(direct.symmetric_difference(tiled).area, 1e-3)

    def test_query_outside_the_cut_keeps_geometry(self):
        far = LineString([(10000, 10000), (10100, 10000)])
        self.assertEqual(self.local.subtract_from(far).length, far.length)


class DrapeSplitTests(unittest.TestCase):
    def test_split_drape_matches_cell_by_cell(self):
        ground = box(0, 0, 1200, 900).difference(road_grid())
        tri_area = lambda tris: sum(Polygon(t).area for t in tris)
        old = scene.DRAPE_SPLIT_WORK
        try:
            scene.DRAPE_SPLIT_WORK = 10 ** 18
            direct = scene.draped_triangles(ground)
            scene.DRAPE_SPLIT_WORK = 1000
            split = scene.draped_triangles(ground)
        finally:
            scene.DRAPE_SPLIT_WORK = old
        self.assertAlmostEqual(tri_area(direct), ground.area, delta=1e-3)
        self.assertAlmostEqual(tri_area(split), tri_area(direct), delta=1e-3)
        self.assertLess(abs(len(split) - len(direct)), len(direct) * 0.01 + 5)
        for tri in split:  # every triangle stays inside one 20 m cell
            xs, ys = [p[0] for p in tri], [p[1] for p in tri]
            cx, cy = sum(xs) / 3 // scene.GROUND_CELL, sum(ys) / 3 // scene.GROUND_CELL
            self.assertTrue(all(cx * 20 - 1e-6 <= x <= cx * 20 + 20 + 1e-6 for x in xs))
            self.assertTrue(all(cy * 20 - 1e-6 <= y <= cy * 20 + 20 + 1e-6 for y in ys))


if __name__ == '__main__':
    unittest.main()
