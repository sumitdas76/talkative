"""
How this copy was installed (added 2026-11-12 for the Microsoft Store
version). The only module that knows; everything else asks it.

The Store version runs inside an MSIX package, which gives the process a
"package identity". The GitHub installer copy and a from-source run have
none. Inside a package three things work differently (docs/PROJECT_CHECKS.md):
start with Windows is a StartupTask declared in the manifest, not the Run
key; app updates come from the Store, never from our own updater; files
under %LOCALAPPDATA% are redirected into the package's private folder by
Windows itself (no code change needed for that).
"""

import ctypes
from ctypes import wintypes
from functools import lru_cache

_APPMODEL_ERROR_NO_PACKAGE = 15700
_ERROR_INSUFFICIENT_BUFFER = 122


@lru_cache(maxsize=1)
def package_full_name():
    """This process's package full name, or "" when it isn't packaged."""
    try:
        func = ctypes.windll.kernel32.GetCurrentPackageFullName
    except AttributeError:          # Windows 7: no packages at all
        return ""
    func.argtypes = (ctypes.POINTER(wintypes.UINT), wintypes.LPWSTR)
    func.restype = wintypes.LONG
    length = wintypes.UINT(0)
    rc = func(ctypes.byref(length), None)
    if rc == _APPMODEL_ERROR_NO_PACKAGE or rc != _ERROR_INSUFFICIENT_BUFFER:
        return ""
    buf = ctypes.create_unicode_buffer(length.value)
    if func(ctypes.byref(length), buf) != 0:
        return ""
    return buf.value


def is_store_build():
    """True when running as the Microsoft Store (MSIX) version."""
    return bool(package_full_name())
