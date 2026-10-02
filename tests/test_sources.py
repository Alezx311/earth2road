"""Source contracts: cache coverage, corrupt HTTP/PBF, cancellation and offline DEM."""
import copy
from contextlib import redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from PIL import Image
from shapely.geometry import box, mapping

from akadem_maps.context import BuildContext, read_json, sha256
from akadem_maps import sources, packages, offline, runtime
from akadem_maps.core import prepare, osm_extract
from akadem_maps.errors import SourceError, NetworkError, OfflineMissing, ToolError
from akadem_maps.world import validate_config, build_world

OSM = '''<osm version="0.6"><node id="1" version="1" lon="30.005" lat="50.005"/>
<node id="2" version="1" lon="30.015" lat="50.015"/>
<way id="1" version="1"><nd ref="1"/><nd ref="2"/><tag k="highway" v="residential"/></way></osm>'''


class SourceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.raw = Path(self.tmp.name)/'raw'
        self.raw.mkdir()
        self.cfg = validate_config({'id': 'one', 'name': 'Area', 'bbox': [30, 50, 30.02, 50.02],
                                    'overpass': 'https://a.example', 'overpass_mirrors': ['https://b.example']})
        self.ctx = BuildContext(Path(self.tmp.name)/'world', self.raw, Path(self.tmp.name))
        self.geometry = mapping(box(*self.cfg['bbox']))

    def source(self, text=OSM):
        path = Path(self.tmp.name)/'input.osm'
        path.write_text(text, encoding='utf8')
        return path

    def publish(self, text=OSM):
        return sources.publish(self.raw, self.source(text), self.geometry, 'fixture')

    def test_new_id_reuses_verified_snapshot_without_network(self):
        path, _ = self.publish()
        other = {**self.cfg, 'id': 'two'}
        with patch.object(self.ctx, 'download', side_effect=AssertionError('network')):
            actual, _ = sources.acquire(other, self.ctx, self.geometry)
        self.assertEqual(actual, path)

    def test_contained_area_is_cut_and_has_complete_ways(self):
        self.publish()
        cfg = {**self.cfg, 'id': 'two', 'bbox': [30.004, 50.004, 30.01, 50.01]}
        with patch.object(self.ctx, 'download', side_effect=AssertionError('network')), redirect_stdout(io.StringIO()):
            path, meta = sources.acquire(cfg, self.ctx, sources.coverage(cfg))
        self.assertEqual(len(sources.validate_osm(path).findall('node')), 2)
        self.assertEqual(json.loads(json.dumps(meta['coverage'])), json.loads(json.dumps(sources.coverage(cfg))))
        self.assertEqual(len(sources.snapshots(self.raw)), 2)

    def test_partial_coverage_is_not_reused(self):
        self.publish()
        cfg = {**self.cfg, 'bbox': [30, 50, 30.03, 50.03]}
        self.ctx.offline = True
        with self.assertRaises(OfflineMissing):
            sources.acquire(cfg, self.ctx, sources.coverage(cfg))

    def test_legacy_file_does_not_grant_coverage_to_another_id(self):
        (self.raw/'one.osm').write_text(OSM, encoding='utf8')
        self.ctx.offline = True
        path, _ = sources.acquire(self.cfg, self.ctx, self.geometry)
        self.assertEqual(path.name, 'one.osm')
        with self.assertRaises(OfflineMissing):
            sources.acquire({**self.cfg, 'id': 'two'}, self.ctx, self.geometry)

    def test_corrupt_or_old_selection_cache_is_not_accepted(self):
        path, _ = self.publish()
        path.write_text('broken', encoding='utf8')
        self.assertEqual(sources.snapshots(self.raw), [])
        path.write_text(OSM, encoding='utf8')
        meta = read_json(path.parent/'snapshot.json')
        meta['selection'] = 'obsolete'
        packages.atomic_json(path.parent/'snapshot.json', meta)
        self.assertEqual(sources.snapshots(self.raw), [])

    def test_bad_http_200_tries_next_mirror_before_publication(self):
        for bad in ('<osm><remark>runtime timeout</remark></osm>', '<osm>',
                    OSM.replace('ref="2"', 'ref="999"')):
            with self.subTest(bad=bad):
                calls = []
                def download(url, path, *args, **kwargs):
                    calls.append(url)
                    path.write_text(bad if len(calls) == 1 else OSM, encoding='utf8')
                with patch.object(self.ctx, 'download', side_effect=download):
                    path, _ = sources.acquire({**self.cfg, 'refresh': True}, self.ctx, self.geometry)
                self.assertEqual(calls, ['https://a.example', 'https://b.example'])
                self.assertEqual(path.read_text(encoding='utf8'), OSM)

    def test_failed_or_cancelled_refresh_preserves_good_snapshot(self):
        path, _ = self.publish()
        for error in (NetworkError('HTTP 504'), KeyboardInterrupt()):
            with self.subTest(error=type(error).__name__), patch.object(self.ctx, 'download', side_effect=error):
                with self.assertRaises((NetworkError, KeyboardInterrupt)):
                    sources.acquire({**self.cfg, 'refresh': True}, self.ctx, self.geometry)
            self.assertEqual(path.read_text(encoding='utf8'), OSM)
            self.assertFalse(list(self.raw.glob('download-*')))
            self.assertEqual(len(sources.snapshots(self.raw)), 1)

    def test_retry_after_for_same_host_and_budget(self):
        cfg = {**self.cfg, 'overpass': 'https://host/a', 'overpass_mirrors': ['https://host/b', 'https://other/c']}
        clocks = [0]
        def download(url, path, *args, **kwargs):
            self.assertLessEqual(kwargs['max_time'], 180-clocks[0])
            if url.endswith('/a'):
                raise NetworkError('HTTP 429', retry_after=30)
            path.write_text(OSM, encoding='utf8')
        def sleep(seconds): clocks[0] += seconds
        with patch.object(self.ctx, 'download', side_effect=download), patch('akadem_maps.sources.time.monotonic', side_effect=lambda: clocks[0]), patch('akadem_maps.sources.time.sleep', side_effect=sleep):
            sources.overpass(cfg, self.ctx, Path(self.tmp.name)/'response.osm')
        self.assertEqual(clocks[0], 30)

    def test_recursive_relations_and_restrictions_are_complete(self):
        body = OSM.replace('</osm>', '''
<node id="3" version="1" lon="30.2" lat="50.2"/>
<way id="2" version="1"><nd ref="2"/><nd ref="3"/></way>
<relation id="20" version="1"><member type="relation" ref="10" role="outer"/><tag k="type" v="multipolygon"/></relation>
<relation id="10" version="1"><member type="way" ref="1" role="outer"/><member type="way" ref="2" role="inner"/><tag k="type" v="multipolygon"/></relation>
<relation id="30" version="1"><member type="way" ref="1" role="from"/><member type="node" ref="2" role="via"/><member type="way" ref="2" role="to"/><tag k="type" v="restriction"/></relation></osm>''')
        # libosmium expects nodes before ways before relations.
        import xml.etree.ElementTree as ET
        root = ET.fromstring(body)
        root[:] = sorted(root, key=lambda obj: ('node','way','relation').index(obj.tag))
        path = self.source(ET.tostring(root, encoding='unicode'))
        cut = Path(self.tmp.name)/'cut.osm'
        with redirect_stdout(io.StringIO()):
            osm_extract.extract(path, cut, self.cfg['bbox'])
        result = sources.validate_osm(cut)
        self.assertEqual({r.get('id') for r in result.findall('relation')}, {'10','20','30'})
        self.assertEqual({w.get('id') for w in result.findall('way')}, {'1','2'})
        self.assertEqual({n.get('id') for n in result.findall('node')}, {'1','2','3'})

    def test_missing_relation_member_is_rejected(self):
        with self.assertRaisesRegex(SourceError, 'relation'):
            sources.validate_osm(self.source(OSM.replace('</osm>', '<relation id="1"><member type="relation" ref="9"/></relation></osm>')))

    def test_invalid_coordinates_and_corrupt_metadata_are_rejected(self):
        for bad in ('nan', '181', 'bad'):
            with self.assertRaises(SourceError):
                sources.validate_osm(self.source(OSM.replace('30.005', bad)))
        path, _ = self.publish()
        packages.atomic_json(path.parent/'snapshot.json', {'selection':sources.SELECTION,'coverage':None})
        self.assertEqual(sources.snapshots(self.raw,self.geometry), [])

    def test_package_import_coverage_integrity_and_offline_extract(self):
        import osmium
        src, pbf = self.source(), Path(self.tmp.name)/'local.osm.pbf'
        with osmium.SimpleWriter(str(pbf)) as writer:
            for obj in osmium.FileProcessor(str(src)): writer.add(obj)
        package = packages.register(self.raw, pbf, self.geometry)
        self.ctx.offline = True
        with redirect_stdout(io.StringIO()), patch.object(self.ctx, 'download', side_effect=AssertionError('network')):
            path, meta = sources.acquire({**self.cfg, 'package': package['id']}, self.ctx, self.geometry)
        self.assertEqual(meta['source']['kind'], 'pbf')
        self.assertEqual(len(sources.validate_osm(path).findall('node')), 2)
        with self.assertRaises(SourceError):
            packages.available_packages(self.raw, mapping(box(29, 49, 31, 51)), package['id'])
        pbf.write_bytes(b'corrupt')
        with self.assertRaises(SourceError): packages.verify_package(package)
        with self.assertRaises(SourceError): packages.register(self.raw, pbf, self.geometry)

    def test_catalog_polygon_hole_is_not_covered(self):
        ring = box(29,49,31,51).difference(box(30,50,30.1,50.1))
        feature = {'properties': {'id':'hole','name':'Hole','urls':{'pbf':'https://download.geofabrik.de/hole.osm.pbf'}}, 'geometry':mapping(ring)}
        with patch.object(packages, 'catalog', return_value={'features':[feature]}):
            with self.assertRaisesRegex(SourceError, 'fully covers'):
                packages.suggest(self.raw, self.geometry, offline=True)

    def test_suggest_compares_package_bytes_and_unknown_size_never_downloads(self):
        from unittest.mock import MagicMock
        features = [{'properties': {'id':str(i),'name':str(i),'urls':{'pbf':f'https://download.geofabrik.de/{i}.osm.pbf'}},
                     'geometry':mapping(box(29-i,49-i,31+i,51+i))} for i in (0,1)]
        def head(request, **kwargs):
            response = MagicMock()
            response.headers = {'Content-Length':'200' if request.full_url.endswith('/0.osm.pbf') else '100'}
            response.__enter__.return_value = response
            return response
        with patch.object(packages,'catalog',return_value={'features':features}), patch('urllib.request.urlopen',side_effect=head):
            offer = packages.suggest(self.raw,self.geometry)
        self.assertEqual(offer['id'],'1')
        self.assertEqual(offer['bytes'],100)
        with patch('akadem_maps.network.download') as download:
            with self.assertRaises(SourceError): packages.download_package(self.raw,offer,accepted_bytes=200)
            with self.assertRaises(SourceError): packages.download_package(self.raw,{**offer,'bytes':None},accepted_bytes=None)
        download.assert_not_called()

    def test_prepare_tracks_dem_and_detects_corruption(self):
        self.publish()
        def download(url, path, *args, **kwargs):
            Image.new('RGB', (256,256), (128,0,0)).save(path, format='PNG')
        with patch.object(prepare, 'download', side_effect=download):
            result = offline.prepare_area(self.cfg, self.raw)
        self.assertTrue(offline.status(self.cfg, self.raw)['terrain_ready'])
        with patch.object(prepare, 'download', side_effect=AssertionError('network')):
            offline.prepare_area({**self.cfg, 'id':'another'}, self.raw, offline=True)
        damaged = self.raw/next(iter(result['terrain']))
        damaged.write_bytes(b'broken')
        self.assertFalse(offline.status(self.cfg, self.raw)['terrain_ready'])
        with self.assertRaises(OfflineMissing):
            offline.prepare_area(self.cfg, self.raw, offline=True)

    def test_invalid_dem_does_not_replace_good_file_or_publish(self):
        key = 'terrain/12/1/1.png'
        with patch.object(prepare, 'download', side_effect=lambda url,path,*a,**k: path.write_text('bad')):
            with self.assertRaises(SourceError): offline.ensure_tile(self.ctx,key)
        self.assertFalse((self.raw/key).exists())

    def test_netconvert_preflight_precedes_sources(self):
        with patch.object(runtime, 'check_sumo', side_effect=ToolError('relocated launcher')), patch.object(prepare,'fetch') as fetch:
            with self.assertRaises(ToolError): build_world(self.cfg, Path(self.tmp.name)/'output')
        fetch.assert_not_called()

    def test_full_world_with_new_id_from_prepared_sources_and_blocked_network(self):
        example = Path(__file__).resolve().parents[1]/'examples/tiny'
        cfg = read_json(example/'config.json')
        cfg.update(id='fresh_id', source_kind='osm')  # tiny OSM-format fixture exercises the real-source route
        sources.publish(self.raw, example/'inputs/raw/tiny.osm', sources.coverage(cfg), 'synthetic test fixture')
        def download(url, path, *args, **kwargs):
            Image.new('RGB', (256,256), (128,0,0)).save(path, format='PNG')
        with patch.object(prepare, 'download', side_effect=download):
            offline.prepare_area(cfg, self.raw)
        with patch('urllib.request.urlopen', side_effect=AssertionError('network forbidden')), patch.object(prepare, 'download', side_effect=AssertionError('network forbidden')), redirect_stdout(io.StringIO()):
            result = build_world(cfg, Path(self.tmp.name)/'offline-world', cache=self.raw, offline=True)
        self.assertGreater(result['lanes'], 0)

    def test_missing_synthetic_fixture_never_uses_real_osm(self):
        self.publish()
        with self.assertRaises(OfflineMissing):
            sources.acquire({**self.cfg, 'source_kind':'synthetic'}, self.ctx, self.geometry)

    def test_tool_log_survives_atomic_stage_cleanup(self):
        from akadem_maps.context import atomic_directory
        output = Path(self.tmp.name)/'build'
        with self.assertRaises(ToolError):
            with atomic_directory(output) as stage:
                ctx = BuildContext(stage, self.raw, self.raw, diagnostics=Path(self.tmp.name)/'build.logs')
                log = stage/'netconvert.log'
                log.write_text('Fatal launcher error', encoding='utf8')
                saved = ctx.preserve_log(log)
                raise ToolError(str(saved))
        self.assertFalse(output.exists())
        self.assertEqual(saved.read_text(encoding='utf8'), 'Fatal launcher error')


class NetworkDeadlineTests(unittest.TestCase):
    def test_slow_http_body_has_wall_clock_deadline_and_no_publication(self):
        from akadem_maps.network import download
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200); self.end_headers()
                try:
                    for _ in range(15):
                        self.wfile.write(b'x'); self.wfile.flush(); time.sleep(.03)
                except (OSError, ConnectionError): pass
            def log_message(self, *args): pass
        server = ThreadingHTTPServer(('127.0.0.1',0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                dest = Path(tmp)/'data'
                start = time.monotonic()
                with self.assertRaises(TimeoutError): download(f'http://127.0.0.1:{server.server_port}', dest, max_time=.12)
                self.assertLess(time.monotonic()-start, .4)
                self.assertFalse(dest.exists())
                time.sleep(.2)
                self.assertFalse(list(Path(tmp).iterdir()))
        finally:
            server.shutdown(); server.server_close(); thread.join()


class RelocatedSumoTests(unittest.TestCase):
    def test_native_binary_precedes_broken_wrapper(self):
        with tempfile.TemporaryDirectory() as tmp:
            native, scripts = Path(tmp)/'native', Path(tmp)/'Scripts'
            native.mkdir(); scripts.mkdir()
            import os
            name = 'netconvert.exe' if os.name == 'nt' else 'netconvert'
            (native/name).write_text('native'); (scripts/name).write_text('old absolute Python path')
            with patch.object(runtime, '_sumo_home_bins', return_value=iter([native])), patch.object(runtime,'venv_bin_dir', return_value=scripts):
                self.assertEqual(runtime.sumo_binary('netconvert'),native/name)

    def test_preflight_reports_captured_launcher_reason(self):
        result = subprocess.CompletedProcess([], 1, '', 'Cannot launch old/python.exe')
        with patch.object(runtime,'sumo_binary',return_value=Path('netconvert')), patch('akadem_maps.runtime.subprocess.run',return_value=result):
            with self.assertRaisesRegex(ToolError,'old/python.exe'):
                runtime.check_sumo('netconvert')


class CacheAclTests(unittest.TestCase):
    @unittest.skipUnless(__import__('os').name == 'nt', 'Windows ACL inheritance')
    def test_file_moved_out_of_scratch_inherits_parent_acl(self):
        # mkdtemp's 0o700 becomes an owner-only ACL on Python 3.13+; a renamed file kept
        # it and a cache prepared by one account was unreadable for another.
        from akadem_maps.context import scratch_directory
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)/'cache'
            with scratch_directory(parent) as scratch:
                (Path(scratch)/'tile.png').write_bytes(b'x')
                (Path(scratch)/'tile.png').replace(parent/'tile.png')
            self.assertEqual(list(parent.iterdir()), [parent/'tile.png'])
            acl = subprocess.run(['icacls', str(parent/'tile.png')], capture_output=True,
                                 text=True, errors='replace').stdout
            entries = [line for line in acl.splitlines()[:-1] if ':(' in line]
            self.assertTrue(entries)
            self.assertTrue(all('(I)' in line for line in entries), acl)
