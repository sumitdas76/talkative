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
from difflib import SequenceMatcher

from . import config

_SENTENCE_BOUNDARY = re.compile(r"[.!?]\s*")
_WHITESPACE_RUN = re.compile(r"[ \t]+")
_FIRST_LETTER = re.compile(r"([.!?]\s*|^\s*)([a-z])")
_WORD_TOKENS = re.compile(r"[a-z0-9']+")


def _word_similarity(a, b):
    wa, wb = _WORD_TOKENS.findall(a.lower()), _WORD_TOKENS.findall(b.lower())
    if not wa or not wb:
        return 0.0
    return SequenceMatcher(None, wa, wb).ratio()

_MAX_PASSES = 20


def _build_trigger_patterns(triggers):
    """Two patterns: strict (spaces between trigger words, matched anywhere)
    and loose (commas also allowed between words, e.g. "No, sorry"). The
    loose form is only trusted at the start of a sentence -- mid-sentence,
    "I said no, sorry, I was busy" is literal content, not a retraction, and
    no rule can tell the difference. Periods are never allowed between
    trigger words ("I said no. Sorry, ..." is not a retraction)."""
    phrases = sorted(triggers, key=len, reverse=True)
    strict = [re.escape(p).replace(r"\ ", r"\s+") for p in phrases]
    loose = [re.escape(p).replace(r"\ ", r"(?:,\s*|\s+)") for p in phrases]
    tail = r"\b[,.:;!]?\s*"
    return (
        re.compile(r"\b(?:" + "|".join(strict) + r")" + tail, re.IGNORECASE),
        re.compile(r"\b(?:" + "|".join(loose) + r")" + tail, re.IGNORECASE),
    )


def _find_trigger(strict_pattern, loose_pattern, text):
    strict_match = strict_pattern.search(text)
    loose_match = None
    for m in loose_pattern.finditer(text):
        before = text[: m.start()].strip()
        if not before or before[-1] in ".!?":
            loose_match = m
            break
        if strict_match is not None and m.start() > strict_match.start():
            break
    if strict_match is None:
        return loose_match
    if loose_match is None or strict_match.start() <= loose_match.start():
        return strict_match
    return loose_match


def _recapitalize(text):
    return _FIRST_LETTER.sub(lambda m: m.group(1) + m.group(2).upper(), text)


def apply_self_corrections(text, triggers=None):
    if not text:
        return text

    triggers = config.SELF_CORRECTION_TRIGGERS if triggers is None else triggers
    if not triggers:
        return text

    strict_pattern, loose_pattern = _build_trigger_patterns(triggers)

    result = text
    changed = False
    for _ in range(_MAX_PASSES):
        match = _find_trigger(strict_pattern, loose_pattern, result)
        if not match:
            break
        changed = True

        preceding = result[: match.start()]
        boundaries = list(_SENTENCE_BOUNDARY.finditer(preceding))
        cut = boundaries[-1].end() if boundaries else 0

        # A trigger that *starts* a sentence retracts into the previous
        # sentence ("... Monday, Sumit. No, sorry, send it Wednesday.").
        # How much of it? A retraction is a restatement, so retract the span
        # that resembles the correction: the whole previous sentence, or only
        # its last comma clause (Whisper often glues separate spoken
        # sentences with commas -- "Keep this line, drop this line."). Ties
        # go to the smaller span: delete less when unsure.
        if boundaries and not preceding[cut:].strip():
            prev_start = boundaries[-2].end() if len(boundaries) > 1 else 0
            prev_sentence = preceding[prev_start:cut]
            comma = prev_sentence.rstrip().rfind(",")
            if comma == -1:
                cut = prev_start
            else:
                correction = _SENTENCE_BOUNDARY.split(result[match.end():].lstrip())[0]
                whole_sim = _word_similarity(prev_sentence, correction)
                clause_sim = _word_similarity(prev_sentence[comma + 1 :], correction)
                cut = prev_start if whole_sim > clause_sim else prev_start + comma + 1

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
