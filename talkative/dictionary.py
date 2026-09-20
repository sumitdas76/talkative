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

# spoken_symbols.py fuses "underscore"/"hyphen"/"at sign"/slash words into
# these characters with no surrounding space, producing filenames, paths,
# identifiers, and email addresses ("settings_window.py", "c:\users\sumit",
# "john.smith@company.com"). A dictionary term that happens to also be a
# path/username component ("Sumit" -> "Sumit Chatterjee") must not expand
# when it's actually sitting inside one of these fused tokens -- confirmed
# live 2026-09-20: dictating a path containing the literal folder name
# matching a dictionary entry silently corrupted the path into a folder
# name that doesn't exist. "." is deliberately excluded from this set --
# it's also the normal, unavoidable character directly touching the last
# word of an ordinary sentence, so excluding on it would break the common
# case instead of the rare one.
_FUSION_CHARS = frozenset("\\/_-@")


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
        start, end = match.start(), match.end()
        before_char = text[start - 1] if start > 0 else ""
        after_char = text[end] if end < len(text) else ""
        if before_char in _FUSION_CHARS or after_char in _FUSION_CHARS:
            return matched
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
