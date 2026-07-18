"""
Detect spoken self-corrections and drop the retracted part.

Whisper transcribes verbatim, so a misspoken-then-corrected utterance like
"Send it tomorrow, no wait, send it on Friday." comes out with both the
mistake and the correction. This is a purely local, deterministic, rule-based
cleanup -- no LLM or network call -- that discards everything since the last
sentence boundary (or the start of the text) up to a trigger phrase, keeping
only what follows.
"""

import re

from . import config

_SENTENCE_BOUNDARY = re.compile(r"[.!?]\s*")
_WHITESPACE_RUN = re.compile(r"[ \t]+")
_FIRST_LETTER = re.compile(r"([.!?]\s*|^\s*)([a-z])")

_MAX_PASSES = 20


def _build_trigger_pattern(triggers):
    phrases = sorted(triggers, key=len, reverse=True)
    # Words inside a trigger may be separated by a comma as well as spaces:
    # Whisper punctuates freely, so "no sorry" must also match "No, sorry".
    # Periods are deliberately NOT allowed between trigger words -- "I said
    # no. Sorry, I was busy." is not a retraction.
    alternatives = [re.escape(p).replace(r"\ ", r"(?:,\s*|\s+)") for p in phrases]
    return re.compile(r"\b(?:" + "|".join(alternatives) + r")\b[,.:;!]?\s*", re.IGNORECASE)


def _recapitalize(text):
    return _FIRST_LETTER.sub(lambda m: m.group(1) + m.group(2).upper(), text)


def apply_self_corrections(text, triggers=None):
    if not text:
        return text

    triggers = config.SELF_CORRECTION_TRIGGERS if triggers is None else triggers
    if not triggers:
        return text

    pattern = _build_trigger_pattern(triggers)

    result = text
    changed = False
    for _ in range(_MAX_PASSES):
        match = pattern.search(result)
        if not match:
            break
        changed = True

        preceding = result[: match.start()]
        boundaries = list(_SENTENCE_BOUNDARY.finditer(preceding))
        cut = boundaries[-1].end() if boundaries else 0

        # A trigger that *starts* a sentence retracts the previous sentence:
        # "Send it on Monday, Sumit. No, sorry, send it on Wednesday." -- the
        # retracted content sits before the boundary Whisper inserted, so
        # reach back one sentence further.
        if boundaries and not preceding[cut:].strip():
            cut = boundaries[-2].end() if len(boundaries) > 1 else 0

        kept_prefix = preceding[:cut].rstrip()
        remainder = result[match.end() :].lstrip()

        if kept_prefix and remainder:
            result = kept_prefix + " " + remainder
        else:
            result = kept_prefix or remainder

    if not changed:
        return text

    result = _WHITESPACE_RUN.sub(" ", result).strip()
    return _recapitalize(result)
