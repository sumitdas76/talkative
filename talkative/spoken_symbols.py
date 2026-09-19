"""
Spoken symbol names -> literal characters.

Whisper transcribes spoken symbol words ("underscore", "dot", "at sign")
as literal text rather than the character they name, so dictating a
filename or identifier like "settings underscore window dot py" comes out
as exactly that instead of "settings_window.py". Pure, local, rule-based
(no LLM, no network) -- this is a small fixed vocabulary, not something
that needs a model.

Runs on every dictation regardless of cleanup mode (this is a raw-
transcription-fidelity fix, not a style choice), and runs first, before
fillers/self-correction/the grammar engine, so those stages see the
already-fused "settings_window.py" rather than the literal word
"underscore" -- among other things, this avoids confusing the grammar
engine's word-retention guard, which would otherwise expect to see
"underscore" survive verbatim.

"dot" is deliberately included even though it's an ordinary English word
in other contexts ("there's a dot on the map"): a literal "dot" token in
a Whisper transcript almost always means the user said the word on
purpose to spell out a symbol -- natural end-of-sentence pauses come out
as "." directly, not as the word "period" or "dot". Some false-positive
risk is accepted here, the same tradeoff this app already makes elsewhere
(self_correction.py, cleanup.py) between imperfect heuristics and a much
more common failure to fix.
"""

import re

from . import config

# Longest phrases first so "forward slash" matches before a hypothetical
# shorter overlapping entry.
_SYMBOLS = [
    ("forward slash", "/"),
    ("back slash", "\\"),
    ("backslash", "\\"),
    ("underscore", "_"),
    ("hyphen", "-"),
    ("at sign", "@"),
    ("at symbol", "@"),
    ("dot", "."),
]


def _build_pattern():
    phrases = sorted(_SYMBOLS, key=lambda kv: len(kv[0]), reverse=True)
    alternatives = "|".join(
        re.escape(phrase).replace(r"\ ", r"\s+") for phrase, _ in phrases
    )
    lookup = {phrase.lower(): symbol for phrase, symbol in phrases}
    return re.compile(r"\s*\b(?:" + alternatives + r")\b\s*", re.IGNORECASE), lookup


_PATTERN, _LOOKUP = _build_pattern()


def apply_spoken_symbols(text):
    """Convert spoken symbol names into their literal character, fusing
    them with the surrounding words the way a typed identifier/filename/
    URL would read."""
    if not text or not config.ENABLE_SPOKEN_SYMBOLS:
        return text

    def _replace(match):
        phrase = re.sub(r"\s+", " ", match.group(0).strip()).lower()
        return _LOOKUP[phrase]

    return _PATTERN.sub(_replace, text)
