"""Windows generator ownership: one job owns Python and all of its descendants.

The job handle deliberately lives until process exit. Windows then closes it and
kills any remaining netconvert/duarouter children, even after a forced game exit.
"""
import _thread
import ctypes
from ctypes import wintypes as w
import os
from pathlib import Path
import threading


def windows_job():
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, w.LPCWSTR]
    kernel.CreateJobObjectW.restype = w.HANDLE
    kernel.GetCurrentProcess.restype = w.HANDLE
    kernel.SetInformationJobObject.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD]
    kernel.AssignProcessToJobObject.argtypes = [w.HANDLE, w.HANDLE]
    kernel.TerminateJobObject.argtypes = [w.HANDLE, w.UINT]
    kernel.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
    kernel.OpenProcess.restype = w.HANDLE
    kernel.WaitForSingleObject.argtypes = [w.HANDLE, w.DWORD]
    kernel.CloseHandle.argtypes = [w.HANDLE]

    class Basic(ctypes.Structure):
        _fields_ = [('process_time', ctypes.c_int64), ('job_time', ctypes.c_int64),
                    ('flags', w.DWORD), ('min_ws', ctypes.c_size_t), ('max_ws', ctypes.c_size_t),
                    ('active', w.DWORD), ('affinity', ctypes.c_size_t),
                    ('priority', w.DWORD), ('scheduling', w.DWORD)]

    class Extended(ctypes.Structure):
        _fields_ = [('basic', Basic), ('io', ctypes.c_uint64 * 6),
                    ('process_memory', ctypes.c_size_t), ('job_memory', ctypes.c_size_t),
                    ('peak_process', ctypes.c_size_t), ('peak_job', ctypes.c_size_t)]

    job = kernel.CreateJobObjectW(None, None)
    limits = Extended()
    limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not job or not kernel.SetInformationJobObject(job, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
        raise ctypes.WinError(ctypes.get_last_error())
    if not kernel.AssignProcessToJobObject(job, kernel.GetCurrentProcess()):
        kernel.CloseHandle(job)
        raise ctypes.WinError(ctypes.get_last_error())
    return kernel, job


def watch_windows(parent=0, cancel_file=None, *, grace=5.0, poll=0.1):
    """Try normal KeyboardInterrupt cleanup, then terminate the whole job if blocked.

    Hold the original parent handle so PID reuse cannot attach us to another game.
    Returns a stop Event; the caller sets it before publishing its terminal event.
    """
    kernel, job = windows_job()
    parent_handle = kernel.OpenProcess(0x100000, False, parent) if parent else None
    done = threading.Event()

    def watch():
        try:
            while not done.wait(poll):
                gone = parent and (not parent_handle or kernel.WaitForSingleObject(parent_handle, 0) == 0)
                cancelled = cancel_file and Path(cancel_file).exists()
                if gone or cancelled:
                    _thread.interrupt_main()
                    if not done.wait(grace):
                        kernel.TerminateJobObject(job, 130)
                    return
        finally:
            if parent_handle:
                kernel.CloseHandle(parent_handle)

    threading.Thread(target=watch, name='generator-owner', daemon=True).start()
    return done
