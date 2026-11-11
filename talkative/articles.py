"""a/an before the next word's sound ("a empty" -> "an empty").

Local mode with the grammar model off (the default since 1.3.23) has
nothing else that fixes this, and Whisper writes what it hears: a quick
"an" often comes out as "a". Pure rules, no model.

Conservative on purpose: wrongly changing a correct word is worse than
leaving a slip. Only lowercase "a"/"an" followed by one space and a
lowercase word are touched, so letters ("plan A", "option a, b") and
sentence-start "A" (often a spoken letter bullet) are left alone. Words
whose first letter doesn't say how they sound are only changed when
listed below; anything unlisted that starts with "u", "h", "x" or "y"
is left as it is.
"""
import re

# Start with a vowel letter but sound like a consonant: "a user", "a one".
_CONSONANT_SOUND = re.compile(
    r"(?:uni(?:que|corn|on|t|ted|verse|versal|versit|form|son|fy|fied|fication|lateral|code|x)"
    r"|use|usa|usu|uti|ura|ure|uri|uro|eu|ewe|one\b|once|ouija)"
)
# Start with "h" but sound like a vowel: "an hour".
_SILENT_H = re.compile(r"(?:hour|honest|honor|honour|heir)")
# Start with "u" and sound like a vowel: "an umbrella", "an update".
_VOWEL_U = re.compile(r"(?:un(?!i)|up|ug|ul|umb|ump|ut(?:most|ter)|us\b)")

# "a" here is a letter, not an article: "option a and", "vitamin a in".
_LETTER_BEFORE = {
    "option", "plan", "point", "part", "section", "grade", "type", "vitamin",
    "class", "row", "column", "step", "item", "case", "letter", "list",
    "category", "group", "level", "phase", "version", "model", "block",
    "team", "line", "page", "figure", "table", "appendix", "schedule",
}

_ARTICLE = re.compile(r"(?<![\w'\-.])(a|an) ([a-z][a-z'\-]*)")


def _wants_an(word):
    """True/False when the word's sound is clear, None when it isn't."""
    if _CONSONANT_SOUND.match(word):
        return False
    if _SILENT_H.match(word):
        return True
    if not re.search(r"[aeiou]", word):
        return None  # "an npm", "an ssh key": letters read out one by one
    first = word[0]
    if first == "u":
        return True if _VOWEL_U.match(word) else None
    if first in "aeio":
        return True
    if first in "hxy":
        # "an historic" (British), "an x-ray", "a yttrium": not ours to judge.
        return None
    return False


def fix_articles(text):
    """Return `text` with "a"/"an" matched to the next word's sound."""

    def repl(m):
        article, word = m.group(1), m.group(2)
        if len(word) < 2:
            return m.group(0)  # "a b c", "an x": letters, not words
        before = text[: m.start()].rstrip().rsplit(None, 1)
        if before and before[-1].lower().strip(",:;") in _LETTER_BEFORE:
            return m.group(0)
        want = _wants_an(word)
        if want is None:
            return m.group(0)
        right = "an" if want else "a"
        return m.group(0) if right == article else f"{right} {word}"

    return _ARTICLE.sub(repl, text)
