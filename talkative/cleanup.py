"""
Rule-based transcript cleanup for "cleaned_up" mode.

Purely local, deterministic, rule-based -- no LLM or network call. Two
stages: filler-word removal and conservative near-repeat sentence collapsing
(the speaker said the same thing twice, keep the last version). Everything
here is biased conservative: wrongly deleting intended words is the worst
failure a dictation tool can have, so anything ambiguous is left alone.
"""

import re
from difflib import SequenceMatcher

from . import config

_WHITESPACE_RUN = re.compile(r"[ \t]+")
# A "." immediately followed by a word character (no space) is never a real
# sentence end -- it's a fused identifier/URL/decimal ("settings_window.py",
# "company.com", "2.3.1") that spoken_symbols.py or Whisper's own number
# formatting produced. Only "!"/"?" always end a sentence; a bare "." needs
# the (?!\w) guard so recapitalizing after one doesn't mangle the character
# right after a fused period (e.g. ".py" -> ".Py").
_FIRST_LETTER = re.compile(r"((?:\.(?!\w)|[!?])\s*|^\s*)([a-z])")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
_WORDS = re.compile(r"[a-z0-9']+")


def _recapitalize(text):
    return _FIRST_LETTER.sub(lambda m: m.group(1) + m.group(2).upper(), text)


def remove_fillers(text, fillers=None):
    fillers = config.FILLER_WORDS if fillers is None else fillers
    if not text or not fillers:
        return text

    alternatives = "|".join(re.escape(f) for f in sorted(fillers, key=len, reverse=True))
    # The filler plus whatever punctuation glues it into the sentence:
    # "Send, um, the file" / "Um, send it" / "send it, uh, today". Only
    # ,/:/; are treated as glue to consume -- a trailing .!? is a sentence
    # terminator, not glue, and must survive so downstream stages that split
    # on it (self_correction.py, collapse_repeats() below) don't see two
    # sentences silently fused into a run-on. (?!-) keeps a filler prefix
    # that's actually part of a real hyphenated word ("uh-huh", "um-hmm")
    # from being chopped down to "-huh"/"-hmm".
    pattern = re.compile(
        r"(?:,\s*)?\b(?:" + alternatives + r")\b(?!-)(?:[,:;]\s*|(?=[.!?])|\s+|$)",
        re.IGNORECASE,
    )

    cleaned = pattern.sub(" ", text)
    if cleaned == text:
        return text

    cleaned = _WHITESPACE_RUN.sub(" ", cleaned)
    cleaned = re.sub(r"\s+([,.!?;:])", r"\1", cleaned)
    cleaned = re.sub(r"^[,.;:\s]+", "", cleaned).strip()
    return _recapitalize(cleaned)


def _content_words(sentence):
    return _WORDS.findall(sentence.lower())


def _is_restatement(prev, curr):
    # Word-level comparison: character-level ratios score a true restatement
    # ("send the file today" / "send the file by this evening") and two
    # intentional sentences ("I love this plan" / "I love this idea even
    # more") almost identically, so no threshold separates them. Word tokens
    # separate tight repeats (collapse) from loose rephrasings (leave for a
    # smarter cleanup stage).
    a, b = _content_words(prev), _content_words(curr)
    if not a or not b or a[0] != b[0]:
        return False
    if SequenceMatcher(None, a, b).ratio() < config.REPEAT_SIMILARITY:
        return False
    # A difference sandwiched between a shared prefix AND a shared suffix
    # ("we need three PEOPLE for this" / "we need three CHAIRS for this")
    # reads as two different intentional statements, not a restatement --
    # a spoken restatement corrects the tail end of what was being said
    # ("meet tomorrow" -> "meet Friday"), it doesn't swap out one word in
    # the middle while repeating everything after it unchanged. Require the
    # differing span to extend through the end of at least one sentence.
    prefix = 0
    while prefix < len(a) and prefix < len(b) and a[prefix] == b[prefix]:
        prefix += 1
    suffix = 0
    while (suffix < len(a) - prefix and suffix < len(b) - prefix
           and a[len(a) - 1 - suffix] == b[len(b) - 1 - suffix]):
        suffix += 1
    if suffix > 0 and prefix + suffix < min(len(a), len(b)):
        return False
    return True


def collapse_repeats(text):
    if not text or not config.ENABLE_REPEAT_COLLAPSE:
        return text

    sentences = _SENTENCE_SPLIT.split(text.strip())
    if len(sentences) < 2:
        return text

    kept = [sentences[0]]
    for sentence in sentences[1:]:
        if _is_restatement(kept[-1], sentence):
            kept[-1] = sentence  # the restatement wins
        else:
            kept.append(sentence)

    if len(kept) == len(sentences):
        return text
    return " ".join(kept)


def finish_sentence(text):
    """Minimal finishing touches for cleaned_up mode: capitalize the first
    letter and add a terminal period when the dictation ends mid-word style
    (Whisper omits both on long spontaneous speech). Never touches interior
    punctuation -- restructuring is the future grammar engine's job."""
    if not text:
        return text
    text = text.strip()
    if text[:1].islower():
        text = text[0].upper() + text[1:]
    if text[-1:].isalnum() or text[-1:] == "%":
        text += "."
    elif text[-1:] in ",;:":
        text = text[:-1] + "."
    return text
