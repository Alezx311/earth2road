"""Platform paths for the venv, Godot 4.6 and SUMO binaries.

Linux setup.sh used `.venv/bin/...` and `Godot_v4.6-stable_linux.x86_64`.
Windows uses `.venv/Scripts/` and `Godot_v4.6-stable_win64.exe`. macOS uses
`.venv/bin/` and the app bundle `Godot_v4.6-stable_macos.app` (see tools/godot.sh).
Callers must not hard-code any of these layouts.
"""
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GODOT_VERSION = '4.6-stable'


def venv_dir():
    path = ROOT / '.venv'
    return path if path.is_dir() else None


def venv_bin_dir():
    folder = venv_dir()
    if folder is None:
        return None
    scripts = folder / 'Scripts'
    unix = folder / 'bin'
    if os.name == 'nt' and scripts.is_dir():
        return scripts
    if unix.is_dir():
        return unix
    if scripts.is_dir():
        return scripts
    return None


def venv_python():
    folder = venv_bin_dir()
    if folder is not None:
        for name in ('python.exe', 'python3', 'python'):
            path = folder / name
            if path.exists():
                return path
    return Path(sys.executable)


def _sumo_home_bins():
    try:
        import sumo
        home = Path(getattr(sumo, 'SUMO_HOME', '') or '')
    except Exception:
        home = Path()
    if not home:
        env = os.environ.get('SUMO_HOME')
        home = Path(env) if env else Path()
    if home and (home / 'bin').is_dir():
        yield home / 'bin'


def sumo_binary(name):
    """netconvert, sumo or duarouter from the venv, eclipse-sumo, or PATH."""
    exe = name + ('.exe' if os.name == 'nt' else '')
    candidates = []
    bindir = venv_bin_dir()
    if bindir is not None:
        candidates.extend((bindir / exe, bindir / name))
    for folder in _sumo_home_bins():
        candidates.extend((folder / exe, folder / name))
    found = shutil.which(exe) or shutil.which(name)
    if found:
        candidates.append(Path(found))
    for path in candidates:
        if path.exists():
            return path
    raise FileNotFoundError(
        f'{name} not found. Install eclipse-sumo==1.27.1 into .venv '
        f'(looked in {bindir or ROOT / ".venv"}).'
    )


def godot_names():
    if os.name == 'nt':
        return (f'Godot_v{GODOT_VERSION}_win64.exe',
                f'Godot_v{GODOT_VERSION}_win64_console.exe')
    if sys.platform == 'darwin':
        return (f'Godot_v{GODOT_VERSION}_macos.app/Contents/MacOS/Godot',)
    return (f'Godot_v{GODOT_VERSION}_linux.x86_64',)


def godot_url():
    if os.name == 'nt':
        archive = f'Godot_v{GODOT_VERSION}_win64.exe.zip'
    elif sys.platform == 'darwin':
        archive = f'Godot_v{GODOT_VERSION}_macos.universal.zip'
    else:
        archive = f'Godot_v{GODOT_VERSION}_linux.x86_64.zip'
    return f'https://github.com/godotengine/godot/releases/download/{GODOT_VERSION}/{archive}'


def godot_binary():
    tools = ROOT / '.tools'
    if tools.is_dir():
        for name in godot_names():
            path = tools / name
            if path.is_file():
                return path
        for path in sorted(tools.glob('Godot_v4.6*')):
            if path.is_file() and path.stat().st_size > 1_000_000:
                return path
    raise FileNotFoundError(
        f'Godot {GODOT_VERSION} not found in {tools}. Run setup.ps1 or setup.sh.'
    )


def preload_libsumo():
    """Windows libsumo wheels need SUMO DLLs on PATH before the first start()."""
    try:
        import libsumo
    except ImportError:
        return
    sim = getattr(libsumo, 'simulation', None)
    loader = getattr(sim, 'preloadLibraries', None) if sim is not None else None
    if loader:
        loader()
