import threading
import time

import pyperclip
from pynput.keyboard import Controller, Key

from . import config

_controller = Controller()
_paste_lock = threading.Lock()


def insert_text(text):
    """Copy text to the clipboard, paste it via simulated Ctrl+V into
    whatever control currently has focus, then restore the user's previous
    clipboard contents a moment later. In "clipboard" mode, only copy --
    the user pastes manually, and the clipboard is not restored."""
    if config.INSERT_MODE == "clipboard":
        pyperclip.copy(text)
        return

    if config.APPEND_SPACE:
        text = text + " "

    # One paste at a time, from saving the clipboard to restoring it. Two
    # dictations finishing close together used to interleave: the second
    # saved the first one's text as "the user's clipboard" and put that
    # back, so whatever the user had copied was lost (reproduced by
    # tools/e2e/clipboard_race_test.py, 2026-10-04). Called from the
    # processing thread, never the hotkey listener, so the wait is fine.
    with _paste_lock:
        try:
            previous = pyperclip.paste()
        except Exception:
            previous = None

        pyperclip.copy(text)

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
                pyperclip.copy(previous)
            except Exception:
                pass
