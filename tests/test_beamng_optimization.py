import math
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

from akadem_maps.adapters.beamng.beamng_geometry import Mesh, features, optimization_mode
from akadem_maps.adapters.beamng.beamng_terrain import GroundTerrain, terrain_grid
from akadem_maps.adapters.beamng.optimization import simplify_ground
from akadem_maps.adapters.beamng.beamng_curbs import arc_segments, build_sidewalks
from tests.test_beamng_curbs import street


def expanded(path):
    root = ET.parse(path).getroot()
    ns = {'c': root.tag.split('}')[0][1:]}
    result = []
    for geometry in root.findall('.//c:geometry', ns):
        arrays = [[float(x) for x in s.text.split()] for s in geometry.findall('.//c:float_array', ns)]
        ids = [int(x) for x in geometry.find('.//c:p', ns).text.split()]
        result.append([tuple(tuple(a[i*stride:(i+1)*stride]) for a,stride in zip(arrays,(3,3,2))) for i in ids])
    return result


class OptimizedGeometry(unittest.TestCase):
    def test_indexing_preserves_all_corner_attributes_and_sharp_edges(self):
        mesh = Mesh()
        mesh.box((0,0,0), (2,2,2), 'stone')
        mesh.tri('stone',(1,1,1),(-1,1,1),(-1,-1,1),uv=((.2,.3),(.4,.5),(.6,.7)))
        with tempfile.TemporaryDirectory() as tmp:
            old,new = Path(tmp)/'old.dae',Path(tmp)/'new.dae'
            mesh.write(old, optimization='legacy')
            stats = mesh.write(new)
            self.assertEqual(expanded(old), expanded(new))
            self.assertLess(stats['vertices'], mesh.count*3)
            self.assertLess(new.stat().st_size, old.stat().st_size)
            first = new.read_bytes()
            mesh.write(new)
            self.assertEqual(first,new.read_bytes())

    def test_compact_shares_smooth_vertices_and_keeps_creases(self):
        mesh = Mesh()
        # Gently folded 4×4 grid (≈3° between neighbours), a sharp box and slivers.
        for i in range(4):
            for j in range(4):
                z = lambda x, y: .05*((x+y) % 2)
                a, b, c, d = (i,j), (i+1,j), (i+1,j+1), (i,j+1)
                mesh.tri('grid', *[(x, y, z(x, y)) for x, y in (a, b, c)])
                mesh.tri('grid', *[(x, y, z(x, y)) for x, y in (a, c, d)])
        mesh.box((10, 10, 1), (2, 2, 2), 'stone')
        mesh.tri('stone', (0, 0, 0), (.0004, 0, 0), (0, 1, 0))    # collapses at 1 mm
        with tempfile.TemporaryDirectory() as tmp:
            old, new = Path(tmp)/'old.dae', Path(tmp)/'new.dae'
            base = mesh.write(old)
            stats = mesh.write(new, optimization='compact')
            self.assertEqual(stats['triangles'], mesh.count-1)
            self.assertEqual(stats['vertices'], 25+24)    # grid: one per position; box: 4 per face
            self.assertLess(stats['bytes'], base['bytes'])
            grid_old, stone_old = expanded(old)
            grid_new, stone_new = expanded(new)
            self.assertEqual([tuple(round(c, 3) for c in v[0]) for v in grid_old],
                             [v[0] for v in grid_new])
            for v in stone_new:    # box normals stay axis-aligned
                self.assertEqual(sorted(abs(c) for c in v[1]), [0, 0, 1])
            first = new.read_bytes()
            mesh.write(new, optimization='compact')
            self.assertEqual(first, new.read_bytes())

    def test_compact_collision_is_keyed_by_position(self):
        visual, collider = Mesh(), Mesh()
        visual.box((0, 0, 0), (2, 2, 2), 'stone')
        collider.box((0, 0, 0), (2, 2, 2), 'stone')
        with tempfile.TemporaryDirectory() as tmp:
            stats = visual.write(Path(tmp)/'c.dae', optimization='compact', collision=collider)
            self.assertEqual(stats['collision_triangles'], 12)
            self.assertEqual(stats['vertices'], 24+8)

    def test_compact_kerb_is_its_own_collider_and_lighter(self):
        balanced, _ = build_sidewalks([('a', street())], collision=Mesh())
        compact, audit = build_sidewalks([('a', street())], optimization='compact')
        self.assertGreater(compact.count, 0)
        self.assertLess(compact.count, balanced.count)
        self.assertEqual(audit['collision_triangles'], compact.count)
        self.assertEqual(audit['unresolved'], [])
        top = max(v[2] for fs in compact.faces.values() for t in fs for v in t)
        self.assertLessEqual(top, .04)
        again, _ = build_sidewalks([('a', street())], optimization='compact')
        self.assertEqual(dict(again.faces), dict(compact.faces))

    def test_optimization_modes_compose(self):
        self.assertEqual(optimization_mode('writer'), 'balanced+writer')
        self.assertEqual(optimization_mode('terrain+kerbs'), 'balanced+kerbs+terrain')
        self.assertEqual(optimization_mode('writer+kerbs+terrain'), 'compact')
        self.assertEqual(features('compact'), frozenset(('writer', 'kerbs', 'terrain')))
        self.assertEqual(features('balanced'), frozenset())
        with self.assertRaises(ValueError):
            optimization_mode('legacy+writer')
        with self.assertRaises(ValueError):
            optimization_mode('fast')

    def test_terrain_grid_sizes(self):
        self.assertEqual(terrain_grid([0, 0, 1300, 900]), (1.0, 2048))
        self.assertEqual(terrain_grid([0, 0, 8300, 8300]), (2.25, 4096))

    def test_ground_terrain_follows_ground_and_stays_under_caps(self):
        terrain = GroundTerrain([0, 0, 100, 100])
        # Ground: a 1:10 slope over the square; road: a strip x 40..60 at ground height.
        g = lambda x, y: x/10
        for x0, x1 in ((0, 40), (60, 100)):
            terrain.add_ground([((x0, 0, g(x0, 0)), (x1, 0, g(x1, 0)), (x1, 100, g(x1, 100))),
                                ((x0, 0, g(x0, 0)), (x1, 100, g(x1, 100)), (x0, 100, g(x0, 100)))])
        terrain.add_cap([((40, 0, 4), (60, 0, 6), (60, 100, 6)), ((40, 0, 4), (60, 100, 6), (40, 100, 4))])
        h = terrain.heights()
        self.assertAlmostEqual(float(h[50, 20]), 2.0, places=4)       # plain ground
        self.assertAlmostEqual(float(h[50, 80]), 8.0, places=4)
        for i in range(39, 62):                                         # road ± one cell
            road = min(max(i, 40), 60)/10
            self.assertLessEqual(float(h[50, i]), road-.05+1e-5)
        with tempfile.TemporaryDirectory() as tmp:
            obj, stats = terrain.write(Path(tmp), 'kyiv_test')
            payload = (Path(tmp)/'ground.ter').read_bytes()
            self.assertEqual(payload[0], 9)
            self.assertEqual(len(payload), 5+stats['size']**2*3+4+1+len('kyiv_test_ground'))
            self.assertEqual(obj['position'][:2], [0.0, 0.0])
            stored = int.from_bytes(payload[5+2*(50*stats['size']+20):5+2*(50*stats['size']+20)+2], 'little')
            self.assertAlmostEqual(obj['position'][2]+stored*obj['maxHeight']/65536, 2.0, delta=.01)

    def test_terrain_clamps_height_spikes(self):
        terrain = GroundTerrain([0, 0, 200, 200])
        terrain.add_ground([((0, 0, 1), (200, 0, 1), (200, 200, 3)), ((0, 0, 1), (200, 200, 3), (0, 200, 3))])
        terrain.add_ground([((50, 50, 900), (51, 50, 900), (50, 51, 900))])    # source spike
        with tempfile.TemporaryDirectory() as tmp:
            obj, stats = terrain.write(Path(tmp), 'kyiv_test')
        self.assertGreater(stats['clamped_cells'], 0)
        self.assertLessEqual(obj['maxHeight'], 16)
        self.assertLess(stats['step_mm'], .5)

    def test_ground_reduction_keeps_boundary_and_respects_height_bound(self):
        ring = [(math.cos(i*math.tau/6),math.sin(i*math.tau/6),0) for i in range(6)]
        for height, reduced in ((.02,True),(.5,False)):
            old = [((0,0,height),ring[i],ring[(i+1)%6]) for i in range(6)]
            new, audit = simplify_ground(old)
            self.assertEqual(len(new)<len(old),reduced)
            self.assertTrue(set(ring) <= {p for t in new for p in t})
            self.assertLessEqual(audit['max_error_bound_m'],.05)
            self.assertEqual(simplify_ground(old),(new,audit))

    def test_ground_preserves_open_fan_and_separate_decks(self):
        fan = [((0,0,0),(1,0,0),(0,1,0)),((0,0,0),(0,1,0),(-1,0,0))]
        self.assertEqual(simplify_ground(fan)[0],fan)
        decks = fan+[tuple((x,y,z+7) for x,y,z in t) for t in fan]
        self.assertEqual(simplify_ground(decks)[0],decks)

    def test_arc_error_bound_and_collision_omits_bevel(self):
        for radius in (.008,.15):
            n = arc_segments(radius)
            self.assertLessEqual(radius*(1-math.cos(math.pi/(4*n))),.002)
        collider = Mesh()
        visual,audit = build_sidewalks([('a',street())], collision=collider)
        self.assertGreater(collider.count,0)
        self.assertLess(collider.count,visual.count)
        self.assertEqual(audit['collision_triangles'],collider.count)
        self.assertLessEqual(max(v[2] for fs in collider.faces.values() for t in fs for v in t),.04)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'walk.dae'
            visual.write(path,collision=collider)
            root=ET.parse(path).getroot()
            ns={'c':root.tag.split('}')[0][1:]}
            names=[n.get('name','') for n in root.findall('.//c:node',ns)]
            self.assertTrue(any(n.startswith('Colmesh') and n.endswith('-1') for n in names))
