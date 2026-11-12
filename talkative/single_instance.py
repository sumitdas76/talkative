"""
One running copy per Windows sign-in (added 2026-11-12, for the Microsoft
Store version: with the GitHub copy and the Store copy both installed and
both starting with Windows, one key press would dictate twice).

A named mutex in the session's "Local\\" namespace: whichever copy starts
first holds it until it exits (Windows releases it even after a crash or
a force-kill, so a dead copy never blocks the next start). The Store
version runs with full trust, outside an app container, so both builds see
the same name. A different Windows user signed in at the same time has
their own session and their own copy, as before.
"""

import ctypes
from ctypes import wintypes

MUTEX_NAME = "Local\\SumitDas.Talkative.Running"
_ERROR_ALREADY_EXISTS = 183

_handle = None   # kept for the life of the process; never closed


def acquire(name=MUTEX_NAME):
    """True if this is the only running copy (and it now holds the name).
    False if another copy already holds it. If the check itself fails,
    returns True: refusing to start over a broken check is worse than the
    rare double copy."""
    global _handle
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    kernel32.CreateMutexW.argtypes = (wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR)
    handle = kernel32.CreateMutexW(None, False, name)
    if not handle:
        return True
    if ctypes.get_last_error() == _ERROR_ALREADY_EXISTS:
        kernel32.CloseHandle(handle)
        return False
    _handle = handle
    return True


def tell_already_running():
    """Plain message box: no Tk yet at this point, and none is needed."""
    MB_ICONINFORMATION, MB_SETFOREGROUND = 0x40, 0x10000
    ctypes.windll.user32.MessageBoxW(
        None,
        "Talkative is already running. Look for its icon in the system tray, "
        "next to the clock (it may be under the ^ arrow).\n\n"
        "If you see this every time Windows starts, Talkative is installed "
        "twice (for example from the Microsoft Store and from GitHub). "
        "Uninstall one of them in Settings > Apps.",
        "Talkative",
        MB_ICONINFORMATION | MB_SETFOREGROUND,
    )
