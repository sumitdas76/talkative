"""
Learn from the user's own corrections (idea 4, 2026-10-23).

After a dictation is pasted, the field it went into is read again a little
later -- at the next hotkey press, and CHECK_AFTER seconds on. If the
user has since changed a word or two of what Talkative typed ("Kuber
Netties" -> "Kubernetes", "priyanka" -> "Priyanka"), that pair is offered
as an Auto Text entry: listed under Settings -> Auto Text with Add /
Dismiss, plus one tray message. Nothing is added until the user clicks
Add (the user's choice, 2026-10-23).

Only small, sound-alike, name-like fixes count (see suggestions()):
rewording a sentence or swapping "I" for "you" is editing, not a
transcription fix, and must never turn into a replacement that fires on
every later dictation. Password fields are never read. The field text is
compared in memory and dropped; only the word pairs are kept, in
settings.json on this PC (config.FIX_SUGGESTIONS / FIX_DISMISSED).

All UI Automation work runs on one worker thread, so COM objects never
cross threads.
"""

import difflib
import logging
import queue
import re
import threading
import time

from . import config, settings

log = logging.getLogger(__name__)

# Seconds after a paste at which the field is read again (on top of the
# next hotkey press). Watching stops after the last one.
CHECK_AFTER = (30, 180)
_MAX_WATCHES = 5
_MAX_FIELD_CHARS = 100_000
_MAX_SUGGESTIONS = 30

# Words whose change is never a transcription fix to remember.
_COMMON = frozenset("""
a an the and or but of to in on at for with by from as is are was were be been
being this that these those it its i you he she we they me him her us them my
your his our their mine yours not no yes do does did done have has had will
would can could should shall may might must just so very too also if then
than when what which who whom whose where why how there here up down out off
over under again once all any both each few more most other some such only
own same into about against between through during before after above below
""".split())

_WORD = re.compile(r"\w(?:[\w'’\-.@]*\w)?")


def _norm(word):
    return word.lower().replace("’", "'")


def _name_like(words):
    """A capital letter, digit or inner symbol: a name, product or code
    term, the kind of word speech-to-text misspells and a dictionary
    entry can fix. Plain lowercase words ("collars" for "colors") are
    usually homophones in context, which a whole-word replacement would
    break everywhere else."""
    return any(c.isupper() or c.isdigit() or c in "-.@" for w in words for c in w)


def _likeness(x, y):
    return difflib.SequenceMatcher(
        None, x.lower().replace(" ", ""), y.lower().replace(" ", "")).ratio()


def suggestions(pasted, field):
    """[(heard, typed)] word fixes the user made to `pasted`, which was
    typed into a field whose text is now `field`. Pure, for testing."""
    field = field or ""
    a = _WORD.findall(pasted or "")
    b_matches = list(_WORD.finditer(field))
    b = [m.group(0) for m in b_matches]
    if len(a) < 2 or not b:
        return []
    an, bn = [_norm(w) for w in a], [_norm(w) for w in b]
    # Where in the field the dictation is now: the stretch covering most
    # of its words in order. Each stretch the dictation is split into must
    # be found, or it's somewhere else (or gone).
    sm = difflib.SequenceMatcher(None, an, bn, autojunk=False)
    blocks = [m for m in sm.get_matching_blocks() if m.size]
    if not blocks:
        return []
    matched = sum(m.size for m in blocks)
    # Widened by as many words as the dictation has before its first match
    # and after its last, so a fix to its first or last word is in range.
    span_start = max(0, blocks[0].b - blocks[0].a)
    span_end = min(len(b), blocks[-1].b + blocks[-1].size
                   + len(a) - (blocks[-1].a + blocks[-1].size))
    if matched < 0.5 * len(a) or span_end - span_start > 2 * len(a) + 3:
        return []
    out = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(
            None, an, bn[span_start:span_end], autojunk=False).get_opcodes():
        old, new = a[i1:i2], b[span_start + j1:span_start + j2]
        if tag == "equal":
            # Case-only fixes: "priyanka" -> "Priyanka" -- but not a word
            # capitalized because the user started a new sentence there.
            for k, (x, y) in enumerate(zip(old, new)):
                pos = b_matches[span_start + j1 + k].start()
                starts_sentence = field[:pos].rstrip()[-1:] in ("", ".", "!", "?")
                if (x != y and x.lower() == y.lower() and y[:1].isupper()
                        and x[:1].islower() and _norm(x) not in _COMMON
                        and not starts_sentence):
                    out.append((x, y))
            continue
        if tag != "replace" or not (1 <= len(old) <= 3 and 1 <= len(new) <= 3):
            continue
        if all(_norm(w) in _COMMON for w in old) or all(_norm(w) in _COMMON for w in new):
            continue
        heard = " ".join(old)
        # The closest-sounding run of the new words: the widened span can
        # pull in a neighbouring word the user typed ("Hello Raghavendra"
        # for "Raga Vendra").
        likeness, typed = max(
            (_likeness(heard, " ".join(new[x:y])), " ".join(new[x:y]))
            for x in range(len(new)) for y in range(x + 1, len(new) + 1))
        if likeness >= 0.5 and _name_like([typed]):
            out.append((heard, typed))
    # A first word capitalized only because it now starts a sentence, or
    # the same pair twice in one dictation, count once.
    seen, result = set(), []
    for heard, typed in out:
        if (heard.lower(), typed) not in seen:
            seen.add((heard.lower(), typed))
            result.append((heard, typed))
    return result


def _clean(items):
    """Saved suggestion lists, minus anything malformed (settings.json can
    be hand-edited)."""
    return [d for d in items if isinstance(d, dict) and isinstance(d.get("heard"), str)
            and isinstance(d.get("typed"), str)]


def pending():
    """The current suggestions, for Settings."""
    return _clean(config.FIX_SUGGESTIONS)


def record(pairs):
    """Add new pairs to config.FIX_SUGGESTIONS (saved). Returns the pairs
    that are new: not already suggested, dismissed, or in the dictionary."""
    suggestions_now = _clean(config.FIX_SUGGESTIONS)
    known = {(s["heard"].lower(), s["typed"]) for s in suggestions_now}
    dismissed = {(d["heard"].lower(), d["typed"]) for d in _clean(config.FIX_DISMISSED)}
    in_dict = {(k.lower(), v) for k, v in config.DICTIONARY.items()}
    fresh = []
    for heard, typed in pairs:
        key = (heard.lower(), typed)
        if key in dismissed or key in in_dict:
            continue
        if key in known:
            for s in suggestions_now:
                if (s["heard"].lower(), s["typed"]) == key:
                    s["count"] = (s.get("count") if isinstance(s.get("count"), int) else 1) + 1
            continue
        suggestions_now.append({"heard": heard, "typed": typed, "count": 1})
        known.add(key)
        fresh.append((heard, typed))
    suggestions_now = suggestions_now[-_MAX_SUGGESTIONS:]
    if suggestions_now != config.FIX_SUGGESTIONS:
        config.FIX_SUGGESTIONS = suggestions_now
        settings.save({"fix_suggestions": suggestions_now})
    return fresh


def remove(heard, typed, dismiss=False):
    """Take a suggestion off the list (Settings' Add or Dismiss); a
    dismissed pair is remembered so it isn't suggested again."""
    config.FIX_SUGGESTIONS = [s for s in _clean(config.FIX_SUGGESTIONS)
                              if (s["heard"], s["typed"]) != (heard, typed)]
    values = {"fix_suggestions": config.FIX_SUGGESTIONS}
    if dismiss:
        config.FIX_DISMISSED = (_clean(config.FIX_DISMISSED)
                                + [{"heard": heard, "typed": typed}])[-200:]
        values["fix_dismissed"] = config.FIX_DISMISSED
    settings.save(values)


# ---------------------------------------------------------------- watching

def _read_field(control):
    """Full text of a field (TextPattern, else ValuePattern), or None."""
    import uiautomation as auto

    try:
        if control.IsPassword:
            return None
    except Exception:
        return None
    try:
        pattern = control.GetPattern(auto.PatternId.TextPattern)
        if pattern is not None:
            return pattern.DocumentRange.GetText(_MAX_FIELD_CHARS)
    except Exception:
        pass
    try:
        value = control.GetPattern(auto.PatternId.ValuePattern)
        if value is not None:
            return value.Value
    except Exception:
        pass
    return None


class _Watcher:
    def __init__(self):
        self._jobs = queue.Queue()
        self._watches = []  # [(control, pasted text, pasted at)]
        self.on_new = None  # callback(list of (heard, typed)), set by the app
        threading.Thread(target=self._run, daemon=True, name="fix-learning").start()

    def _run(self):
        import pythoncom
        import uiautomation as auto

        try:
            pythoncom.CoInitialize()
        except Exception:
            pass
        while True:
            job, text = self._jobs.get()
            try:
                if job == "watch":
                    control = auto.GetFocusedControl()
                    if control is not None:
                        self._watches = (self._watches + [(control, text, time.monotonic())])[-_MAX_WATCHES:]
                else:
                    self._check()
            except Exception:
                log.warning("checking for corrections failed", exc_info=True)

    def _check(self):
        now = time.monotonic()
        keep, found = [], []
        for control, pasted, at in self._watches:
            field = _read_field(control)
            pairs = suggestions(pasted, field) if field else []
            if pairs:
                found += pairs
            elif field is not None and now - at < CHECK_AFTER[-1] + 5:
                keep.append((control, pasted, at))
        self._watches = keep
        fresh = record(found) if found else []
        if fresh and self.on_new is not None:
            self.on_new(fresh)

    def watch(self, text):
        self._jobs.put(("watch", text))
        for delay in CHECK_AFTER:
            timer = threading.Timer(delay, self.check)
            timer.daemon = True
            timer.start()

    def check(self):
        if self._watches:
            self._jobs.put(("check", None))


_watcher = None


def watch(text, on_new=None):
    """Call right after `text` was pasted into the focused field."""
    global _watcher
    if not config.LEARN_FIXES or not text:
        return
    if _watcher is None:
        _watcher = _Watcher()
    if on_new is not None:
        _watcher.on_new = on_new
    _watcher.watch(text)


def check():
    """Look for corrections now (the hotkey went down: the user has moved
    on to the next dictation, so any fix to the last one is done)."""
    if _watcher is not None and config.LEARN_FIXES:
        _watcher.check()
