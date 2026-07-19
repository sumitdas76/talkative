"""
Personal dictionary: spoken -> typed replacements.

Purely local, deterministic, rule-based -- no LLM or network call. Matches
whole words/phrases case-insensitively and preserves sentence-start
capitalization. The typed forms are also included in the match pattern
mapped to themselves, so an already-expanded phrase ("Sumit Chatterjee") is
matched whole and left alone instead of having its first word re-expanded
("Sumit Chatterjee Chatterjee").

Also builds a vocabulary hint prompt for the transcriber so dictionary terms
are more likely to be recognized correctly in the first place.
"""

import re

from . import config


def _normalize(phrase):
    return re.sub(r"\s+", " ", phrase.strip().lower())


def _build_pattern(spoken_forms):
    phrases = sorted(spoken_forms, key=len, reverse=True)
    alternatives = [re.escape(p).replace(r"\ ", r"\s+") for p in phrases]
    return re.compile(r"\b(?:" + "|".join(alternatives) + r")\b", re.IGNORECASE)


def apply_dictionary(text, entries=None):
    entries = config.DICTIONARY if entries is None else entries
    if not text or not entries:
        return text

    lookup = {}
    for _, typed in entries.items():
        lookup.setdefault(_normalize(typed), typed)
    for spoken, typed in entries.items():
        lookup[_normalize(spoken)] = typed

    pattern = _build_pattern(lookup.keys())

    def _replace(match):
        matched = match.group(0)
        typed = lookup[_normalize(matched)]
        # Capitalize only at an actual sentence start -- "the matched text
        # is uppercase" is the wrong signal (acronyms like "AI" are always
        # uppercase and must not capitalize a lowercase expansion
        # mid-sentence).
        before = text[: match.start()].rstrip()
        at_sentence_start = not before or before[-1] in ".!?"
        if at_sentence_start and typed[:1].islower():
            typed = typed[0].upper() + typed[1:]
        return typed

    return pattern.sub(_replace, text)


def vocabulary_prompt(entries=None):
    """A short prompt biasing Whisper toward the dictionary's vocabulary."""
    entries = config.DICTIONARY if entries is None else entries
    if not entries or not config.ENABLE_RECOGNITION_BIAS:
        return None
    terms = list(dict.fromkeys(list(entries.keys()) + list(entries.values())))
    return "Vocabulary: " + ", ".join(terms) + "."
