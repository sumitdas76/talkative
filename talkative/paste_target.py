"""Paste where the user dictated, even if they switched windows since.

Text arrives a second or more after the hotkey is let go (transcription,
grammar). Users move on in that time -- Alt+Tab to another app -- and the
paste used to go wherever focus was by then: a "no text box" message, or,
worse, the words typed into the wrong app. (2026-10-27, user report.)

Now the target is remembered: the foreground window and focused control
at the hotkey press (`capture`), switched to whatever window was in front
at the release if the user moved while speaking (`at_release`). At paste
time, if another window is in front, `bring_back` makes the target window
foreground again, puts focus back in the same control, and returns the
window to go back to; `return_to` does that after the paste. The user's
choice: "back, paste, return" -- a brief flicker over losing the words.
"""

import ctypes
import logging
import time

import uiautomation as auto

from . import config

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
user32.GetForegroundWindow.restype = ctypes.c_void_p
user32.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
for _fn in ("IsWindow", "IsIconic", "SetForegroundWindow", "BringWindowToTop"):
    getattr(user32, _fn).argtypes = [ctypes.c_void_p]
user32.ShowWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]

_SW_RESTORE, _SW_MINIMIZE = 9, 6
_VK_HELD = (0x10, 0x11, 0x12, 0x5B, 0x5C)  # Shift, Ctrl, Alt, Win (both)


class Lost(Exception):
    """The target window is gone or couldn't be brought back."""


class Target:
    def __init__(self, hwnd, control=None):
        self.hwnd = hwnd
        self.control = control  # UIA element; None = the window's own focus


def capture():
    """At the hotkey press: the foreground window and its focused control."""
    try:
        control = auto.GetFocusedControl()
    except Exception:
        control = None
    return Target(user32.GetForegroundWindow(), control)


def at_release(target):
    """At the release. Moving to another window *while speaking* means the
    words go there: keep only that window (its own focus is restored when
    it's activated)."""
    hwnd = user32.GetForegroundWindow()
    if target is None or hwnd != target.hwnd:
        return Target(hwnd)
    return target


def _keys_up(timeout):
    """Wait (up to timeout) until no modifier is held -- a paste in the
    middle of the user's Alt+Tab would be Ctrl+Alt+V."""
    end = time.time() + timeout
    while time.time() < end:
        if not any(user32.GetAsyncKeyState(vk) & 0x8000 for vk in _VK_HELD):
            return
        time.sleep(0.03)


def _activate(hwnd):
    """Foreground hwnd. Windows refuses SetForegroundWindow to a background
    process unless its input is attached to the current foreground thread's
    for the call."""
    fg = user32.GetForegroundWindow()
    fg_thread = user32.GetWindowThreadProcessId(fg, None) if fg else 0
    me = kernel32.GetCurrentThreadId()
    attached = bool(fg_thread and fg_thread != me
                     and user32.AttachThreadInput(me, fg_thread, True))
    try:
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
    finally:
        if attached:
            user32.AttachThreadInput(me, fg_thread, False)


def bring_back(target):
    """Make the target foreground again if the user has moved away. Returns
    (window to return to, re-minimize?) or None when nothing moved. Raises
    Lost when it can't be done."""
    if target is None or not target.hwnd:
        return None
    _keys_up(config.PASTE_TARGET_KEYS_WAIT)
    now = user32.GetForegroundWindow()
    if now == target.hwnd:
        return None
    if not user32.IsWindow(target.hwnd):
        raise Lost("window closed")
    minimized = bool(user32.IsIconic(target.hwnd))
    if minimized:
        user32.ShowWindow(target.hwnd, _SW_RESTORE)
    _activate(target.hwnd)
    end = time.time() + 0.5
    while user32.GetForegroundWindow() != target.hwnd and time.time() < end:
        time.sleep(0.02)
    if user32.GetForegroundWindow() != target.hwnd:
        if minimized:
            user32.ShowWindow(target.hwnd, _SW_MINIMIZE)
        raise Lost("Windows kept the other window in front")
    if target.control is not None:
        try:
            target.control.SetFocus()
        except Exception:
            logging.getLogger(__name__).info("couldn't refocus the control; "
                                             "using the window's own focus")
    time.sleep(config.PASTE_TARGET_SETTLE)
    return now, minimized


def return_to(back, target):
    """After the paste: give the user their window back."""
    if not back:
        return
    now, minimized = back
    # Let the target take the Ctrl+V before it loses the foreground.
    time.sleep(config.PASTE_TARGET_SETTLE)
    if minimized and target is not None:
        user32.ShowWindow(target.hwnd, _SW_MINIMIZE)
    if now and user32.IsWindow(now):
        _activate(now)
