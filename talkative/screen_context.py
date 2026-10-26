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
"""

import logging
import re
import threading

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


def capture(limit=None):
    """The text before the cursor in the focused control ("" when there is
    none, it's a password field, or it can't be read). Never raises."""
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
        return _tail(text, limit)
    except Exception:
        log.debug("screen context unavailable", exc_info=True)
        return ""


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
            self._text = capture()
        finally:
            self._done.set()

    def get(self, timeout=1.0):
        """The captured text, or "" if it isn't ready within `timeout`."""
        return self._text if self._done.wait(timeout) else ""


def enabled(cloud):
    """Whether context is used for a dictation processed in this mode."""
    return config.CONTEXT_CLOUD if cloud else config.CONTEXT_LOCAL
