import ctypes
import ctypes.wintypes as wt
import threading
import time

import pyperclip
from pynput.keyboard import Controller, Key

from . import config

_controller = Controller()
_paste_lock = threading.Lock()

# --- Win32 clipboard, every format -----------------------------------------
# pyperclip only knows text: a copied image or file list was replaced by an
# empty clipboard after every dictation, and copied formatted text lost its
# formatting (QA run 2026-10-11). These save and restore the raw data of
# every memory-backed format instead.
_user32 = ctypes.WinDLL("user32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_user32.OpenClipboard.argtypes = [wt.HWND]
_user32.OpenClipboard.restype = wt.BOOL
_user32.CloseClipboard.restype = wt.BOOL
_user32.EmptyClipboard.restype = wt.BOOL
_user32.EnumClipboardFormats.argtypes = [wt.UINT]
_user32.EnumClipboardFormats.restype = wt.UINT
_user32.GetClipboardData.argtypes = [wt.UINT]
_user32.GetClipboardData.restype = wt.HANDLE
_user32.SetClipboardData.argtypes = [wt.UINT, wt.HANDLE]
_user32.SetClipboardData.restype = wt.HANDLE
_user32.RegisterClipboardFormatW.argtypes = [wt.LPCWSTR]
_user32.RegisterClipboardFormatW.restype = wt.UINT
_kernel32.GlobalAlloc.argtypes = [wt.UINT, ctypes.c_size_t]
_kernel32.GlobalAlloc.restype = wt.HGLOBAL
_kernel32.GlobalLock.argtypes = [wt.HGLOBAL]
_kernel32.GlobalLock.restype = ctypes.c_void_p
_kernel32.GlobalUnlock.argtypes = [wt.HGLOBAL]
_kernel32.GlobalSize.argtypes = [wt.HGLOBAL]
_kernel32.GlobalSize.restype = ctypes.c_size_t
_kernel32.GlobalFree.argtypes = [wt.HGLOBAL]

_CF_UNICODETEXT = 13
_GMEM_MOVEABLE = 0x0002
# GDI-handle formats (not memory, can't be copied as bytes) and the text
# forms Windows synthesizes from CF_UNICODETEXT / CF_DIB on its own.
_SKIP = {1, 2, 3, 7, 9, 14, 0x80, 0x82, 0x83, 0x8E}
_SAVE_LIMIT = 64 * 2**20  # bigger than this: leave the clipboard alone

# Standard flags that keep an entry out of Win+V clipboard history, cloud
# clipboard sync and clipboard managers: dictated text is put there only
# to paste it, and may be private.
_PRIVATE = [("ExcludeClipboardContentFromMonitorProcessing", b"\0\0\0\0"),
            ("CanIncludeInClipboardHistory", b"\0\0\0\0"),
            ("CanUploadToCloudClipboard", b"\0\0\0\0")]


class _Open:
    """The clipboard, opened with a few retries (another app may hold it
    for a moment)."""

    def __enter__(self):
        for _ in range(25):
            if _user32.OpenClipboard(None):
                return self
            time.sleep(0.02)
        raise OSError("clipboard busy")

    def __exit__(self, *exc):
        _user32.CloseClipboard()


def _set(fmt, data):
    h = _kernel32.GlobalAlloc(_GMEM_MOVEABLE, max(len(data), 1))
    if not h:
        return
    p = _kernel32.GlobalLock(h)
    ctypes.memmove(p, data, len(data))
    _kernel32.GlobalUnlock(h)
    if not _user32.SetClipboardData(fmt, h):
        _kernel32.GlobalFree(h)


def _save_clipboard():
    """[(format, bytes)] of everything copyable on the clipboard, or None
    if it can't be read (then it isn't restored either)."""
    saved, total = [], 0
    with _Open():
        fmt = 0
        while True:
            fmt = _user32.EnumClipboardFormats(fmt)
            if not fmt:
                break
            if fmt in _SKIP:
                continue
            h = _user32.GetClipboardData(fmt)
            if not h:
                continue
            size = _kernel32.GlobalSize(h)
            p = _kernel32.GlobalLock(h)
            if not p:
                continue
            try:
                saved.append((fmt, ctypes.string_at(p, size)))
            finally:
                _kernel32.GlobalUnlock(h)
            total += size
            if total > _SAVE_LIMIT:
                return None
    return saved


def _restore_clipboard(saved):
    with _Open():
        _user32.EmptyClipboard()
        for fmt, data in saved:
            _set(fmt, data)
        # Already in the user's history from when they copied it.
        for name, data in _PRIVATE:
            _set(_user32.RegisterClipboardFormatW(name), data)


def _put_private_text(text):
    with _Open():
        _user32.EmptyClipboard()
        _set(_CF_UNICODETEXT, (text + "\0").encode("utf-16-le"))
        for name, data in _PRIVATE:
            _set(_user32.RegisterClipboardFormatW(name), data)


def copy_only(text):
    """Put text on the clipboard for the user to paste (nowhere to type it)."""
    pyperclip.copy(text.replace("\r\n", "\n").replace("\n", "\r\n"))


def insert_text(text, take_back=0, append_space=None):
    """Copy text to the clipboard, paste it via simulated Ctrl+V into
    whatever control currently has focus, then restore the user's previous
    clipboard contents a moment later. In "clipboard" mode, only copy --
    the user pastes manually, and the clipboard is not restored.
    `take_back` Backspaces go first (continuation.py: the full stop that
    ended the last dictation, when this one carries on its sentence).
    `append_space` overrides config.APPEND_SPACE (None = use it):
    continuation.fit_to_cursor knows when text already follows."""
    # Windows line breaks: a bare "\n" (bullet lists) shows as nothing in
    # older Win32 edit controls.
    text = text.replace("\r\n", "\n").replace("\n", "\r\n")
    if config.INSERT_MODE == "clipboard":
        pyperclip.copy(text)
        return

    if config.APPEND_SPACE if append_space is None else append_space:
        text = text + " "

    # One paste at a time, from saving the clipboard to restoring it. Two
    # dictations finishing close together used to interleave: the second
    # saved the first one's text as "the user's clipboard" and put that
    # back, so whatever the user had copied was lost (reproduced by
    # tools/e2e/clipboard_race_test.py, 2026-10-04). Called from the
    # processing thread, never the hotkey listener, so the wait is fine.
    with _paste_lock:
        try:
            previous = _save_clipboard()
        except Exception:
            previous = None

        try:
            _put_private_text(text)
        except Exception:
            pyperclip.copy(text)

        for _ in range(take_back):
            _controller.press(Key.backspace)
            _controller.release(Key.backspace)
        if take_back:
            # Without a moment here the target app (Windows 11 Notepad,
            # measured) still handles the Backspaces when Ctrl goes down,
            # and the paste arrives as a plain "v".
            time.sleep(0.08)

        _controller.press(Key.ctrl)
        _controller.press("v")
        _controller.release("v")
        _controller.release(Key.ctrl)

        if config.PRESS_ENTER_AFTER:
            time.sleep(0.1)
            _controller.press(Key.enter)
            _controller.release(Key.enter)

        time.sleep(config.CLIPBOARD_RESTORE_DELAY)
        if previous is not None:
            try:
                _restore_clipboard(previous)
            except Exception:
                pass
