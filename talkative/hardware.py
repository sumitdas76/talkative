"""What this PC can do, for sizing the local models to it.

Talkative runs on anything from an old dual-core laptop with DDR4 to a
current desktop, with or without an NVIDIA GPU. Nothing here guesses from
CPU model names: it reads core count and RAM from Windows, asks
CTranslate2 whether a CUDA device is usable, and the engines measure their
own speed at load (see grammar_engine.load()) -- so an unfamiliar or slow
machine adapts to what it actually does, not to what it was expected to do.

Pure Windows APIs through ctypes: no new dependencies.
"""

import ctypes
import functools
import os
from ctypes import wintypes


@functools.lru_cache(maxsize=None)
def physical_cores():
    """Physical CPU cores (hyper-threads not counted). CTranslate2 runs
    fastest with one thread per physical core -- measured 2026-09-27 on a
    6-core/12-thread Ryzen: 6 threads beat both the default 4 and 12."""
    try:
        class _Info(ctypes.Structure):
            _fields_ = [("mask", ctypes.c_size_t), ("relationship", wintypes.DWORD),
                        ("_union", ctypes.c_ubyte * 16)]

        k32 = ctypes.windll.kernel32
        size = wintypes.DWORD(0)
        k32.GetLogicalProcessorInformation(None, ctypes.byref(size))
        buf = (_Info * (size.value // ctypes.sizeof(_Info)))()
        if not k32.GetLogicalProcessorInformation(buf, ctypes.byref(size)):
            raise OSError
        cores = sum(1 for info in buf if info.relationship == 0)  # RelationProcessorCore
        if cores:
            return cores
    except Exception:
        pass
    return max(1, (os.cpu_count() or 2) // 2)


def cpu_threads():
    """Threads for a model on the CPU: one per physical core, at least 2,
    at most 8 (beyond that memory bandwidth, not cores, is the limit)."""
    return max(2, min(8, physical_cores()))


@functools.lru_cache(maxsize=None)
def ram_gb():
    try:
        class _Mem(ctypes.Structure):
            _fields_ = [("length", wintypes.DWORD), ("load", wintypes.DWORD),
                        ("total", ctypes.c_ulonglong), ("avail", ctypes.c_ulonglong),
                        ("total_page", ctypes.c_ulonglong), ("avail_page", ctypes.c_ulonglong),
                        ("total_virtual", ctypes.c_ulonglong), ("avail_virtual", ctypes.c_ulonglong),
                        ("avail_ext", ctypes.c_ulonglong)]

        m = _Mem()
        m.length = ctypes.sizeof(_Mem)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)):
            return round(m.total / 2**30, 1)
    except Exception:
        pass
    return 0.0


@functools.lru_cache(maxsize=None)
def cuda_devices():
    """NVIDIA GPUs CTranslate2 can see. Seeing one does not mean the CUDA
    libraries (cuBLAS/cuDNN) are installed -- callers must still fall back
    to the CPU if loading or the first run on the GPU fails."""
    try:
        import ctranslate2

        return ctranslate2.get_cuda_device_count()
    except Exception:
        return 0


def summary():
    return {"physical_cores": physical_cores(), "logical_cores": os.cpu_count(),
            "ram_gb": ram_gb(), "cuda_devices": cuda_devices()}
