"""Own subprocesses and terminate them even after a worker-thread failure."""
import atexit
import os
import sys
import threading
import traceback
from .notifications import emit

children = []
_job_handle = None


def cleanup():
    for child in children[:]:
        if child.poll() is None:
            child.terminate()
    for child in children[:]:
        try:
            child.wait(timeout=2)
        except Exception:
            child.kill()
            child.wait()


def fail(message):
    emit("error", message=str(message))
    cleanup()
    os._exit(1)


def install():
    global _job_handle
    if os.name == "nt":
        # A kernel-owned job also cleans up FFmpeg on native NCNN crashes/kill().
        import ctypes
        from ctypes import wintypes
        class BASIC(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                        ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                        ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD)]
        class IO(ctypes.Structure):
            _fields_ = [(name, ctypes.c_uint64) for name in ("ReadOperationCount", "WriteOperationCount", "OtherOperationCount", "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]
        class EXTENDED(ctypes.Structure):
            _fields_ = [("BasicLimitInformation", BASIC), ("IoInfo", IO), ("ProcessMemoryLimit", ctypes.c_size_t),
                        ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateJobObjectW.restype = wintypes.HANDLE
        kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        _job_handle = kernel.CreateJobObjectW(None, None)
        info = EXTENDED()
        info.BasicLimitInformation.LimitFlags = 0x2000  # KILL_ON_JOB_CLOSE
        if not _job_handle or not kernel.SetInformationJobObject(_job_handle, 9, ctypes.byref(info), ctypes.sizeof(info)) or not kernel.AssignProcessToJobObject(_job_handle, kernel.GetCurrentProcess()):
            raise ctypes.WinError(ctypes.get_last_error())
    else:
        os.setsid()
    atexit.register(cleanup)
    def thread_failed(args):
        traceback.print_exception(args.exc_type, args.exc_value, args.exc_traceback, file=sys.stderr)
        fail(args.exc_value)
    threading.excepthook = thread_failed
    def control():
        for line in sys.stdin:
            if line.strip() == "cancel":
                cleanup()
                emit("cancelled")
                os._exit(130)
    threading.Thread(target=control, daemon=True).start()
