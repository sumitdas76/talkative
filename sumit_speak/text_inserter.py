import threading
import time

import pyperclip
from pynput.keyboard import Controller, Key

from . import config

_controller = Controller()


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

    def _restore():
        time.sleep(config.CLIPBOARD_RESTORE_DELAY)
        if previous is not None:
            try:
                pyperclip.copy(previous)
            except Exception:
                pass

    threading.Thread(target=_restore, daemon=True).start()
