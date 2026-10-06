"""Presentation partition must preserve the source mesh, including shading/UVs."""
from collections import Counter
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

from akadem_maps.adapters.beamng.beamng_geometry import Mesh
from tools.beamng_assembly import partition_dae, Q


def corners(data):
    root = ET.fromstring(data)
    output = Counter()
    for geo in root.find(Q('library_geometries')):
        mesh = geo.find(Q('mesh'))
        sources = {}
        for s in mesh.findall(Q('source')):
            stride = int(s.find(Q('technique_common')).find(Q('accessor')).get('stride'))
            values = s.find(Q('float_array')).text.split()
            sources[s.get('id')] = [tuple(values[i:i+stride]) for i in range(0, len(values), stride)]
        pos = mesh.find(Q('vertices')).find(Q('input')).get('source')[1:]
        tri = mesh.find(Q('triangles'))
        attrs = [pos] + [i.get('source')[1:] for i in tri.findall(Q('input')) if i.get('semantic') != 'VERTEX']
        ids = list(map(int, tri.find(Q('p')).text.split()))
        for i in range(0, len(ids), 3):
            output[(tri.get('material'), tuple(tuple(sources[a][v] for a in attrs) for v in ids[i:i+3]))] += 1
    return output


class AssemblyPartition(unittest.TestCase):
    def test_exact_partition_with_uvs_normals_materials_and_duplicates(self):
        mesh = Mesh()
        for material, z in [('kyiv_asphalt', 0), ('kyiv_paint', .025)]:
            for x in (0, 8, 16, 16):
                mesh.tri(material, (x, 0, z), (x+8, 0, z+1), (x, 4, z), uv=((.1,.2),(.3,.4),(.5,.6)))
        with tempfile.TemporaryDirectory() as tmp:
            for mode in ('balanced', 'compact'):
                path = Path(tmp)/'source.dae'
                mesh.write(path, optimization=mode)
                original = path.read_bytes()
                parts, count = partition_dae(path, lambda mat, center: (mat, int(center[0]//8)))
                expanded = Counter()
                for data in parts.values():
                    expanded.update(corners(data))
                self.assertEqual(expanded, corners(original))
                self.assertEqual(count, 8)
                self.assertEqual(path.read_bytes(), original)
                self.assertGreater(len(parts), 1)

    def test_rejects_non_shared_indices(self):
        mesh = Mesh()
        mesh.tri('road', (0,0,0), (1,0,0), (0,1,0))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'source.dae'
            mesh.write(path)
            path.write_text(path.read_text().replace('semantic="NORMAL" source="#g0-normal" offset="0"', 'semantic="NORMAL" source="#g0-normal" offset="1"'))
            with self.assertRaisesRegex(ValueError, 'shared'):
                partition_dae(path, lambda *_: 'all')


if __name__ == '__main__':
    unittest.main()
