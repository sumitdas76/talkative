"""
The last dictation Talkative typed, kept in memory only, so it can be
taken back ("scratch that") or typed again ("type that again"). Never
written to disk or to any log. Forgotten after config.LAST_DICTATION_SECONDS,
after sleep, and at exit. (Backlog undo-retype-last, PROJECT_CHECKS
2026-11-23.)

Taking it back deletes only what can be checked: the same window, nothing
selected, and the exact text Talkative typed right before the caret. When
the app doesn't let that be read (terminals, some Electron boxes), nothing
is deleted and the user is told to press Ctrl+Z: wrongly deleting words is
the worst failure a dictation tool can have, so there's no blind
Backspacing.

The checks and counting are pure functions (tools/undo_retype_test.py);
app.py does the keys and the messages.
"""

import re
import threading
import time

from . import config

REMOVE = "remove"
RETYPE = "retype"

# The whole dictation must be one of these (case, punctuation and extra
# spaces ignored); a phrase inside a longer dictation is just text.
_COMMANDS = {
    "scratch that": REMOVE,
    "delete that": REMOVE,
    "undo that": REMOVE,
    "type that again": RETYPE,
    "type it again": RETYPE,
    "paste that again": RETYPE,
}


class Last:
    def __init__(self, text, typed, taken, target):
        self.text = text      # the dictation's own text (typed again as is)
        self.typed = typed    # exactly what was pasted, incl. a joined start and the space after
        self.taken = taken    # what was Backspaced before it (a join's ". "): put back on removal
        self.target = target  # paste_target.Target of the window it went into
        self.at = time.monotonic()


_lock = threading.Lock()
_last = None


def remember(text, typed, taken="", target=None):
    global _last
    with _lock:
        _last = Last(text, typed, taken, target)


def forget():
    global _last
    with _lock:
        _last = None


def get():
    """The last dictation, or None if there's none or it's too old."""
    global _last
    with _lock:
        if _last is not None and time.monotonic() - _last.at > config.LAST_DICTATION_SECONDS:
            _last = None
        return _last


def command(raw):
    """REMOVE / RETYPE when the whole dictation is one of the commands,
    else None."""
    words = re.sub(r"[^\w\s']", " ", (raw or "").lower())
    return _COMMANDS.get(" ".join(words.split()))


def _lines(s):
    return (s or "").replace("\r\n", "\n").replace("\r", "\n").replace(" ", " ")


def backspaces(typed):
    """Backspaces that delete `typed`: one per character, and one per line
    break (an edit control deletes a CRLF pair with one Backspace)."""
    return len(_lines(typed))


def why_not_removable(last, foreground, read):
    """None when `last` can be deleted with backspaces(); else the reason,
    for the user. `foreground` is the window in front now; `read` is
    screen_context.caret_and_selection() there."""
    if last is None:
        return "There's no recent dictation to remove."
    if not last.typed:
        return "The last dictation wasn't typed anywhere, so there's nothing to remove."
    hwnd = getattr(last.target, "hwnd", None)
    if hwnd and foreground != hwnd:
        return ("The last dictation was typed into another window, "
                "so nothing was removed.")
    if read is None:
        return ("Couldn't read the text here, so nothing was removed. "
                "Press Ctrl+Z to undo it.")
    before, selected = read
    if selected:
        return "Some text is selected, so nothing was removed."
    if not _lines(before).endswith(_lines(last.typed)):
        return ("The text before the cursor has changed since, so nothing "
                "was removed. Press Ctrl+Z to undo it.")
    return None
