#!/usr/bin/env python3
"""Exercise the installed CLI away from the checkout, with both exporters."""
import json
from importlib.metadata import distribution
from pathlib import Path
import subprocess
import sys
import sysconfig
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    with tempfile.TemporaryDirectory(prefix='earth2road-wheel-') as tmp:
        work = Path(tmp)
        def run(*args):
            subprocess.run([sys.executable, '-m', 'akadem_maps', *map(str, args)], cwd=work, check=True)
        package = subprocess.check_output(
            [sys.executable, '-c', 'import akadem_maps; print(akadem_maps.__file__)'], cwd=work, text=True).strip()
        if Path(package).resolve().is_relative_to(ROOT / 'akadem_maps'):
            raise RuntimeError('Wheel test imported the checkout; install a non-editable wheel first')
        dist = distribution('earth2road')
        # A venv keeps scripts next to python; a system Windows Python uses <prefix>/Scripts.
        command = Path(sysconfig.get_path('scripts')) / ('earth2road' + ('.exe' if sys.platform == 'win32' else ''))
        version = subprocess.check_output([str(command), '--version'], cwd=work, text=True).strip()
        assert version == dist.version, (version, dist.version)
        help_text = subprocess.check_output([str(command), '--help'], cwd=work, text=True)
        assert 'usage: earth2road' in help_text
        run('doctor')
        run('build', '--config', ROOT/'examples/tiny/config.json', '--inputs', ROOT/'examples/tiny/inputs',
            '--offline', '--output', work/'world')
        run('validate', '--target', 'world', '--input', work/'world')
        run('export', '--target', 'beamng', '--world', work/'world', '--output', work/'beamng')
        run('validate', '--target', 'beamng', '--input', work/'beamng')
        run('export', '--target', 'godot', '--world', work/'world', '--output', work/'godot', '--offline')
        checkout = work/'checkout'
        (checkout/'game').mkdir(parents=True)
        (checkout/'game/project.godot').write_text('config_version=5\n')
        run('install', '--target', 'godot', '--export', work/'godot', '--root', checkout, '--activate')
        assert (checkout/'game/data/active_map').read_text().strip() == 'tiny'
        assert json.loads((checkout/'game/data/tiny/index.json').read_text())['id'] == 'tiny'
        print('INSTALLED_WHEEL_OFFLINE_CHECK passed')


if __name__ == '__main__':
    main()
