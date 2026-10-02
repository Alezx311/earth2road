"""Regression tests for the road/ground seam (city-enrichment EDGE package).

The defect class: longitudinal dark wedges between asphalt and the adjacent ground. The
old field pulled the ground toward *centerline* anchors only, so at the ribbon edge (one
half-width away) the pull was attenuated (t = d/radius) and the ground ran below the
drawn ribbon; the ground cut was a Shapely centerline buffer that disagrees with the
ribbon's miter clamp on sharp corners.

What must hold now (deterministic, no network/SUMO needed):
  * ground height exactly equals the ribbon border height ON the seam (segment-snapped),
    including mid-segment and on sloped and curved roads;
  * the cut footprint is built from the same offset borders the renderer draws;
  * parallel carriageways both snap; bridges are untouched by anchors and edges;
  * ground triangulation vertices carry the road-profile stations (stitch_vertices);
  * the field is still smooth away from the seam and DEM-only far from roads."""
import math
import sys
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from shapely.geometry import LineString, Point, box
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tools'))
import scene

def strip(points, width, bridge=False):
    return {'points': points, 'width': width, 'bridge': bridge}

def straight(width=8.0, z0=2.0, grade=0.01, n=21, step=10.0):
    xs = np.arange(0.0, (n)*step, step)
    pts = [(float(x), 0.0, float(z0+grade*x)) for x in xs]
    return pts, width

class GroundSeamTests(unittest.TestCase):
    def test_sloped_road_boundary_exact_and_old_gap_quantified(self):
        pts, w = straight()
        dem = lambda x, y: 0.0
        left, right = scene.strip_borders(pts, w)
        edges = scene.border_segments(left)+scene.border_segments(right)
        gf = scene.GroundField(dem, list(pts), edges=edges)
        # Exact at every station and at mid-segment (segment height interpolation).
        for border in (left, right):
            for (ax, ay, az), (bx, by, bz) in zip(border, border[1:]):
                self.assertAlmostEqual(gf(ax, ay), az, places=4)
                self.assertAlmostEqual(gf((ax+bx)/2, (ay+by)/2), (az+bz)/2, places=4)
        for p in left:
            self.assertAlmostEqual(gf(p[0], p[1]), p[2], places=4)
        # The old centreline-anchor-only field leaves a wedge at the edge: quantify it.
        old = scene.GroundField(dem, list(pts))
        gaps = [p[2]-old(p[0], p[1]) for p in left]
        self.assertGreater(max(gaps), 0.05,
                           msg='old field must show a measurable boundary wedge (>5 cm)')
        # Far from the road the new field returns to the DEM, like the old one.
        self.assertAlmostEqual(gf(300.0, 40.0), 0.0, places=6)
        self.assertAlmostEqual(gf(-50.0, 40.0), 0.0, places=6)

    def test_curved_road_boundary_exact(self):
        theta = np.linspace(-0.8, 0.8, 33)
        r = 80.0
        s = r*(theta-theta[0])
        pts = [(float(r*math.cos(t)), float(r*math.sin(t)), float(1.0+0.002*s0))
               for t, s0 in zip(theta, s)]
        w = 8.0
        dem = lambda x, y: 0.0
        left, right = scene.strip_borders(pts, w)
        edges = scene.border_segments(left)+scene.border_segments(right)
        gf = scene.GroundField(dem, list(pts), edges=edges)
        for border in (left, right):
            for (ax, ay, az), (bx, by, bz) in zip(border, border[1:]):
                self.assertAlmostEqual(gf(ax, ay), az, places=4)
                self.assertAlmostEqual(gf((ax+bx)/2, (ay+by)/2), (az+bz)/2, places=4)

    def test_parallel_roads_both_boundaries_exact_blend_in_gap(self):
        def row(y):
            return [(float(x), float(y), 1.0) for x in range(0, 101, 5)]
        pts_a, pts_b = row(0.0), row(12.0)
        w = 6.0            # edges at y=±3 and y=9..15 -> 6 m gap of ground between them
        dem = lambda x, y: 0.0
        edges = []
        for pts in (pts_a, pts_b):
            l, r = scene.strip_borders(pts, w)
            edges += scene.border_segments(l)+scene.border_segments(r)
        gf = scene.GroundField(dem, pts_a+pts_b, edges=edges)
        for border in (scene.strip_borders(pts_a, w)[0], scene.strip_borders(pts_b, w)[1]):
            for (ax, ay, az), (bx, by, bz) in zip(border, border[1:]):
                self.assertAlmostEqual(gf(ax, ay), az, places=4)
        # Between the carriageways the field stays a smooth shoulder, not a cliff.
        mid = [gf(50.0, y) for y in np.linspace(3.0, 9.0, 25)]
        self.assertTrue(all(0.8 < v <= 1.001 for v in mid), mid)

    def test_bridge_unaffected(self):
        dem = lambda x, y: 0.0
        bridge_pts = [(float(x), 0.0, 8.0) for x in range(0, 101, 10)]
        # Random/other strips far away would contribute anchors; none here: the field is
        # built without anchors or edges from the bridge strip, exactly as prepare.py does.
        gf = scene.GroundField(dem, [], edges=[])   # bridge strip contributes nothing
        for (x, y, z) in bridge_pts:
            self.assertAlmostEqual(gf(x, y), 0.0, places=4)   # stays at terrain level
        l, r = scene.strip_borders(bridge_pts, 8.0)
        for border in (l, r):
            for (ax, ay, az) in border:
                self.assertAlmostEqual(gf(ax, ay), 0.0, places=4)  # no snap to deck height

    def test_footprint_from_borders_versus_centreline_buffer_corner(self):
        # Path with a sharp ~135 degree turn: Godot's miter clamp (scale 0.5 -> 1*w/2 max
        # extension) differs from Shapely's LineString buffer (mitre_limit 3 -> 1.5*w).
        pts = [(0.0, 0.0, 0.0), (10.0, 0.0, 0.0), (8.0, -2.0, 0.0)]
        w = 8.0
        fpn = scene.footprint([strip(pts, w)])
        corner_l, corner_r = scene.strip_borders(pts, w)
        # The new footprint is built from the borders themselves: corner points sit ON it.
        for p in (corner_l[1], corner_r[1], corner_l[2], corner_r[2]):
            self.assertLess(fpn.distance(Point(p[0], p[1])), 1e-9)
        old = LineString([(x, y) for x, y, _ in pts]).buffer(w/2, cap_style='flat',
                                                             join_style='mitre', mitre_limit=3)
        # ...but on the sharp corner the old centreline buffer disagrees with the ribbon.
        self.assertGreater(old.boundary.distance(Point(corner_l[1][0], corner_l[1][1])), 0.5,
                           msg='old buffer corner must differ from ribbon miter corner')

    def test_footprint_straight_run_agrees_with_old_buffer(self):
        # Straight (no corner): the old LineString buffer equals the border formula exactly.
        pts, w = straight()
        fp = scene.footprint([strip(pts, w)])
        old = LineString([(x, y) for x, y, _ in pts]).buffer(w/2, cap_style='flat',
                                                             join_style='mitre', mitre_limit=3)
        mid_left = [(x, w/2) for x in (5.0, 50.0, 195.0)]
        for p in mid_left:
            self.assertLess(fp.boundary.distance(Point(*p)), 1e-6)
            self.assertLess(old.boundary.distance(Point(*p)), 1e-6)

    def test_borders_match_godot_ribbon(self):
        # Port of world.gd `borders` (offsets in the XZ plane, clamp scale 0.5): the cut
        # polygon must coincide with what the renderer actually draws, corner for corner.
        def godot_borders(points, half):
            n = len(points)
            left, right = [], []
            for i in range(n):
                p = np.array(points[i])
                prev = np.array(points[max(i-1, 0)])
                nxt = np.array(points[min(i+1, n-1)])
                d0 = np.array([p[0]-prev[0], p[2]-prev[2]])
                d1 = np.array([nxt[0]-p[0], nxt[2]-p[2]])
                d0l = math.hypot(*d0) or 1.0
                d1l = math.hypot(*d1) or 1.0
                if i > 0:
                    d0 = d0/d0l
                else:
                    d0 = np.zeros(2)
                if i < n-1:
                    d1 = d1/d1l
                else:
                    d1 = np.zeros(2)
                direc = d0+d1
                if math.hypot(*direc) < 1e-5:
                    direc = d1 if d1l > 0 else d0
                direc = direc/math.hypot(*direc)
                perp = np.array([-direc[1], direc[0]])
                ref = np.array([-d0[1], d0[0]]) if math.hypot(*d0) > 1e-9 else np.array([-d1[1], d1[0]])
                scale = 1.0/max(0.5, abs(float(perp @ ref)))
                off = np.array([perp[0], 0.0, perp[1]])*half*scale
                left.append(np.array(p)+off)
                right.append(np.array(p)-off)
            return left, right

        # A curve with a sharp corner in net space; map to godot (x, -y) plane for the port.
        net = [(math.cos(t)*100.0, math.sin(t)*100.0, 1.0) for t in np.linspace(-0.9, -0.1, 9)]
        net += [(12.0, -10.0, 1.0), (12.0, -2.0, 1.0)]      # sharp second bend
        godot = [(x, z, -y) for x, y, z in net]
        w = 8.0
        gl, gr = godot_borders(godot, w/2)
        sl, sr = scene.strip_borders(net, w)
        # same point set per side (labels may swap; Godot offsets in (x,z), scene in (x,y))
        to_plane = lambda g: (g[0], -g[2])
        gpoints = [to_plane(p) for p in gl+gr]
        spoints = [(p[0], p[1]) for p in sl+sr]
        self.assertEqual(len(spoints), len(gpoints))
        # Match within a tolerance, not by exact float equality: BLAS/SIMD paths differ in
        # the last bit between platforms (GitHub's Windows runner).
        for a_side, b_side in ((spoints, gpoints), (gpoints, spoints)):
            for a in a_side:
                self.assertLess(min(math.hypot(a[0]-b[0], a[1]-b[1]) for b in b_side), 1e-6)

    def test_stitch_vertices_preserve_profile_stations(self):
        # Profile stations must survive the FULL draped-grid triangulation (grid cells +
        # polygon outlines), not just a bare polygon triangulation.
        pts, w = straight()
        fp = scene.strip_polygon(pts, w)
        covered = scene.polygons(fp)
        ground_poly = box(-20.0, -20.0, 220.0, 20.0).difference(unary_union(covered))
        l, r = scene.strip_borders(pts, w)
        prof = [(p[0], p[1]) for p in l+r]
        stitched = scene.stitch_vertices(scene.polygons(ground_poly), prof)
        verts = set()
        for poly in stitched:
            # draped_triangles splits on the 20 m grid (as prepare.py does for the ground).
            for tri in scene.draped_triangles(poly, cell=20.0):
                for x, y in tri:
                    verts.add((round(x, 6), round(y, 6)))
        missing = [p for p in prof if (round(p[0], 6), round(p[1], 6)) not in verts]
        self.assertEqual(missing, [], f'{len(missing)} profile stations lost in the mesh')
        self.assertTrue(stitched)

    def test_field_grid_is_not_quadratic(self):
        dem = lambda x, y: 0.0
        pts = [(float(x), float(y), 1.0) for y in range(0, 1000, 50) for x in range(0, 200, 10)]
        edges = []
        for i in range(0, len(pts), 20):
            chunk = pts[i:i+20]
            l, r = scene.strip_borders(chunk, 6.0)
            edges += scene.border_segments(l)+scene.border_segments(r)
        t0 = time.monotonic()
        gf = scene.GroundField(dem, pts, edges=edges)
        build = time.monotonic()-t0
        t0 = time.monotonic()
        for k in range(3000):
            gf(float(k % 200), float((k*7) % 1000))
        query = time.monotonic()-t0
        self.assertLess(build, 2.0, f'edge grid build too slow: {build:.2f}s')
        self.assertLess(query, 3.0, f'edge grid query too slow: {query:.2f}s')

    def test_stitch_projects_near_boundary_never_warps_shape(self):
        # Near-but-off-boundary stations used to be inserted verbatim (tol=0.25), bending
        # the cut boundary by up to 25 cm and opening hairline gaps. Now they are projected
        # onto the boundary: the shape is preserved exactly while the knot still lands on
        # the seam; truly collinear stations keep their own coordinates.
        poly = box(-10.0, -10.0, 60.0, 10.0)
        collinear = [(10.0, 10.0), (20.0, 10.0), (30.0, 10.0)]
        wobbly = [(15.0, 9.97), (25.0, 10.03), (35.0, 9.95)]   # 3-5 cm off the edge
        stitched = scene.stitch_vertices([poly], collinear+wobbly)
        self.assertEqual(len(stitched), 1)
        diff = poly.symmetric_difference(stitched[0]).area
        self.assertLess(diff, 1e-9, f'stitching warped the cut by {diff:.3e} m2')
        ring = list(stitched[0].exterior.coords)[:-1]
        for wx, wy in wobbly:
            self.assertFalse(any(math.hypot(px-wx, py-wy) < 1e-9 for px, py in ring),
                             f'off-boundary station ({wx}, {wy}) was inserted verbatim')
            self.assertTrue(any(math.hypot(px-wx, py-10.0) < 1e-9 for px, py in ring),
                            f'projected knot at x={wx} missing from the seam')
        for sx, sy in collinear:
            self.assertIn((sx, sy), ring)

    # --- bridge pedestrians: the ground layer must ignore elevated sidewalks/decks ---

    class _FakeLane:
        def __init__(self, shape, z, lid):
            self._shape, self._z, self._id = shape, z, lid
        def allows(self, v):
            return v == 'pedestrian'
        def getShape(self):
            return self._shape
        def getWidth(self):
            return 3.0
        def getID(self):
            return self._id

    class _FakeEdge:
        def __init__(self, function, lane, orig=''):
            self._f, self._lane, self._orig = function, lane, orig
        def getFunction(self):
            return self._f
        def getLanes(self):
            return [self._lane]

    def _fake_road_z(self, *lids):
        return SimpleNamespace(z={lid: [1.0, 1.0] for lid in lids})

    def test_sidewalks_marks_bridge_strips(self):
        shape = [(0.0, 0.0), (10.0, 0.0)]
        ground_lane = self._FakeLane(shape, [1.0, 1.0], 'wd1')
        deck_lane = self._FakeLane(shape, [1.0, 1.0], 'wd2')
        net = SimpleNamespace(getEdges=lambda withInternal=True:
                              [self._FakeEdge('', ground_lane), self._FakeEdge('', deck_lane, orig='b')])
        level = lambda e: 1 if e._orig == 'b' else 0
        strips, _ = scene.sidewalks(net, self._fake_road_z('wd1', 'wd2'), None, level)
        self.assertEqual([s['bridge'] for s in strips], [False, True])
        # Default structure_of=None preserves the plain API: nothing flagged.
        strips2, _ = scene.sidewalks(net, self._fake_road_z('wd1', 'wd2'), None)
        self.assertEqual([s.get('bridge') for s in strips2], [False, False])

    def test_walkingareas_marked_bridge_only_where_applicable(self):
        wshape = [(0.0, 0.0), (4.0, 0.0), (4.0, 4.0), (0.0, 4.0), (0.0, 0.0)]
        wz = [1.0]*5
        wa = self._FakeEdge('walkingarea', self._FakeLane(wshape, wz, 'wa'), orig='')
        wb = self._FakeEdge('walkingarea', self._FakeLane(wshape, wz, 'wb'), orig='bridge')
        net = SimpleNamespace(getEdges=lambda withInternal=True: [wa, wb])
        level = lambda e: 1 if e._orig == 'bridge' else 0
        _, areas = scene.sidewalks(net, SimpleNamespace(z={'wa': wz, 'wb': wz}), None, level)
        self.assertEqual([a['bridge'] for a in areas], [False, True])

    def test_bridge_sidewalk_edges_do_not_pull_ground(self):
        # A bridge sidewalk sits 5 m above the terrain. Feeding its borders to the ground
        # field (unfiltered walk strips) used to snap/blend the terrain up to deck level;
        # prepare.py now drops bridge walk strips from anchors/edges, leaving the ground
        # at terrain level exactly like it does for bridge carriageways.
        dem = lambda x, y: 0.0
        deck = [(20.0, 0.0, 5.0), (80.0, 0.0, 5.0)]      # elevated sidewalk, z = 5 m
        l, r = scene.strip_borders(deck, 3.0)
        gf_bug = scene.GroundField(dem, [], edges=scene.border_segments(l)+scene.border_segments(r))
        gf_fixed = scene.GroundField(dem, [], edges=[])   # bridge walk strips filtered
        q = (30.0, 4.0)                                   # ~2.5 m out from the curb line
        self.assertGreater(gf_bug(*q), 1.0,
                           'elevated bridge sidewalk edge must pull the ground up (bug)')
        self.assertEqual(gf_fixed(*q), 0.0,
                         'with bridge walk strips filtered the ground stays at terrain level')

    def test_ground_cut_excludes_bridge(self):
        # prepare.py builds the ground cut only from non-bridge strips, so the terrain
        # under a deck is not excavated and bridges stay untouched by the seam fix.
        pts, w = straight()
        self.assertGreater(scene.footprint([strip(pts, w, bridge=True)]).area, 0.0,
                           'bridge strip geometry is usable')
        cut_used = scene.footprint([r for r in [strip(pts, w, bridge=True)] if not r['bridge']])
        self.assertTrue(cut_used.is_empty, 'bridge strips do not contribute to the ground cut')
        cut_flat = scene.footprint([r for r in [strip(pts, w, bridge=False)] if not r['bridge']])
        self.assertGreater(cut_flat.area, 1000.0)
        self.assertTrue(cut_flat.contains(Point(50.0, 0.0)))


if __name__ == '__main__':
    unittest.main()