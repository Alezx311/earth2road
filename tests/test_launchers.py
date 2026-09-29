"""Shell launcher contracts using fake executables; no engine/downloads required."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
BASH = (str(Path(os.environ.get('ProgramFiles', 'C:/Program Files'))/'Git/bin/bash.exe')
        if os.name == 'nt' else shutil.which('bash'))


@unittest.skipUnless(BASH and Path(BASH).exists(), 'Bash is not installed')
class LauncherTests(unittest.TestCase):
    def test_paths_with_spaces_and_no_bridge_arguments(self):
        for platform, binary in [('Darwin', '.tools/Godot_v4.6-stable_macos.app/Contents/MacOS/Godot'),
                                 ('Linux', '.tools/Godot_v4.6-stable_linux.x86_64')]:
            with self.subTest(platform=platform), tempfile.TemporaryDirectory(prefix='Terra drive ') as tmp:
                root = Path(tmp)
                for folder in ['tools', '.venv/bin', 'game/data/tiny', 'game/.godot']:
                    (root/folder).mkdir(parents=True)
                for file in ['start.sh', 'tools/godot.sh']:
                    shutil.copyfile(ROOT/file, root/file)
                (root/'game/data/active_map').write_text('tiny\n')
                (root/'game/data/tiny/index.json').write_text('{}')
                (root/'game/.godot/global_script_class_cache.cfg').touch()
                engine = root/binary
                engine.parent.mkdir(parents=True, exist_ok=True)
                engine.write_text('#!/usr/bin/env bash\nprintf "%s\\n" "$@" > engine.args\n', newline='\n')
                engine.chmod(0o755)
                python = root/'.venv/bin/python'
                python.write_text('#!/usr/bin/env bash\nprintf "%s\\n" "$@" > bridge.args\necho "Traffic bridge ready"\nsleep 4\n', newline='\n')
                python.chmod(0o755)
                wrapper = root/'check.sh'
                wrapper.write_text(f'#!/usr/bin/env bash\nuname() {{ echo {platform}; }}\nexport -f uname\nexec bash start.sh\n', newline='\n')
                env = {key: value for key, value in os.environ.items() if not key.startswith('AKADEM_')}
                result = subprocess.run([BASH, 'check.sh'], cwd=root, env=env, capture_output=True, text=True, timeout=15)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual((root/'bridge.args').read_text().splitlines(), ['tools/traffic.py'])
                self.assertEqual((root/'engine.args').read_text().splitlines(), ['--path', 'game'])
