"""Protect the publication gate against staged ignored files and secrets."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from check_publication import audit, inspect_file


class PublicationTests(unittest.TestCase):
    def test_staged_file_is_checked_even_after_it_is_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(['git', 'init', '-q', str(root)], check=True)
            (root / '.env').write_text('EXAMPLE=local\n')
            subprocess.run(['git', 'add', '.env'], cwd=root, check=True)
            (root / '.gitignore').write_text('.env\n')
            result = audit(root)
            self.assertFalse(result['ok'])
            self.assertIn('.env', result['findings'])

    def test_secret_is_flagged_without_echoing_its_value(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            secret = 'gh' + 'p_' + 'a' * 36
            (root / 'config.txt').write_text(secret)
            findings = inspect_file(root, Path('config.txt'))
            self.assertIn('GitHub token', findings)
            self.assertNotIn(secret, str(findings))

    def test_synthetic_osm_is_allowed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rel = Path('examples/tiny/inputs/raw/tiny.osm')
            (root / rel).parent.mkdir(parents=True)
            (root / rel).write_text('<osm/>')
            self.assertEqual(inspect_file(root, rel), [])
