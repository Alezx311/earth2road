"""Public package contracts with a small, licensed, entirely offline world."""
from contextlib import redirect_stderr, redirect_stdout
import copy
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from akadem_maps.context import BuildContext, atomic_directory, read_json, sha256, write_json
from akadem_maps.world import build_world, validate_config, validate_world
from akadem_maps.adapters.beamng.export import export_world, validate_export

ROOT=Path(__file__).resolve().parents[1]
EXAMPLE=ROOT/'examples/tiny'

class WorldContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory()
        cls.root=Path(cls.temp.name)
        cls.world=cls.root/'world'
        cls.cfg=read_json(EXAMPLE/'config.json')
        with redirect_stdout(io.StringIO()):
            build_world(cls.cfg,cls.world,inputs=EXAMPLE/'inputs',offline=True)
    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_offline_geometry_reproducible(self):
        other=self.root/'rebuild'
        build_world(self.cfg,other,inputs=self.world/'inputs',offline=True)
        self.assertEqual(sha256(self.world/'network.net.xml'),sha256(other/'network.net.xml'))
        self.assertEqual(read_json(self.world/'index.json'),read_json(other/'index.json'))
        self.assertEqual({p.name:sha256(p) for p in (self.world/'tiles').glob('*.json')},
                         {p.name:sha256(p) for p in (other/'tiles').glob('*.json')})

    def test_one_world_both_adapters_and_unique_resources(self):
        from akadem_maps.adapters.godot.export import export_world as godot
        with redirect_stdout(io.StringIO()):
            a=export_world(self.world,self.root/'beam_a',level_id='akadem_test_a')
            b=export_world(self.world,self.root/'beam_b',level_id='akadem_test_b')
            godot(self.world,self.root/'godot',offline=True)
        self.assertTrue(validate_export(self.root/'beam_a')['objects'])
        self.assertFalse((self.root/'game').exists())
        self.assertFalse((self.root/'godot/game/data/active_map').exists())
        self.assertTrue((self.root/'godot/data/build/tiny/demand.json').exists())
        mats=[]
        for name,level in [('beam_a','akadem_test_a'),('beam_b','akadem_test_b')]:
            folder=self.root/name/'mod/levels'/level
            mats.append(set(read_json(folder/'art/kyiv/main.materials.json')))
            self.assertFalse((folder/'kyiv-baseline.json').exists())
        # Only stock-mesh foliage names repeat; the game itself defines them per level.
        from akadem_maps.adapters.beamng.beamng_assets import STOCK_MESH_MATERIALS
        self.assertTrue(mats[0]&mats[1])
        self.assertLessEqual(mats[0]&mats[1],STOCK_MESH_MATERIALS)
        for level,names in zip(('akadem_test_a','akadem_test_b'),mats):
            self.assertFalse({n for n in names-STOCK_MESH_MATERIALS if not n.startswith(level+'_')})
        self.assertFalse(a['runtime_verified'])
        # Synthetic fixture must not be attributed to OSM/Mapzen.
        level=self.root/'beam_a/mod/levels/akadem_test_a'
        self.assertNotIn('OpenStreetMap',(level/'LICENSE-DATA.txt').read_text(encoding='utf8').replace('No OpenStreetMap',''))
        self.assertNotIn('osm',read_json(self.world/'world.json')['licenses'])
        self.assertNotIn('OpenStreetMap',read_json(self.world/'index.json')['attribution'].replace('not OpenStreetMap',''))

    def test_experimental_region_has_no_ukrainian_signs(self):
        from akadem_maps.adapters.beamng import export as beam
        from akadem_maps.adapters.godot import export as godot
        world=self.root/'signed'
        shutil.copytree(self.world,world)
        tile=sorted((world/'tiles').glob('*.json'))[0]
        data=read_json(tile)
        data['signs']=[{'kind':'maxspeed','value':30,'lane':'x','edge':'x','position':[0,2.3,0],
                        'yaw':0,'provenance':'osm','source':'test'}]
        write_json(tile,data)
        self.assertEqual(read_json(world/'config.json')['region_profile'],'experimental')
        with patch.object(godot,'validate_world'),patch.object(beam,'validate_world'),redirect_stdout(io.StringIO()):
            godot.export_world(world,self.root/'signed_godot',offline=True)
            beam.export_world(world,self.root/'signed_beam',level_id='akadem_test_s')
        out=self.root/'signed_godot/game/data/tiny/tiles'/tile.name
        self.assertEqual(read_json(out)['signs'],[])
        self.assertEqual(read_json(self.root/'signed_godot/godot-export.json')['signs_skipped_region'],1)
        level=self.root/'signed_beam/mod/levels/akadem_test_s'
        self.assertFalse([p for p in level.rglob('*') if 'signface' in p.name])
        self.assertFalse([n for n in read_json(level/'art/kyiv/main.materials.json') if 'kyiv_sign_' in n])

    def test_enrichment_resolves_against_build_config_root(self):
        from akadem_maps.core import prepare
        from shapely.geometry import box
        base=self.root/'enrich_root'
        (base/'sources').mkdir(parents=True)
        west,south=30.3525,50.4515  # inside a block, away from the synthetic streets
        building=box(west,south,west+0.0003,south+0.0002)
        write_json(base/'sources/overture.geojson',{'type':'FeatureCollection','features':[
            {'type':'Feature','properties':{'id':'tiny-b1','height':12.0},
             'geometry':{'type':'Polygon','coordinates':[list(map(list,building.exterior.coords))]}}]})
        sources=read_json(ROOT/'akadem_maps/resources/building_sources.json')
        write_json(base/'building_sources.json',sources)
        cfg=copy.deepcopy(self.cfg)
        cfg['building_enrichment']={'enabled':True,'strict':True,'sources_config':'building_sources.json',
                                    'cache_dir':'cache','sources':{'overture':{'local_geojson':'sources/overture.geojson'}}}
        raw=self.root/'enrich_raw'
        shutil.copytree(EXAMPLE/'inputs/raw',raw)
        def no_network(*args,**kwargs):
            raise AssertionError('network used')
        with patch.object(prepare,'download',no_network),redirect_stdout(io.StringIO()):
            build_world(cfg,self.root/'enriched',config_root=base,cache=raw)
        audit=read_json(self.root/'enriched/audit.json')['building_enrichment']
        self.assertEqual(audit['candidates']['status'],'ok')
        self.assertEqual(audit['accepted'],1)
        self.assertTrue(audit['cache_files'])
        for name,digest in audit['cache_files'].items():
            self.assertFalse(Path(name).is_absolute())
            self.assertEqual(sha256(base/'cache'/name),digest)
        self.assertTrue((self.root/'enriched/inputs/config_root/building_sources.json').exists())

    def test_real_kyiv_level_ids_namespace_cleanly(self):
        own=[]
        for level_id in ('kyiv_akadem','kyiv_ring_teremky_berkovets'):
            out=self.root/('real_'+level_id)
            with redirect_stdout(io.StringIO()):
                export_world(self.world,out,level_id=level_id)
            validate_export(out)  # ZIP: scoped materials, resolvable DAE symbols
            level=out/'mod/levels'/level_id
            names=set(read_json(level/'art/kyiv/main.materials.json'))
            self.assertIn(level_id+'_substrate',read_json(level/'art/terrains/main.materials.json'))
            self.assertFalse([n for n in names if n.startswith('kyiv_') and not n.startswith(level_id+'_')])
            own.append({n for n in names if n.startswith(level_id+'_')})
        self.assertTrue(own[0] and own[1])

    def test_godot_install_is_explicit_and_backs_up(self):
        from akadem_maps.adapters.godot.export import export_world as godot
        from akadem_maps.adapters.godot.install import install_export
        export=self.root/'install_export'
        with redirect_stdout(io.StringIO()):
            godot(self.world,export,offline=True)
        game=self.root/'checkout'
        (game/'game/data').mkdir(parents=True)
        (game/'game/project.godot').write_text('')
        (game/'game/data/active_map').write_text('other')
        first=install_export(export,game)
        self.assertTrue((game/'game/data/tiny/index.json').exists())
        self.assertTrue((game/'data/build/tiny/network.net.xml').exists())
        self.assertIsNone(first['replaced_backup'])
        marker=game/'game/data/tiny/local-edit.txt'
        marker.write_text('keep')
        with self.assertRaises(FileExistsError):
            install_export(export,game)
        self.assertTrue(marker.exists())
        second=install_export(export,game,replace=True)
        self.assertFalse(marker.exists())
        self.assertTrue((Path(second['replaced_backup'])/'game/data/tiny/local-edit.txt').exists())
        self.assertEqual((game/'game/data/active_map').read_text(),'other')
        install_export(export,game,replace=True,activate=True)
        self.assertEqual((game/'game/data/active_map').read_text().strip(),'tiny')
        self.assertFalse(list((game/'game/data').glob('.tiny.install-*')))

    def test_build_progress_events_are_monotonic(self):
        seen=[]
        build_world(self.cfg,self.root/'progress',inputs=self.world/'inputs',offline=True,
                    emit=lambda event,**data: seen.append((event,data)))
        progress=[d['progress'] for e,d in seen if e=='stage']
        self.assertGreaterEqual(len(progress),10)
        self.assertEqual(progress,sorted(progress))
        self.assertEqual(seen[-1][0],'result')

    def test_abandoned_stage_of_dead_process_removed(self):
        dead=subprocess.Popen([sys.executable,'-c','pass']); dead.wait()
        parent=self.root/'abandoned'; parent.mkdir()
        stale=parent/'.out.stage-dead'; stale.mkdir()
        stale.with_name(stale.name+'.pid').write_text(str(dead.pid))
        live=parent/'.out.stage-live'; live.mkdir()
        live.with_name(live.name+'.pid').write_text(str(os.getpid()))
        with atomic_directory(parent/'out') as stage:
            (stage/'x').write_text('x')
        self.assertFalse(stale.exists())
        self.assertTrue(live.exists())
        self.assertEqual(sorted(p.name for p in parent.iterdir()),['.out.stage-live','.out.stage-live.pid','out'])

    def test_manual_edits_capture_and_reapply(self):
        first=self.root/'edit_first'
        with redirect_stdout(io.StringIO()):
            export_world(self.world,first,level_id='akadem_test_e')
        # Simulate a World Editor save in a separate copy of the installed level.
        saved=self.root/'edit_saved'
        shutil.copytree(first/'mod/levels/akadem_test_e',saved)
        items=sorted(saved.rglob('items.level.json'),key=lambda p:-p.stat().st_size)[0]
        rows=[json.loads(s) for s in items.read_text(encoding='utf8').splitlines() if s.strip()]
        moved=next(r for r in rows if 'position' in r and r.get('name'))
        moved['position']=[moved['position'][0]+1.5,*moved['position'][1:]]
        items.write_text(''.join(json.dumps(r)+'\n' for r in rows),encoding='utf8')
        edits=self.root/'edits.json'
        process=subprocess.run([sys.executable,'-m','akadem_maps','capture','--target','beamng','--level',str(saved),
                                '--export',str(first),'--output',str(edits),'--events','-'],capture_output=True,text=True,cwd=ROOT)
        self.assertEqual(process.returncode,0,process.stderr)
        self.assertEqual(json.loads(process.stdout.splitlines()[-1])['changed_objects'],1)
        second=self.root/'edit_second'
        with redirect_stdout(io.StringIO()):
            export_world(self.world,second,level_id='akadem_test_e',overrides=edits)
        found=[json.loads(s) for f in (second/'mod/levels/akadem_test_e').rglob('items.level.json')
               for s in f.read_text(encoding='utf8').splitlines() if s.strip()]
        self.assertEqual(next(r for r in found if r.get('name')==moved['name'])['position'],moved['position'])
        # A baseline that no longer matches the edit stops the export instead of guessing.
        document=read_json(edits)
        document['objects'][moved['name']]['base']['position'][0]+=10
        write_json(edits,document)
        with self.assertRaisesRegex(ValueError,'conflicts'),redirect_stdout(io.StringIO()):
            export_world(self.world,self.root/'edit_conflict',level_id='akadem_test_e',overrides=edits)
        self.assertFalse((self.root/'edit_conflict').exists())

    def test_unscoped_material_rejected(self):
        from akadem_maps.adapters.beamng import export as beam
        level=self.root/'scope/akadem_test_c'
        level.mkdir(parents=True)
        write_json(level/'main.materials.json',{'akadem_test_c__kyiv_ok':{},'Birch_Bark_01':{}})
        with patch.object(beam,'validate_level_files',return_value={}):
            beam.validate_level(level)
            write_json(level/'main.materials.json',{'kyiv_road':{}})
            with self.assertRaisesRegex(ValueError,'kyiv_road'):
                beam.validate_level(level)
            write_json(level/'main.materials.json',{'akadem_test_c__kyiv_ok':{}})
            (level/'shape.dae').write_text('<material id="akadem_test_c__kyiv_gone" name="x"/>',encoding='utf8')
            with self.assertRaisesRegex(ValueError,'kyiv_gone'):
                beam.validate_level(level)

    def test_world_hash_tamper_rejected(self):
        corrupt=self.root/'corrupt'
        shutil.copytree(self.world,corrupt)
        (corrupt/'network.net.xml').write_text('<net/>')
        with self.assertRaisesRegex(ValueError,'SHA-256'):
            validate_world(corrupt)

    def test_input_hash_tamper_rejected_before_output(self):
        source=self.root/'bad_inputs'
        shutil.copytree(EXAMPLE/'inputs',source)
        (source/'raw/tiny.osm').write_text('<osm/>')
        output=self.root/'bad_output'
        with self.assertRaisesRegex(ValueError,'SHA-256'):
            build_world(self.cfg,output,inputs=source,offline=True)
        self.assertFalse(output.exists())

    def test_duplicate_output_is_preserved(self):
        before=sha256(self.world/'index.json')
        with self.assertRaises(FileExistsError):
            build_world(self.cfg,self.world,inputs=EXAMPLE/'inputs',offline=True)
        self.assertEqual(before,sha256(self.world/'index.json'))

    def test_failure_and_cancellation_leave_no_published_output(self):
        for exception in (ValueError('failed'),KeyboardInterrupt()):
            out=self.root/'interrupted'
            with self.assertRaises(type(exception)):
                with atomic_directory(out) as stage:
                    (stage/'partial').write_text('partial')
                    raise exception
            self.assertFalse(out.exists())
            self.assertFalse(list(self.root.glob('.interrupted.stage-*')))

    def test_invalid_rectangles(self):
        for bbox in ([20,40,10,50],[0,50,1,40],[170,40,-170,41],[0,86,1,87],[0,0,float('nan'),1]):
            with self.subTest(bbox=bbox),self.assertRaises(ValueError):
                validate_config({'id':'test','name':'test','bbox':bbox})

    def test_empty_incomplete_download_and_offline_inputs(self):
        from akadem_maps.core.prepare import fetch
        raw=self.root/'raw-errors';raw.mkdir()
        cfg=validate_config({**self.cfg,'id':'empty'})
        ctx=BuildContext(self.root/'fetch',raw,self.root,True)
        with self.assertRaisesRegex(FileNotFoundError,'Offline input'):
            fetch(cfg,ctx)
        for text,message in [('<osm version="0.6"/>','no suitable'),('<osm><remark>timeout</remark></osm>','incomplete')]:
            (raw/'empty.osm').write_text(text)
            with self.assertRaisesRegex((ValueError,RuntimeError),message):
                fetch(cfg,ctx)
        ctx.offline=False
        with patch('akadem_maps.core.prepare.download',side_effect=OSError('connection lost')):
            with self.assertRaisesRegex(RuntimeError,'Download failed'):
                ctx.download('https://example.invalid',raw/'missing')

    def test_cli_jsonl_error_is_machine_readable(self):
        process=subprocess.run([sys.executable,'-m','akadem_maps','build','--bbox','10','0','-10','1','--id','bad','--name','bad','--output',str(self.root/'bad-cli'),'--events','-'],capture_output=True,text=True,cwd=ROOT)
        self.assertEqual(process.returncode,1)
        events=[json.loads(line) for line in process.stdout.splitlines()]
        self.assertEqual(events[-1]['event'],'error')
        self.assertIn('bbox',events[-1]['message'])

if __name__=='__main__':
    unittest.main()
