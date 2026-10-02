"""Bounded downloads. Only the caller can publish a completed temporary file.

A daemon does blocking DNS/TLS/reads so even a stalled peer cannot extend the caller's
wall-clock budget. Cancellation/deadline revokes publication and the worker cleans up.
"""
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

from .errors import NetworkError


def retry_after(value):
    try:
        return max(0, float(value))
    except (ValueError, TypeError):
        try:
            return max(0, (parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds())
        except (ValueError, TypeError, OverflowError):
            return 0


def download(url, path, form=None, max_time=180):
    from .core.prepare import user_agent
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name('.' + path.name + '.' + uuid.uuid4().hex + '.part')
    done, abandoned = threading.Event(), threading.Event()
    completion_lock = threading.Lock()
    errors = []
    deadline = time.monotonic() + max_time

    def receive():
        try:
            data = urllib.parse.urlencode({'data': form}).encode() if form else None
            request = urllib.request.Request(url, data=data, headers={'User-Agent': user_agent()})
            with urllib.request.urlopen(request, timeout=max_time) as response:
                expected = response.headers.get('Content-Length')
                received = 0
                with completion_lock:
                    if not abandoned.is_set():
                        temporary.touch()
                while not abandoned.is_set():
                    block = response.read1(256 * 1024)
                    if not block:
                        break
                    # Do not hold a Windows file handle across a stalled socket read:
                    # the caller must be able to remove its stage on cancellation.
                    with completion_lock:
                        if abandoned.is_set():
                            break
                        with temporary.open('ab') as stream:
                            stream.write(block)
                    received += len(block)
                    if time.monotonic() >= deadline:
                        raise TimeoutError(f'Download timed out after {max_time:g} s')
                if expected is not None and received != int(expected) and not abandoned.is_set():
                    raise NetworkError(f'Incomplete HTTP body: {received} of {expected} bytes')
        except urllib.error.HTTPError as exc:
            errors.append(NetworkError(f'HTTP {exc.code}', retry_after(exc.headers.get('Retry-After'))))
            exc.close()
        except BaseException as exc:
            errors.append(exc)
        finally:
            with completion_lock:
                if abandoned.is_set() or errors:
                    temporary.unlink(missing_ok=True)
                done.set()

    threading.Thread(target=receive, name='source-download', daemon=True).start()
    try:
        while not done.wait(min(0.1, max(0, deadline - time.monotonic()))):
            if time.monotonic() >= deadline:
                raise TimeoutError(f'Download timed out after {max_time:g} s')
        if errors:
            raise errors[0]
        if time.monotonic() > deadline:
            raise TimeoutError(f'Download timed out after {max_time:g} s')
        temporary.replace(path)
    finally:
        with completion_lock:
            abandoned.set()
            temporary.unlink(missing_ok=True)
