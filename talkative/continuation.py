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

Only a closing full stop or trailing-off mark ("...", "…", "-") is removed
(never "?" or "!"; a closing quote after it is kept), never after a
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
eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen
twenty thirty forty fifty sixty seventy eighty ninety hundred thousand
million half twice once wait sure actually probably definitely almost
already always never sometimes usually soon instead though although unless
until since nothing something anything everything someone everyone
""".split())

_last = None  # (pasted text, monotonic time, window handle)

# What can end a dictation that stopped mid-sentence: a full stop, or the
# trailing-off marks Whisper and the grammar model write for a cut-off word
# ("we should-" -> "we should..."). The 1.3.16 D6 test found "..." was
# treated as the end of a sentence and never joined.
# A closing quote or bracket after it stays and is typed back before the
# join: 'there was no full stop after "what."' + 'either' ->
# '..."what" either.' (2026-11-22: a dictation ending '."' never joined).
_END = re.compile(r"(?:\.|\.\.\.|…|[-–—]+\.?)([\"'”’)\]]*)$")


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


def last_text():
    """What the last paste typed, or ""."""
    return _last[0] if _last is not None else ""


def forget():
    """The last paste was taken back ("scratch that"): nothing to join."""
    global _last
    _last = None


def press_info():
    """When and where the hotkey went down, for joins() later."""
    return time.monotonic(), _foreground()


def _norm(s):
    return re.sub(r"\s+", " ", s or "").strip()


last_check = None  # why joins() last decided as it did, for debug.log


def joins(press, before_cursor):
    """True when this dictation carries on the last one's sentence.
    `press` is press_info() from the hotkey press; `before_cursor` the text
    before the cursor now (screen_context.capture())."""
    global last_check
    ok, last_check = _joins(press, before_cursor)
    return ok


def _joins(press, before_cursor):
    if _last is None or press is None or not config.CONTINUE_SECONDS:
        return False, "nothing to carry on"
    text, pasted_at, hwnd = _last
    pressed_at, press_hwnd = press
    # Negative when the key went down again before the last dictation was
    # even typed -- the quickest continuation of all.
    gap = pressed_at - pasted_at
    if gap > config.CONTINUE_SECONDS:
        return False, f"pressed {gap:.1f}s after the last paste"
    if hwnd is None or hwnd != press_hwnd:
        return False, f"different window ({hwnd} -> {press_hwnd})"
    last = _norm(text)
    if not _END.search(last) or "\n" in text or "•" in text:
        return False, "last dictation didn't end in a full stop or '...'"
    before = _norm(before_cursor)
    if not before or not before.endswith(last[-60:]):
        return False, f"text before the cursor doesn't end with it: {before[-60:]!r}"
    return True, f"joined (pressed {gap:+.1f}s after the last paste)"


# Ordinary words that are also common names, months or product names:
# their capital at the start of a dictation may be meant, so it stays.
# (The word list has no names, but "mark", "may" and "word" are words.)
_NAME_WORDS = frozenset("""
may june august march april will mark bill rose grace joy hope faith frank
jack sue pat art dawn summer amber ruby crystal iris lily daisy holly ivy
jade pearl sandy rusty ray gene guy rob nick max chuck dean earl drew cliff
glen wade miles owen victor christian don jean bob ken lee sky river penny
apple amazon android windows word excel teams outlook office edge chrome
slack zoom notepad visual studio code python java swift rust go ruby
talkative claude groq azure cloudflare github git whatsapp google meta grok
whisper docs drive sheets confluence twitter linkedin tableau alt ctrl shift
enter esc tab
""".split())

_words = None


def _word_list():
    global _words
    if _words is None:
        from . import wordlist
        _words = wordlist.load()
    return _words


def _stems(w):
    """`w` and what it may be inflected from: "depicting" -> "depict",
    "needs" -> "need", "cities" -> "city", "stopped" -> "stop"."""
    yield w
    if w.endswith("'s"):
        w = w[:-2]
        yield w
    for end, repl in (("ies", "y"), ("ied", "y"), ("ier", "y"), ("iest", "y"),
                      ("ily", "y"), ("es", ""), ("s", ""), ("ed", ""),
                      ("ed", "e"), ("ing", ""), ("ing", "e"), ("ly", ""),
                      ("er", ""), ("er", "e"), ("ers", ""), ("est", ""),
                      ("ness", ""), ("ment", ""), ("ments", "")):
        if w.endswith(end) and len(w) - len(end) >= 3:
            stem = w[:-len(end)] + repl
            yield stem
            if not repl and len(stem) > 3 and stem[-1] == stem[-2]:
                yield stem[:-1]  # "stopped" -> "stopp" -> "stop"


def _ordinary(word):
    """Is `word` an ordinary lowercase English word (so a capital on it
    only marks a sentence start)?"""
    w = word.lower()
    if w in _COMMON:
        return True
    if w in _NAME_WORDS:
        return False
    words = _word_list()
    return any(s in words for s in _stems(w))


def _capital_meant(word, before):
    """Is `word` written with a capital mid-sentence on screen, or as a
    typed form in the user's Auto Text? Then the capital is meant."""
    for m in re.finditer(rf"(?<![A-Za-z']){re.escape(word)}(?![A-Za-z'])", before or ""):
        head = before[:m.start()].rstrip(" \t ").rstrip(_CLOSERS + "(\"“‘")
        if head and head[-1] not in ".!?:\r\n•" and not _at_prompt(head):
            return True
    for typed in (config.DICTIONARY or {}).values():
        if re.search(rf"(?<![A-Za-z']){re.escape(word)}(?![A-Za-z'])", typed or ""):
            return True
    return False


def lowercase_start(text, before="", english=True):
    """`text` with its first letter lowercased, if the first word is an
    ordinary word: not "I", an acronym, a mixed-case name ("iPhone"), a
    name, or a word `before` (the text on screen) or Auto Text writes with
    a capital mid-sentence. Until 1.3.25 only ~300 _COMMON words were
    lowercased ("...about Reading", "look pretty Jacket", debug.log
    2026-11-22). Not for another language (languages.py): its nouns may be
    English words too ("Hand", "Name" in German)."""
    if not english:
        return text
    m = re.match(r"\s*([A-Za-z][A-Za-z']*)(?:[ -]([A-Za-z][A-Za-z']*))?", text)
    if not m:
        return text
    word, nxt = m.group(1), m.group(2)
    if word == "I" or word.startswith("I'"):
        return text
    if len(word) > 1 and not word[1:].replace("'", "").islower():
        return text  # "GPU", "iPhone", "GitHub", "McDonald"
    # "Harry Potter", "Google Drive", "Provident Fund": a capital on the
    # next word too means a name made of ordinary words (2026-11-23 scan
    # of 15,172 saved texts).
    named = nxt is not None and nxt[0].isupper() and nxt != "I" and not nxt.startswith("I'")
    if word.lower() not in _COMMON and (
            named or not _ordinary(word) or _capital_meant(word, before)):
        return text
    i = m.start(1)
    return text[:i] + text[i].lower() + text[i + 1:]


# fit_to_cursor(): what the text before the cursor ends with when a new
# sentence starts there (closing quotes/brackets after it are skipped).
_SENTENCE_END = ".!?:"
_CLOSERS = "\"')]”’"
_OPENERS = "([{“‘/-"  # no space after these (straight quotes could be either)


# A terminal's input line, read through UI Automation: the whole line is
# one prompt token -- Claude Code's "❯", PowerShell's "PS C:\x>", cmd's
# "C:\x>", bash's "user@pc:~$", zsh's "%" / "➜". (User report 2026-10-27:
# in Claude Code the first word came out lowercase after 2-3 spaces.)
_PROMPT = re.compile(r"(?:PS\s+)?\S*[❯›»>$#%λ➜]")


def _at_prompt(before):
    """Is the cursor right after a terminal prompt (start of fresh input)?"""
    line = re.split(r"[\r\n]", before)[-1].strip()
    return bool(line) and _PROMPT.fullmatch(line) is not None


# A hand-typed list marker right before the cursor: "2)", "3.", "1-",
# and "b)" after a line start or a full stop. (User report 2026-10-31:
# "...sounds fine. 2) put a remaining first" -- the item came out lowercase.)
_LIST_MARKER = re.compile(
    r"(?:^|\s)\d{1,2}[.)]$"
    r"|(?:^|[\r\n]|[.!?:❯>]\s+)(?:\d{1,2}-|[A-Za-z][.)])$")


def _sentence_starts_after(before):
    s = before.rstrip(" \t ")
    if not s or s[-1] in "\r\n":
        return True
    if _LIST_MARKER.search(s):
        return True
    s = s.rstrip(_CLOSERS) or s
    return s[-1] in _SENTENCE_END or s.endswith("•")


def _continues_sentence(after):
    """Does the text after the cursor carry on the same sentence?"""
    s = after.lstrip(" \t ")
    if not s or s[0] in "\r\n":
        return False
    if s[0] in ",.;:!?)]”’\"'":
        return True
    m = re.match(r"[A-Za-z][A-Za-z']*|\d", s)
    if not m:
        return False
    word = m.group(0)
    # "The", "Then", "We" capitalized = a new sentence follows; a name, "I",
    # an acronym or a lowercase word = the same sentence carries on.
    if word == "I" or word.startswith("I'") or not word[0].isupper():
        return True
    if len(word) > 1 and not word[1:].replace("'", "").islower():
        return True  # an acronym or a mixed-case name
    return not _ordinary(word)


def fit_to_cursor(text, before, after, english=True):
    """Fit a dictation typed into the middle of existing text: after a
    mid-sentence word, start in lowercase (and with a space if there isn't
    one); when the same sentence carries on after the cursor, drop the
    full stop. Returns (text, trailing space wanted: True/False, or None to
    leave it to config.APPEND_SPACE). User request 2026-10-25: delete a
    wrong word, dictate the right one, and get "...on tuesday next week"
    without a capital or a stray full stop. Lists are left alone."""
    if not text.strip():
        return text, None
    if _at_prompt(before):
        # Fresh input after a terminal prompt: a sentence start, and what
        # follows the cursor is screen padding or the app's grey hint text
        # ("Try ...", "add the focus guard"), not words to fit around --
        # reading it as the sentence carrying on dropped full stops.
        return text.lstrip(), None
    is_list = "\n" in text or "•" in text
    space = None
    if not is_list and not _sentence_starts_after(before):
        text = lowercase_start(text.lstrip(), before, english)
        if before and not before[-1].isspace() and before[-1] not in _OPENERS:
            text = " " + text
    elif not is_list and before and _LIST_MARKER.search(before):
        text = " " + text.lstrip()  # "2)" typed right before the cursor
    if (not is_list and _continues_sentence(after)
            and text.endswith(".") and not text.endswith("..")):
        text = text[:-1]
    if after:
        # Text follows: a space only if it doesn't already start with one
        # (or with punctuation, which goes straight after the word).
        nxt = after[0]
        space = not (nxt.isspace() or nxt in ",.;:!?)]”’\"'")
    return text, space


def chars_to_delete():
    """How many characters to take back before the joined text: the full
    stop or trailing-off mark, and the space Talkative typed after it
    (config.APPEND_SPACE)."""
    if _last is None:
        return 0
    text = _last[0]
    body = text.rstrip(" ")
    m = _END.search(body)
    return (len(m.group(0)) if m else 1) + (len(text) - len(body))


def closers():
    """The closing quotes/brackets chars_to_delete() takes back with the
    full stop, to type again in front of the joined text."""
    if _last is None:
        return ""
    m = _END.search(_last[0].rstrip(" "))
    return m.group(1) if m else ""
