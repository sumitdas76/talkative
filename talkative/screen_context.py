"""
The text just before the cursor in the field being dictated into, so
speech-to-text can continue it the way a person would: names, product
terms and spellings already on screen come out spelled the same way
(idea 2, 2026-10-23 -- the biggest accuracy feature Wispr Flow has).

Read once, when the hotkey goes down, through the same Windows UI
Automation that focus_check.py uses: the focused control's TextPattern
(text up to the caret), or failing that its ValuePattern (the whole value,
whose end stands in for the caret). Password fields are never read. Only
the last config.CONTEXT_MAX_CHARS characters are kept, in memory, for that
one dictation; nothing is stored.

Whether it's used: config.CONTEXT_LOCAL (it never leaves the PC) and
config.CONTEXT_CLOUD (the text goes to the speech service along with the
audio, PRIVACY.md). Both on, and not settings since 2026-10-26.

caret_rect() reads only where the cursor is (never text), to put
on-screen messages next to it (error_toast).
"""

import ctypes
import logging
import re
import threading
import unicodedata
from ctypes import wintypes

import pythoncom
import uiautomation as auto

from . import config

log = logging.getLogger(__name__)


# Groq's Whisper refuses a prompt over 224 tokens, and the punctuation
# prompt already takes ~35. English runs ~4 characters a token, but other
# scripts can be one token a character or worse, so non-ASCII text counts
# as a whole token per character.
_MAX_TOKENS = 120


def _tokens(text):
    ascii_chars = sum(c < "\x80" for c in text)
    return ascii_chars / 4 + (len(text) - ascii_chars)


def _words_only(text):
    """`text` without icon and line-drawing characters, or "" when no letter is left.
    A terminal app's empty input box (Claude Code) has only its border
    line before the cursor: a prompt of nothing but "────" made Cloud's
    Whisper return no words at all, on two PCs (2026-10-28/29)."""
    text = "".join(" " if unicodedata.category(c) == "So" or unicodedata.category(c)[0] == "C"
                   else c for c in text or "")
    return text if any(c.isalpha() for c in text) else ""


def _tail(text, limit):
    """The last `limit` characters of `text` (fewer if they'd exceed
    _MAX_TOKENS), whitespace collapsed, starting at a word boundary (a cut
    word would bias Whisper toward nonsense)."""
    text = re.sub(r"\s+", " ", text or "").strip()
    if len(text) > limit:
        text = text[-limit:]
        space = text.find(" ")
        text = text[space + 1:] if 0 <= space < 40 else text
    while text and _tokens(text) > _MAX_TOKENS:
        space = text.find(" ")
        text = text[space + 1:] if space >= 0 else ""
    return text


def _before_caret(control, limit):
    """Text before the caret via TextPattern, or None if unavailable."""
    try:
        pattern = control.GetPattern(auto.PatternId.TextPattern)
    except Exception:
        return None
    if pattern is None:
        return None
    try:
        selection = pattern.GetSelection()
        if not selection:
            return None
        rng = selection[0].Clone()
        # Collapse to the caret (the start of any selected text), then reach
        # back. Twice the limit, as whitespace runs are collapsed later.
        # waitTime=0: uiautomation otherwise sleeps 0.5 s after each call.
        rng.MoveEndpointByRange(auto.TextPatternRangeEndpoint.End, rng,
                                auto.TextPatternRangeEndpoint.Start, waitTime=0)
        rng.MoveEndpointByUnit(auto.TextPatternRangeEndpoint.Start,
                               auto.TextUnit.Character, -2 * limit, waitTime=0)
        return rng.GetText(2 * limit + 1)
    except Exception:
        return None


def around_caret(limit=80):
    """(text before, text after) the caret or selection in the focused
    control, raw (whitespace kept), at most `limit` characters each; None
    when the caret can't be located (no TextPattern -- ValuePattern's whole
    value doesn't say where the caret is) or it's a password field. Used
    on this PC only, to fit a dictation into the middle of a sentence
    (continuation.fit_to_cursor); never sent anywhere. Never raises."""
    try:
        pythoncom.CoInitialize()
    except Exception:
        pass
    try:
        control = auto.GetFocusedControl()
        if control is None or control.IsPassword:
            return None
        pattern = control.GetPattern(auto.PatternId.TextPattern)
        if pattern is None:
            return None
        selection = pattern.GetSelection()
        if not selection:
            return None
        start, end = auto.TextPatternRangeEndpoint.Start, auto.TextPatternRangeEndpoint.End
        before = selection[0].Clone()
        before.MoveEndpointByRange(end, before, start, waitTime=0)
        before.MoveEndpointByUnit(start, auto.TextUnit.Character, -limit, waitTime=0)
        after = selection[0].Clone()
        after.MoveEndpointByRange(start, after, end, waitTime=0)
        after.MoveEndpointByUnit(end, auto.TextUnit.Character, limit, waitTime=0)
        return before.GetText(limit + 1), after.GetText(limit + 1)
    except Exception:
        log.debug("caret text unavailable", exc_info=True)
        return None


def capture(limit=None, for_prompt=False):
    """The text before the cursor in the focused control ("" when there is
    none, it's a password field, or it can't be read). Never raises.
    `for_prompt`: for the speech prompt, without icons and line drawing
    (_words_only); continuation compares the text as typed, so not there."""
    limit = limit or config.CONTEXT_MAX_CHARS
    try:
        pythoncom.CoInitialize()
    except Exception:
        pass
    try:
        control = auto.GetFocusedControl()
        if control is None:
            return ""
        try:
            if control.IsPassword:
                return ""
        except Exception:
            return ""  # can't rule it out
        text = _before_caret(control, limit)
        if text is None:
            try:
                value = control.GetPattern(auto.PatternId.ValuePattern)
                text = value.Value if value is not None else ""
            except Exception:
                text = ""
        return _tail(_words_only(text) if for_prompt else text, limit)
    except Exception:
        log.debug("screen context unavailable", exc_info=True)
        return ""


class _GUIThreadInfo(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("flags", wintypes.DWORD),
                ("hwndActive", wintypes.HWND), ("hwndFocus", wintypes.HWND),
                ("hwndCapture", wintypes.HWND), ("hwndMenuOwner", wintypes.HWND),
                ("hwndMoveSize", wintypes.HWND), ("hwndCaret", wintypes.HWND),
                ("rcCaret", wintypes.RECT)]


# A focused control this short is an input box: its own rectangle is a
# good enough "where the text goes". Taller is a whole document or pane
# (a terminal's view), whose top can be far from the caret.
_INPUT_BOX_MAX_HEIGHT = 200


def _uia_caret(control):
    pattern = control.GetPattern(auto.PatternId.TextPattern)
    if pattern is None:
        return None
    selection = pattern.GetSelection()
    if not selection:
        return None
    rng = selection[0].Clone()
    start, end = auto.TextPatternRangeEndpoint.Start, auto.TextPatternRangeEndpoint.End
    rng.MoveEndpointByRange(end, rng, start, waitTime=0)
    rects = rng.GetBoundingRectangles()
    if not rects:
        # A collapsed caret often has no rectangle; the character at it does.
        rng.ExpandToEnclosingUnit(auto.TextUnit.Character, waitTime=0)
        rects = rng.GetBoundingRectangles()
    if not rects:
        return None
    r = rects[0]
    return r.left, r.top, r.right, r.bottom


def _win32_caret():
    user32 = ctypes.windll.user32
    fg = user32.GetForegroundWindow()
    info = _GUIThreadInfo(cbSize=ctypes.sizeof(_GUIThreadInfo))
    if not fg or not user32.GetGUIThreadInfo(
            user32.GetWindowThreadProcessId(fg, None), ctypes.byref(info)):
        return None
    if not info.hwndCaret:
        return None
    rc = info.rcCaret
    top_left = wintypes.POINT(rc.left, rc.top)
    bottom_right = wintypes.POINT(rc.right, rc.bottom)
    user32.ClientToScreen(info.hwndCaret, ctypes.byref(top_left))
    user32.ClientToScreen(info.hwndCaret, ctypes.byref(bottom_right))
    return top_left.x, top_left.y, bottom_right.x, bottom_right.y


def _inside_foreground(rect):
    """The rect's centre is inside the foreground window. Guards against
    coordinates in another scale (this process isn't DPI-aware; on a
    scaled screen a provider may report physical pixels) -- better the
    fallback spot than a message somewhere unrelated."""
    user32 = ctypes.windll.user32
    win = wintypes.RECT()
    if not user32.GetWindowRect(user32.GetForegroundWindow(), ctypes.byref(win)):
        return False
    x, y = (rect[0] + rect[2]) // 2, (rect[1] + rect[3]) // 2
    return win.left <= x <= win.right and win.top <= y <= win.bottom


def caret_rect():
    """Screen rectangle (left, top, right, bottom) of the text cursor in the
    focused control -- or of the focused input box when the cursor itself
    can't be found -- or None. For placing on-screen messages where the
    user is looking (error_toast). Reads positions only, never text.
    Never raises; can be slow in a busy app, so callers cap the wait."""
    try:
        pythoncom.CoInitialize()
    except Exception:
        pass
    found = None
    control = None
    try:
        control = auto.GetFocusedControl()
        if control is not None:
            found = _uia_caret(control)
    except Exception:
        log.debug("UIA caret unavailable", exc_info=True)
    if found is None:
        try:
            found = _win32_caret()
        except Exception:
            log.debug("Win32 caret unavailable", exc_info=True)
    if found is None and control is not None:
        try:
            r = control.BoundingRectangle
            if 0 < r.bottom - r.top <= _INPUT_BOX_MAX_HEIGHT and r.right > r.left:
                found = r.left, r.top, r.right, r.bottom
        except Exception:
            pass
    try:
        if found is not None and _inside_foreground(found):
            return found
    except Exception:
        pass
    return None


# At least one word per this many seconds of recording (people hold the
# key a moment before and after a short word), or a result made
# with screen context is retried without it (see suspect()).
_SECONDS_PER_WORD = 3.0


def suspect(text, seconds):
    """Whether a transcript made WITH screen context looks like the
    context broke it, so the same audio is worth one more try without it
    (app._retry_without_context). On 2026-10-28/29/30 context made Cloud
    return nothing (15 of 105 on the user's office PC, 10-30), a few
    words for many seconds of speech, or script no English speaker
    dictated ("Täggua青", 10-30). Every other result is trusted: an
    invented sentence of the right length ("I will see you." for "In a
    reviewer window", 10-29) can't be told apart from real speech."""
    text = text or ""
    words = len(text.split())
    if words == 0:
        return True
    if words < seconds / _SECONDS_PER_WORD:
        return True
    # CJK and later blocks: English dictation never produces them.
    return any(ord(ch) >= 0x2E80 and unicodedata.category(ch).startswith("L")
               for ch in text)


class Pending:
    """capture() started on its own thread when the hotkey goes down (UIA
    calls into some apps take a while, and the keyboard hook must not
    wait), collected when the dictation is processed."""

    def __init__(self):
        self._text = ""
        self._done = threading.Event()
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        try:
            self._text = capture(for_prompt=True)
        finally:
            self._done.set()

    def get(self, timeout=1.0):
        """The captured text, or "" if it isn't ready within `timeout`."""
        return self._text if self._done.wait(timeout) else ""


def enabled(cloud):
    """Whether context is used for a dictation processed in this mode."""
    return config.CONTEXT_CLOUD if cloud else config.CONTEXT_LOCAL
