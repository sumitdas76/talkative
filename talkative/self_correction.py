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

# A "." immediately followed by a word character (no space) is never a real
# sentence end -- it's a fused identifier/URL/decimal ("settings_window.py",
# "company.com", "2.3.1") that spoken_symbols.py or Whisper's own number
# formatting produced, not a spoken pause. Without the (?!\w) guard, a
# retraction trigger appearing anywhere later in the same dictation counts
# these fused periods as extra sentence boundaries, scrambling the
# retraction-span cut point and mangling real content that has nothing to
# do with the correction (confirmed live 2026-09-20: an email address
# elsewhere in the text got truncated and re-capitalized mid-domain by a
# "scratch that" retraction several words later). "!"/"?" are never fused
# this way, so they don't need the guard.
_SENTENCE_BOUNDARY = re.compile(r"(?:\.(?!\w)|[!?])\s*")
_WHITESPACE_RUN = re.compile(r"[ \t]+")
_FIRST_LETTER = re.compile(r"((?:\.(?!\w)|[!?])\s*|^\s*)([a-z])")
_WORD_TOKENS = re.compile(r"[a-z0-9']+")


def _word_similarity(a, b):
    wa, wb = _WORD_TOKENS.findall(a.lower()), _WORD_TOKENS.findall(b.lower())
    if not wa or not wb:
        return 0.0
    return SequenceMatcher(None, wa, wb).ratio()

_MAX_PASSES = 20

# Safety cap on a whole-span retraction (no comma present to sub-scope it to
# just the last clause). A span this long with zero interior punctuation
# almost never means "one genuine run-on sentence" -- it means the upstream
# transcript is missing sentence-ending punctuation for several real
# sentences in a row (confirmed live 2026-09-20, twice: first a Cloud
# transcript that dropped periods across ~10 consecutive sentences, where a
# "let me say that again" trigger retracted everything back to the start of
# that run, deleting five unrelated sentences; then a second, shorter case
# that slipped past an initial 30-word version of this cap -- four short,
# unrelated command sentences ("open settings", "check email", "reply to
# jake", "close this window") fused with no punctuation summed to only 14
# words and still got deleted whole by an unrelated "no wait"). Every
# legitimate whole-span retraction actually exercised in testing tops out
# around 6 words, so the cap is set low and conservative on purpose: when a
# span this large has no comma to narrow it down, leave it alone rather than
# guess -- the trigger phrase stays as literal text, which is a far smaller
# failure than deleting real content the speaker never asked to retract.
_MAX_RETRACTION_SPAN_WORDS = 12


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


def _find_trigger(strict_pattern, loose_pattern, text, start=0):
    strict_match = strict_pattern.search(text, start)
    loose_match = None
    for m in loose_pattern.finditer(text, start):
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
    search_from = 0
    for _ in range(_MAX_PASSES):
        match = _find_trigger(strict_pattern, loose_pattern, result, search_from)
        if not match:
            break

        preceding = result[: match.start()]
        boundaries = list(_SENTENCE_BOUNDARY.finditer(preceding))
        cut = boundaries[-1].end() if boundaries else 0
        correction = _SENTENCE_BOUNDARY.split(result[match.end() :].lstrip())[0]

        # A trigger that *starts* a sentence retracts into the previous
        # sentence instead -- Whisper often puts a period right before the
        # retraction ("... Monday, Sumit. No, sorry, ...").
        if boundaries and not preceding[cut:].strip():
            cut = boundaries[-2].end() if len(boundaries) > 1 else 0

        # How much of the span gets retracted? Whisper glues separate spoken
        # sentences with commas ("Keep this line, drop this line, no sorry
        # use this one."), so retract the part that resembles the correction
        # (a retraction is a restatement): the whole span, or only its last
        # comma clause. Ties go to the clause -- delete less when unsure.
        span = preceding[cut:].rstrip().rstrip(",.;:!? ")
        comma = span.rfind(",")
        if comma != -1:
            whole_sim = _word_similarity(span, correction)
            clause_sim = _word_similarity(span[comma + 1 :], correction)
            if clause_sim >= whole_sim:
                cut = cut + comma + 1

        # Safety cap on whatever is actually about to be deleted, whichever
        # path produced it. A comma being present doesn't make a long
        # whole-span retraction safe -- the whole/clause comparison above
        # can still pick "whole span" over "just the last clause" (confirmed
        # live 2026-09-20: "Yo, so I was waiting on line at the deli on
        # Flatbush Avenue, and the guy hands me a regular coffee, no wait, I
        # ordered it black..." deleted the entire 21-word scene-setting
        # clause even though a comma was present, because it scored more
        # similar to the correction than just the last clause did). Capping
        # only the no-comma case (as an earlier version of this guard did)
        # missed this -- what matters is how much text is about to vanish,
        # not whether a comma happened to be nearby.
        if len(preceding[cut:].split()) > _MAX_RETRACTION_SPAN_WORDS:
            search_from = match.end()
            continue

        changed = True
        kept_prefix = preceding[:cut].rstrip()
        remainder = result[match.end() :].lstrip()

        if kept_prefix and remainder:
            result = kept_prefix + " " + remainder
        else:
            result = kept_prefix or remainder
        search_from = 0

    if not changed:
        return text

    result = _WHITESPACE_RUN.sub(" ", result).strip()
    return _recapitalize(result)
