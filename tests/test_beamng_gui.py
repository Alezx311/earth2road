"""GUI export publication and cancellation contracts, without network or BeamNG."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tools'))
import export_beamng_gui as gui
from tests.test_beamng_export import fixture
from akadem_maps.adapters.beamng.export import validate_export
from akadem_maps.context import sha256


class Events:
    def __init__(self):
        self.records = []

    def emit(self, event, **data):
        self.records.append({'event': event, **data})


class GuiExportTests(unittest.TestCase):
    def test_zip_unicode_repeated_exports_and_source_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture(root)
            before = {p.relative_to(root): sha256(p) for p in root.rglob('*') if p.is_file()}
            events = Events()
            first = gui.export_installed('test', root/'Експорт карт', events, root=root)
            second = gui.export_installed('test', root/'Експорт карт', events, root=root)
            self.assertNotEqual(first['output'], second['output'])
            self.assertEqual(sha256(first['zip']), sha256(second['zip']))
            self.assertFalse(first['runtime_verified'])
            validate_export(Path(first['output']))
            self.assertEqual(before, {p: sha256(root/p) for p in before})
            self.assertEqual([r['stage'] for r in events.records[:8]],
                             ['prepare', 'geometry', 'sidewalks', 'buildings', 'dressing', 'validate', 'package', 'validate_zip'])
            metrics = json.loads((Path(first['output'])/'reports/performance.json').read_text())
            self.assertEqual(metrics['optimization'], 'balanced')
            self.assertGreater(metrics['categories']['surfaces']['triangles'], 0)
            with zipfile.ZipFile(first['zip']) as archive:
                self.assertTrue(any(n.startswith('vehicles/common/licenseplates/') for n in archive.namelist()))
                self.assertFalse(any(n.endswith('kyiv-manifest.json') for n in archive.namelist()))
                info = json.loads(archive.read('levels/kyiv_test/info.json'))
                self.assertEqual(info['title'], 'Test')

    def test_missing_data_and_hash_mismatch_publish_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            destination = root/'out'
            with self.assertRaises(FileNotFoundError):
                gui.export_installed('missing', destination, Events(), root=root)
            _, net = fixture(root)
            net.write_text('changed')
            with self.assertRaisesRegex(ValueError, 'hash differs'):
                gui.export_installed('test', destination, Events(), root=root)
            self.assertFalse(destination.exists())

    def test_failed_or_cancelled_export_removes_only_own_stage(self):
        for failure in (KeyboardInterrupt, RuntimeError):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                fixture(root)
                destination = root/'out'
                destination.mkdir()
                old = destination/'previous.zip'
                old.write_bytes(b'previous')
                class Interrupted(Events):
                    def emit(self, event, **data):
                        if data.get('stage') == 'geometry':
                            raise failure
                with self.assertRaises(failure):
                    gui.export_installed('test', destination, Interrupted(), root=root)
                self.assertEqual(list(destination.iterdir()), [old])
                self.assertEqual(old.read_bytes(), b'previous')

    def test_packaging_failure_does_not_publish_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture(root)
            with patch.object(gui, 'deterministic_zip', side_effect=OSError('Disk full')):
                with self.assertRaisesRegex(OSError, 'Disk full'):
                    gui.export_installed('test', root/'out', Events(), root=root)
            self.assertEqual(list((root/'out').iterdir()), [])

    def test_bad_destination_and_source_destination(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture(root)
            blocked = root/'file'
            blocked.write_text('keep')
            with self.assertRaises(OSError):
                gui.export_installed('test', blocked, Events(), root=root)
            with self.assertRaisesRegex(ValueError, 'source data'):
                gui.export_installed('test', root/'game/data/test', Events(), root=root)
            with self.assertRaisesRegex(ValueError, 'Invalid map id'):
                gui.export_installed('../test', root/'out', Events(), root=root)
            self.assertEqual(blocked.read_text(), 'keep')

    def test_zip_rejects_foreign_vehicle_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)/'bad.zip'
            with zipfile.ZipFile(target, 'w') as archive:
                archive.writestr('levels/a/info.json', '{}')
                archive.writestr('vehicles/common/licenseplates/b/plate.png', b'x')
            with self.assertRaisesRegex(ValueError, 'different level'):
                validate_export(target)


if __name__ == '__main__':
    unittest.main()
