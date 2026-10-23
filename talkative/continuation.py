"""
Carrying on a sentence across two dictations (2026-10-23, the user's
request: "if the user stops in a sentence and resumes, do not start with a
capital letter").

Letting go of the hotkey mid-sentence and pressing it again types two
sentences ("And don't show." / "The Azure."). When the next press comes
within config.CONTINUE_SECONDS of the last paste, in the same window, and
the text before the cursor still ends with what was pasted (read through
UI Automation -- if it can't be read, nothing is joined), the full stop
that ended the last dictation is deleted and the new text carries on in
lowercase: "And don't show the Azure."

Only a closing full stop is removed (never "?" or "!"), never after a
bullet list, never for code dictations. The first word stays capitalized
when it is "I", an acronym or a name -- anything that isn't a common
lowercase word (_COMMON below).
"""

import re
import time

from . import config

# Common words that are only capitalized because they start a sentence.
_COMMON = frozenset("""
a an the and or but so because if then than when while where which who what
how why that this these those there here it its i'm he she we they you your
my our their his her him them us me to of in on at for with by from as into
about after before over under between through during without within also
just only even still again not no yes all any some every each both either
neither more most less few many much other another such same very really
quite too maybe perhaps please thanks thank okay ok well now later today
tomorrow yesterday is are was were be been being am do does did done have
has had will would can could should shall may might must let make made get
got go going went come came see saw know knew think thought say said tell
told ask asked give gave take took put send sent show showed use used want
need like look keep find found try call check add remove change fix open
close start stop move turn set run write read work help next first last
one two three four five six seven eight nine ten new old good bad big small
long short right left back up down out off on
""".split())

_last = None  # (pasted text, monotonic time, window handle)


def _foreground():
    try:
        import ctypes
        return ctypes.windll.user32.GetForegroundWindow()
    except Exception:
        return None


def note_paste(text):
    """Remember what was just pasted (called right after the paste)."""
    global _last
    _last = (text, time.monotonic(), _foreground())


def press_info():
    """When and where the hotkey went down, for joins() later."""
    return time.monotonic(), _foreground()


def _norm(s):
    return re.sub(r"\s+", " ", s or "").strip()


def joins(press, before_cursor):
    """True when this dictation carries on the last one's sentence.
    `press` is press_info() from the hotkey press; `before_cursor` the text
    before the cursor now (screen_context.capture())."""
    if _last is None or press is None or not config.CONTINUE_SECONDS:
        return False
    text, pasted_at, hwnd = _last
    pressed_at, press_hwnd = press
    # Negative when the key went down again before the last dictation was
    # even typed -- the quickest continuation of all.
    if pressed_at - pasted_at > config.CONTINUE_SECONDS:
        return False
    if hwnd is None or hwnd != press_hwnd:
        return False
    last = _norm(text)
    if not last.endswith(".") or last.endswith("..") or "\n" in text or "•" in text:
        return False
    before = _norm(before_cursor)
    return bool(before) and before.endswith(last[-60:])


def lowercase_start(text):
    """`text` with its first letter lowercased, if the first word is a
    common word (not "I", an acronym or a name)."""
    m = re.match(r"\s*([A-Za-z][A-Za-z']*)", text)
    if not m:
        return text
    word = m.group(1)
    if word.lower() not in _COMMON or word.isupper() and len(word) > 1:
        return text
    i = m.start(1)
    return text[:i] + text[i].lower() + text[i + 1:]


def chars_to_delete():
    """How many characters to take back before the joined text: the full
    stop, and the space Talkative typed after it (config.APPEND_SPACE)."""
    if _last is None:
        return 0
    text = _last[0]
    return 1 + (len(text) - len(text.rstrip(" ")))
