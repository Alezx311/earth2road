"""Explicit build directories, source integrity, atomic publication."""
from contextlib import contextmanager
from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
import shutil
import uuid

RESOURCES = Path(__file__).parent / 'resources'

def sha256(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()

def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)+'\n', encoding='utf8')

def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf8'))

def contained(root, relative):
    root = Path(root).resolve()
    candidate = (root / relative).resolve()
    if not candidate.is_relative_to(root):
        raise ValueError(f'Path escapes package: {relative}')
    return candidate

def _alive(pid):
    if pid == os.getpid():
        return True
    if os.name == 'nt':
        import ctypes
        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        code = ctypes.c_ulong()
        ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        ctypes.windll.kernel32.CloseHandle(handle)
        return code.value == 259  # STILL_ACTIVE
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True

def _remove_abandoned_stages(output):
    """Stages of a killed build (no cleanup ran) whose owner process is gone."""
    for owner in output.parent.glob('.'+output.name+'.stage-*.pid'):
        try:
            pid = int(owner.read_text())
        except (OSError, ValueError):
            continue
        if not _alive(pid):
            shutil.rmtree(owner.with_suffix(''), ignore_errors=True)
            owner.unlink(missing_ok=True)

@contextmanager
def atomic_directory(output):
    output = Path(output).resolve()
    if output.exists():
        raise FileExistsError(f'Output already exists: {output}; choose a new directory')
    output.parent.mkdir(parents=True, exist_ok=True)
    _remove_abandoned_stages(output)
    stage = output.parent / ('.'+output.name+'.stage-'+uuid.uuid4().hex)
    owner = stage.with_name(stage.name+'.pid')
    stage.mkdir()
    owner.write_text(str(os.getpid()))
    try:
        yield stage
        if output.exists():
            raise FileExistsError(f'Output appeared during build: {output}')
        stage.rename(output)
    finally:
        if stage.exists():
            shutil.rmtree(stage)
        owner.unlink(missing_ok=True)

@dataclass
class BuildContext:
    world: Path
    raw: Path
    config_root: Path
    offline: bool = False
    resource_root: Path = RESOURCES
    inputs: dict = field(default_factory=dict)
    config_inputs: dict = field(default_factory=dict)
    expected: dict = field(default_factory=dict)
    emit: object = None
    _last_progress: float = 0.0

    def progress(self, stage, fraction):
        """Monotonic stage event for GUI clients; a no-op without an event sink."""
        fraction = max(self._last_progress, float(fraction))
        self._last_progress = fraction
        if self.emit:
            self.emit('stage', stage=stage, progress=round(fraction, 3))

    def notify(self, event, **data):
        """Informational event ('download', 'warning') for GUI clients; a no-op without a sink."""
        if self.emit:
            self.emit(event, **data)

    @property
    def build(self):
        return self.world

    def resource(self, name):
        path = contained(self.resource_root, name)
        if not path.is_file():
            raise FileNotFoundError(f'Missing generator resource: {name}')
        self.config_inputs['resources/'+name] = path
        return path

    def config_file(self, name):
        path = contained(self.config_root, name)
        self.config_inputs['config_root/'+Path(name).as_posix()] = path
        return path

    def record_input(self, path):
        path = Path(path)
        name = path.relative_to(self.raw).as_posix()
        digest = sha256(path)
        if name in self.expected and self.expected[name] != digest:
            raise ValueError(f'Input SHA-256 mismatch: {name}')
        self.inputs[name] = {'sha256': digest, 'bytes': path.stat().st_size}

    def download(self, url, path, form=None, max_time=180):
        if self.offline:
            raise FileNotFoundError(f'Offline input is missing: {Path(path).relative_to(self.raw)}')
        from akadem_maps.core.prepare import download
        try:
            download(url, path, form, max_time)
        except Exception as exc:
            raise RuntimeError(f'Download failed for {url}: {exc}') from exc
