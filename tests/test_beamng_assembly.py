"""Presentation partition must preserve the source mesh, including shading/UVs."""
from collections import Counter
from pathlib import Path
import tempfile
import unittest
import hashlib
import json
from types import SimpleNamespace
import xml.etree.ElementTree as ET

from akadem_maps.adapters.beamng.beamng_geometry import Mesh
from tools.beamng_assembly import partition_dae, Q, validate_scene, camera_pose, prepare
from tools.director_edit import crop_pixels
from tools.director_camera import gps_to_beamng


class DirectorCamera(unittest.TestCase):
    def test_gps_conversion_uses_both_offsets_and_vertical_datum(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);world=root/'world';export=root/'export'
            world.mkdir();(export/'reports').mkdir(parents=True)
            (world/'index.json').write_text(json.dumps({'id':'test','base_height':50,'offset':[10,20]}))
            (world/'network.net.xml').write_text('<net><location netOffset="-499000,200" projParameter="+proj=utm +zone=17 +datum=WGS84 +units=m +no_defs"/></net>')
            (export/'artifact.json').write_text(json.dumps({'map':'test'}))
            (export/'reports/kyiv-manifest.json').write_text(json.dumps({'base_height':50,'sumo_center_offset':[10,20],'vertical_offset':7}))
            point=gps_to_beamng(world,export,-81,0,401)
            for actual,expected in zip(point,[990,180,358]): self.assertAlmostEqual(actual,expected,places=5)
            (export/'artifact.json').write_text(json.dumps({'map':'other'}))
            with self.assertRaisesRegex(ValueError,'do not match'): gps_to_beamng(world,export,-81,0,401)

    def test_city_prepare_preserves_source_and_uses_original_mesh_without_v2_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);world=root/'world';export=root/'export'
            world.mkdir();(export/'reports').mkdir(parents=True)
            idx={'id':'fixture','offset':[10,20],'base_height':50}
            (world/'index.json').write_text(json.dumps(idx))
            (export/'reports/kyiv-manifest.json').write_text(json.dumps({'sumo_center_offset':[10,20],'base_height':50}))
            (export/'fixture.zip').write_bytes(b'export hash fixture')
            (export/'artifact.json').write_text(json.dumps({'map':'fixture','level_id':'fixture','zip':'fixture.zip',
                'sha256':hashlib.sha256(b'export hash fixture').hexdigest()}))
            level=export/'mod/levels/fixture';(level/'main').mkdir(parents=True)
            mesh=level/'original.dae';mesh.write_bytes(b'unchanged mesh fixture')
            obj={'name':'fixture__kyiv_buildings_1','class':'TSStatic','position':[20,30,0],
                 'shapeName':'/levels/fixture/original.dae'}
            items=level/'main/items.level.json';items.write_text(json.dumps(obj)+'\n')
            scene=root/'scene.json';scene.write_text(json.dumps({'kind':'city','center':[0,0,0],'radius':500,'resolution':[1080,1920],'supersampling':2}))
            before={p.relative_to(export):p.read_bytes() for p in export.rglob('*') if p.is_file()}
            dest=root/'take'
            prepare(SimpleNamespace(output=dest,export=export,world=world,scene=scene,static=False))
            self.assertEqual(before,{p.relative_to(export):p.read_bytes() for p in export.rglob('*') if p.is_file()})
            self.assertEqual((dest/'user/current/mods/unpacked/earth2road_assembly/levels/fixture/original.dae').read_bytes(),mesh.read_bytes())
            cfg=json.loads((dest/'user/current/earth2road-assembly.json').read_text())
            self.assertEqual(cfg['parts'],[{'name':obj['name'],'stage':'buildings','position':[20,30,0],'center':[20,30]}])
            settings=json.loads((dest/'user/current/settings/settings.json').read_text())
            self.assertEqual(settings['GraphicDisplayResolutions'],'624 960')
            self.assertEqual((cfg['capture_size'],cfg['engine_supersampling']),([1248,1920],4))

    def test_city_ground_stays_in_place(self):
        # Detroit 07.10.2026: ground hidden as a prop exposed the bare terrain and river plane.
        from tools.beamng_assembly import city_stage
        self.assertIsNone(city_stage('detroit__kyiv_ground_3_4'))
        self.assertEqual([city_stage('m__kyiv_'+k+'_1') for k in ('surface','walk','paint','buildings','lamp')],
                         ['roads','walks','marks','buildings','props'])

    def test_holds_then_reveals_and_clamps_after_last_key(self):
        a={'time':0,'pos':[10,20,30],'look':[0,0,0],'fov':45}
        b={**a,'time':16}
        c={'time':23,'pos':[100,200,300],'look':[0,30,0],'fov':60}
        keys=[a,b,c]
        self.assertEqual(camera_pose(keys,8)['pos'],a['pos'])
        self.assertEqual(camera_pose(keys,19.5)['pos'],[55,110,165])
        self.assertEqual(camera_pose(keys,19.5)['fov'],52.5)
        self.assertEqual(camera_pose(keys,25)['pos'],c['pos'])

    def test_scene_rejects_ambiguous_or_invalid_camera(self):
        base={'kind':'city','center':[0,0,0],'radius':2000,'resolution':[1080,1920]}
        key={'time':0,'pos':[0,0,100],'look':[0,0,0],'fov':50}
        validate_scene({**base,'camera_path':[key]})
        for keys in ([],[dict(key,time=1)],[key,key],[dict(key,fov=float('nan'))],[dict(key,look=key['pos'])]):
            with self.subTest(keys=keys),self.assertRaises(ValueError):
                validate_scene({**base,'camera_path':keys})
        validate_scene({'kind':'junction','center':[0,0,0],'radius':80})

    def test_portrait_capture_is_wider_then_cropped_without_scaling(self):
        from tools.beamng_assembly import capture_geometry
        from tools.director_edit import capture_crop
        self.assertEqual(capture_geometry({'resolution':[1080,1920],'supersampling':2}),([1248,1920],[624,960]))
        self.assertEqual(capture_geometry({'resolution':[1920,1080]}),([1920,1080],[1920,1080]))
        self.assertEqual(capture_crop((1248,1920),[1080,1920]),84)
        for size in ((1248,1918),(1000,1920),(1081,1920)):
            with self.subTest(size=size),self.assertRaises(ValueError):
                capture_crop(size,[1080,1920])

    def test_supersampling_must_divide_into_even_window(self):
        base={'kind':'city','center':[0,0,0],'radius':2000,'resolution':[1080,1920]}
        validate_scene({**base,'supersampling':2})
        for ss in (0,5,1.5,'2'):
            with self.subTest(ss=ss),self.assertRaises(ValueError):
                validate_scene({**base,'supersampling':ss})
        with self.assertRaises(ValueError):
            validate_scene({**base,'resolution':[1080,1924],'supersampling':4})

    def test_reference_crop_cannot_distort_or_leave_image(self):
        self.assertEqual(crop_pixels((6000,4000),[.4,0,.375,1],[1080,1920]),(2400,0,2250,4000))
        for crop in ([0,0,1,1],[.8,0,.375,1],[0,0,float('nan'),1]):
            with self.subTest(crop=crop),self.assertRaises(ValueError):
                crop_pixels((6000,4000),crop,[1080,1920])


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
