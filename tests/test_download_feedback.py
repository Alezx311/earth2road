"""Exercise the Windows urllib branch against a local HTTP server, without public APIs."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from akadem_maps.context import BuildContext
from akadem_maps.core.prepare import download, fetch
from akadem_maps.world import validate_config


@unittest.skipUnless(os.name == 'nt', 'Windows urllib download implementation')
class DownloadFeedbackTests(unittest.TestCase):
    def test_http_failure_falls_back_and_records_successful_source(self):
        requests = []

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                requests.append((self.path, self.headers.get('User-Agent')))
                self.rfile.read(int(self.headers.get('Content-Length', 0)))
                self.send_response(504 if self.path == '/busy' else 200)
                self.end_headers()
                if self.path != '/busy':
                    self.wfile.write(b'<osm><node id="1" lat="50" lon="30"/><node id="2" lat="50.01" lon="30"/>'
                                     b'<way id="1"><nd ref="1"/><nd ref="2"/><tag k="highway" v="residential"/></way></osm>')

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                world, raw = root/'world', root/'raw'
                world.mkdir()
                raw.mkdir()
                url = f'http://127.0.0.1:{server.server_port}'
                cfg = validate_config({'id': 'test', 'name': 'Test', 'bbox': [30, 50, 30.01, 50.01],
                                       'overpass': url+'/busy', 'overpass_mirrors': [url+'/ok']})
                events = []
                ctx = BuildContext(world, raw, root, emit=lambda event, **data: events.append((event, data)))
                with patch('time.sleep'):
                    result = fetch(cfg, ctx)
                self.assertEqual(result.tag, 'osm')
                self.assertEqual(json.loads((world/'sources.json').read_text())['source'], url+'/ok')
                self.assertEqual([event for event, _ in events], ['download', 'warning', 'download'])
                self.assertIn('504', events[1][1]['message'])
                self.assertTrue(all(agent.startswith('Earth2Road/') for _, agent in requests))
                self.assertEqual([path for path, _ in requests], ['/busy', '/ok'])
                self.assertFalse((raw/'test.osm.part').exists())
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_timeout_does_not_publish_partial_download(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp)/'osm.xml'
            with patch('urllib.request.urlopen', side_effect=TimeoutError('timed out')) as request, patch('time.sleep'):
                with self.assertRaises(TimeoutError):
                    download('http://127.0.0.1/unreachable', dest, max_time=0.05)
            self.assertEqual(request.call_count, 1)
            self.assertFalse(dest.exists())
