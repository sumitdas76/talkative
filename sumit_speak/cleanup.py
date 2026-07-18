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
_FIRST_LETTER = re.compile(r"([.!?]\s*|^\s*)([a-z])")
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
    # "Send, um, the file" / "Um, send it" / "send it, uh, today".
    pattern = re.compile(r"(?:,\s*)?\b(?:" + alternatives + r")\b[,.:;]?\s*", re.IGNORECASE)

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
    return SequenceMatcher(None, a, b).ratio() >= config.REPEAT_SIMILARITY


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
