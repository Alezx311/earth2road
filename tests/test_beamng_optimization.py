import math
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

from akadem_maps.adapters.beamng.beamng_geometry import Mesh
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
