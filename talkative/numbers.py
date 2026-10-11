"""
Numbers as a careful writer would type them: digits or words, by context.

Whisper writes numbers inconsistently ("twenty five people", "2 kids",
"three thirty"), and the grammar pass is told to leave numbers exactly as
heard (its digit guard rejects any rewrite that changes them -- see
grammar_engine._digits_ok). This stage runs after grammar and decides the
written form with fixed rules, so Cloud and Local agree and nothing can
invent a number: every rewrite here is the same value, re-spelled.

The style (user request 2026-10-11, "intelligently understand when to
write in digits and when in words"), close to common English usage:
- digits: 10 and above, times ("at three thirty" -> "at 3:30", "five pm"),
  percentages ("25%"), money ("₹500", "$50", "₹5 lakh"), measurements
  ("5 GB"), dates ("October 5", "the 21st"), decimals ("3.5"), years
  ("twenty twenty six" after a month or "in"), spoken digit strings
  (phone numbers, OTPs: four or more single digits);
- words: one to nine as plain counts ("two kids", not "2 kids"), any
  number opening a sentence, and idioms ("one of", "a hundred times").

Pure, local, rule-based. Ambiguous cases are left as they were spoken.
"""

import re

_UNITS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
    "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
}
_TENS = {
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60,
    "seventy": 70, "eighty": 80, "ninety": 90,
}
_SCALES = {"hundred": 100, "thousand": 1000, "lakh": 100000, "lakhs": 100000,
           "crore": 10000000, "crores": 10000000, "million": 10 ** 6,
           "billion": 10 ** 9}
# Kept as words after the digits ("₹5 lakh"), the way they're written in India.
_WORD_SCALES = {"lakh", "lakhs", "crore", "crores", "million", "billion"}
_ORDINALS = {
    "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5,
    "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10,
    "eleventh": 11, "twelfth": 12, "thirteenth": 13, "fourteenth": 14,
    "fifteenth": 15, "sixteenth": 16, "seventeenth": 17,
    "eighteenth": 18, "nineteenth": 19, "twentieth": 20, "thirtieth": 30,
    "fortieth": 40, "fiftieth": 50, "sixtieth": 60, "seventieth": 70,
    "eightieth": 80, "ninetieth": 90, "hundredth": 100,
}
_DIGIT_WORDS = {"zero": "0", "oh": "0", "one": "1", "two": "2", "three": "3",
                "four": "4", "five": "5", "six": "6", "seven": "7",
                "eight": "8", "nine": "9", "double": None, "triple": None}

_MONTHS = {"January", "February", "March", "April", "May", "June", "July",
           "August", "September", "October", "November", "December"}
_PERCENT = {"percent", "per cent"}
_CURRENCY = {"rupees": "₹", "rupee": "₹", "rs": "₹", "dollars": "$",
             "dollar": "$", "euros": "€", "euro": "€", "pounds": "£"}
_UNIT_WORDS = {
    "gb", "mb", "kb", "tb", "gbps", "mbps", "kbps", "ghz", "mhz", "kg", "kgs",
    "km", "kms", "cm", "mm", "ml", "mg", "kilograms", "kilogram", "kilometers",
    "kilometres", "kilometer", "kilometre", "grams", "gram", "meters",
    "metres", "liters", "litres", "degrees", "celsius", "fahrenheit", "x",
    "inch", "inches", "feet", "pixels", "px", "rpm", "kmph", "mph",
}
# Words before a small number that make it a label or a time, not a count:
# "step 3", "version 2", "at 5", "room 4" keep their digits.
_KEEP_DIGIT_AFTER = {
    "page", "pages", "step", "steps", "room", "version", "chapter", "number",
    "no", "option", "options", "level", "phase", "grade", "class", "floor",
    "gate", "platform", "line", "item", "part", "section", "figure", "table",
    "episode", "season", "round", "day", "week", "slide", "slides", "point",
    "at", "by", "till", "until", "around", "before", "after", "from", "to",
    "and", "or", "of", "between", "sprint", "batch", "ward", "sector",
    "block", "unit", "tier", "rank", "q", "h", "p",
}
# Prepositions that make "three thirty" a time.
_TIME_BEFORE = {"at", "by", "till", "until", "around", "before", "after",
                "from", "since", "about", "to"}
# A time also shows from what follows it ("three thirty on Friday",
# "four fifteen tomorrow").
_TIME_AFTER = {"on", "today", "tomorrow", "tonight", "this", "sharp",
               "monday", "tuesday", "wednesday", "thursday", "friday",
               "saturday", "sunday"}
_YEAR_BEFORE = {"in", "since", "by", "year", "of", "until", "till", "from",
                "before", "after"}

_TOKEN = re.compile(r"[A-Za-z]+|\d+(?:[.,:]\d+)*|\s+|.", re.UNICODE)


# Whisper writes a lone spoken "point one" as ".1" ("I cannot do .1",
# seen live 2026-10-11), and the grammar pass then makes it "0.1". A real
# decimal is spoken "zero point one" and comes out "0.1", so a bare ".N"
# after a word is turned back into "point N" -- unless a unit or percent
# follows, or a word that introduces a quantity comes before it.
_BARE_POINT = re.compile(
    r"(?<![\w.])(?P<prev>[A-Za-z]+,?\s+|(?<=[.!?:]\s)|^)\.(?P<n>\d{1,2})\b"
    r"(?!\s*(?:%|(?:percent|per|times|x|seconds?|secs?|minutes?|mins?"
    r"|hours?|hrs?|days?|weeks?|months?|years?|ms|mm|cm|km|kg|g|m|s|gb|mb|kb"
    r"|tb|ghz|mhz|inch(?:es)?|feet|foot|miles?|litres?|liters?|points|stars?"
    r"|lakhs?|crores?|million|billion|k)\b))",
)
_QUANTITY_BEFORE = {"by", "to", "of", "is", "was", "at", "about", "around",
                    "minus", "plus", "equals", "version", "v", "from",
                    "than", "only", "just", "under", "over", "approximately",
                    "roughly", "nearly", "almost", "be", "are", "were"}


def restore_spoken_point(text):
    def fix(m):
        prev = m.group("prev").strip(" ,").lower()
        if prev in _QUANTITY_BEFORE:
            return m.group(0)
        word = "Point" if not prev else "point"
        return f"{m.group('prev')}{word} {m.group('n')}"
    return _BARE_POINT.sub(fix, text) if text and "." in text else text


def _lower(tok):
    return tok.lower() if tok else ""


def _is_word(tok):
    return bool(tok) and tok[0].isalpha()


def _parse_cardinal(words):
    """Longest prefix of `words` (lowercase) that reads as one number.
    Returns (value, count consumed, largest scale word or None) or None."""
    total = current = 0
    used = 0
    last_kind = None  # unit | teen | tens | scale | and
    scale_word = None
    for i, w in enumerate(words):
        if w == "and":
            # Only "hundred and twenty", "thousand and five".
            if last_kind != "scale" or i + 1 >= len(words) or (
                    words[i + 1] not in _UNITS and words[i + 1] not in _TENS):
                break
            last_kind = "and"
            continue
        if w in _UNITS:
            v = _UNITS[w]
            if last_kind in ("unit", "teen") or (last_kind == "tens" and v >= 10):
                break
            if last_kind == "tens" and v == 0:
                break
            current += v
            last_kind = "teen" if v >= 10 else "unit"
        elif w in _TENS:
            if last_kind in ("unit", "teen", "tens"):
                break
            current += _TENS[w]
            last_kind = "tens"
        elif w in _SCALES:
            if last_kind in (None, "and"):
                break
            scale = _SCALES[w]
            if scale == 100:
                if current == 0 or current % 100 != current:
                    break
                current *= 100
            else:
                if current == 0:
                    break
                total += current * scale
                current = 0
            last_kind = "scale"
            # The largest scale names the number ("one crore twenty lakh"
            # is crores, not lakhs).
            if scale_word is None or scale > _SCALES[scale_word]:
                scale_word = w
        else:
            break
        used = i + 1
    if used == 0:
        return None
    if words[used - 1] == "and":
        used -= 1
    return total + current, used, scale_word


def _group(n):
    return f"{n:,}" if n >= 10000 else str(n)


def _ordinal_suffix(n):
    if 10 <= n % 100 <= 20:
        return "th"
    return {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")


class _Words:
    """The token list with word positions, so rules can look at the words
    around a number regardless of the spaces and punctuation between."""

    def __init__(self, text):
        self.toks = _TOKEN.findall(text)

    def next_word(self, i, gap_ok=(" ",)):
        """Index of the next token that's a word, if only allowed separators
        come between; else None."""
        j = i + 1
        while j < len(self.toks) and not _is_word(self.toks[j]) and not self.toks[j][0].isdigit():
            if self.toks[j] not in gap_ok and not self.toks[j].isspace():
                return None
            j += 1
        return j if j < len(self.toks) else None

    def prev_word(self, i):
        j = i - 1
        while j >= 0 and self.toks[j].isspace():
            j -= 1
        return j if j >= 0 and (_is_word(self.toks[j]) or self.toks[j][0].isdigit()) else None

    def sentence_start(self, i):
        j = i - 1
        while j >= 0 and self.toks[j].isspace():
            j -= 1
        return j < 0 or self.toks[j] in (".", "!", "?", "\n", ":")


def _span(w, i):
    """Collect number-ish words from token i on, joined by spaces or
    hyphens. Returns (lowercase words, token index after each word)."""
    words, ends = [], []
    j = i
    vocab = set(_UNITS) | set(_TENS) | set(_SCALES) | {"and"} | set(_ORDINALS)
    while j is not None and j < len(w.toks) and _lower(w.toks[j]) in vocab:
        words.append(_lower(w.toks[j]))
        ends.append(j + 1)
        if _lower(w.toks[j]) in _ORDINALS:
            break
        j = w.next_word(j, gap_ok=(" ", "-"))
    return words, ends


def format_numbers(text):
    if not text or not re.search(r"[A-Za-z0-9]", text):
        return text
    w = _Words(text)
    out = []
    i = 0
    toks = w.toks
    while i < len(toks):
        tok = toks[i]
        low = _lower(tok)
        if _is_word(tok) and (low in _UNITS or low in _TENS or low in _ORDINALS
                              or low == "oh"):
            done = _convert_words(w, i, out)
            if done is not None:
                i = done
                continue
        if tok.isdigit():
            done = _small_digit_to_word(w, i, out)
            if done is not None:
                i = done
                continue
        out.append(tok)
        i += 1
    return "".join(out)


_AMPM_AHEAD = re.compile(r"\s*([ap])\.?\s?m\b\.?", re.IGNORECASE)


def _ampm_after(w, end):
    """True when "am"/"pm" ("p.m.", "PM", "p m") follows token `end`."""
    return bool(_AMPM_AHEAD.match("".join(w.toks[end:end + 6])))


def _word_after(w, end):
    j = w.next_word(end - 1)
    return (j, w.toks[j]) if j is not None else (None, "")


def _convert_words(w, i, out):
    """Rewrite the number-word phrase starting at token i, appending to out.
    Returns the token index to continue from, or None to leave it alone."""
    toks = w.toks
    prev_i = w.prev_word(i)
    prev = toks[prev_i] if prev_i is not None else ""
    prev_low = _lower(prev)
    at_start = w.sentence_start(i)

    # Spoken digit strings: phone numbers, OTPs, PINs ("nine eight one
    # oh ..."): four or more single digits in a row.
    digits, j, last = [], i, i
    while j is not None and j < len(toks) and _lower(toks[j]) in _DIGIT_WORDS \
            and _DIGIT_WORDS[_lower(toks[j])] is not None:
        digits.append(_DIGIT_WORDS[_lower(toks[j])])
        last = j
        j = w.next_word(j, gap_ok=(" ", "-", ","))
    if len(digits) >= 4:
        out.append("".join(digits))
        return last + 1
    if _lower(toks[i]) == "oh":
        return None

    words, ends = _span(w, i)
    if not words:
        return None

    # Ordinals: "twenty fifth" -> "25th"; "fifth" alone stays a word unless
    # it's a date ("October fifth", "fifth of October", "the 5th").
    if words[-1] in _ORDINALS:
        base = words[:-1]
        if base:
            parsed = _parse_cardinal(base)
            if parsed is None or parsed[1] != len(base):
                return None
            value = parsed[0] + _ORDINALS[words[-1]]
        else:
            value = _ORDINALS[words[-1]]
        end = ends[-1]
        nj, nxt = _word_after(w, end)
        after_month = prev in _MONTHS
        before_month = nxt in _MONTHS or (
            _lower(nxt) == "of" and nj is not None
            and (w.next_word(nj) is not None and toks[w.next_word(nj)] in _MONTHS))
        if after_month:
            out.append(str(value))
            return end
        if value >= 10 or before_month:
            out.append(f"{value}{_ordinal_suffix(value)}")
            return end
        return None

    parsed = _parse_cardinal(words)
    if parsed is None:
        return None
    value, used, scale_word = parsed
    end = ends[used - 1]
    nj, nxt = _word_after(w, end)
    nxt_low = _lower(nxt)

    # A second number right after: a time ("at three thirty") or a year
    # ("in twenty twenty six").
    if nxt and (nxt_low in _UNITS or nxt_low in _TENS or nxt_low == "oh"):
        words2, ends2 = _span(w, nj)
        minute_words = words2
        oh = False
        if nxt_low == "oh" and len(toks) > nj:
            oh = True
            nj2 = w.next_word(nj)
            words2, ends2 = _span(w, nj2) if nj2 is not None else ([], [])
            minute_words = words2
        p2 = _parse_cardinal(minute_words) if minute_words else None
        if p2 is not None and not scale_word:
            v2, used2, sc2 = p2
            end2 = ends2[used2 - 1]
            aj, after = _word_after(w, end2)
            is_ampm = _ampm_after(w, end2)
            if (1 <= value <= 12 and (oh and v2 < 10 or 10 <= v2 <= 59) and not sc2
                    and (prev_low in _TIME_BEFORE or is_ampm
                         or _lower(after) in ("o'clock", "oclock")
                         or _lower(after) in _TIME_AFTER)):
                out.append(f"{value}:{v2:02d}")
                return end2
            if (10 <= value <= 20 and 0 <= v2 <= 99 and not sc2 and not oh
                    and used2 == len(minute_words[:used2])
                    and (prev_low in _YEAR_BEFORE or prev in _MONTHS)):
                out.append(f"{value}{v2:02d}")
                return end2
            if not scale_word:
                # Two numbers side by side that aren't a time or a year:
                # leave both as spoken. Converting only the second one
                # gave "three 30".
                out.extend(w.toks[i:end2])
                return end2
        if not scale_word and value < 10:
            return None  # "one two three", "two three people": leave it

    # Decimals: "three point five".
    if nxt_low == "point" and nj is not None:
        dj = w.next_word(nj)
        frac, last = [], None
        while dj is not None and _lower(toks[dj]) in _DIGIT_WORDS \
                and _DIGIT_WORDS[_lower(toks[dj])] is not None:
            frac.append(_DIGIT_WORDS[_lower(toks[dj])])
            last = dj
            dj = w.next_word(dj)
        if frac and not scale_word:
            out.append(f"{value}.{''.join(frac)}")
            end = last + 1
            nj, nxt = _word_after(w, end)
            return _with_unit(w, end, nj, nxt, out) or end

    shown = _digits_for(value, scale_word)

    if _lower(nxt) in _CURRENCY and nj is not None:
        out.append(_CURRENCY[_lower(nxt)] + shown)
        return nj + 1
    if nxt_low == "percent" or (nxt_low == "per" and nj is not None
                                and _lower(w.toks[w.next_word(nj) or nj]) == "cent"):
        out.append(shown + "%")
        return (nj + 1) if nxt_low == "percent" else w.next_word(nj) + 1
    if nxt_low in _UNIT_WORDS or prev in _MONTHS or nxt in _MONTHS:
        out.append(shown)
        return end
    if _ampm_after(w, end) and 1 <= value <= 12:
        out.append(str(value))
        return end
    if at_start:
        return None
    if value >= 10:
        out.append(shown)
        return end
    return None


def _with_unit(w, end, nj, nxt, out):
    """After a decimal: fold "percent" into "%"."""
    if _lower(nxt) == "percent":
        out[-1] += "%"
        return nj + 1
    return None


def _indian_group(n):
    """2,37,500: the last three digits, then pairs."""
    s = str(n)
    if len(s) <= 3:
        return s
    head, tail = s[:-3], s[-3:]
    pairs = []
    while len(head) > 2:
        pairs.insert(0, head[-2:])
        head = head[:-2]
    return ",".join([head] + pairs + [tail])


def _digits_for(value, scale_word):
    if scale_word in _WORD_SCALES:
        base = value / _SCALES[scale_word]
        if base == int(base):
            return f"{int(base)} {scale_word}"
        # "two lakh fifty thousand" -> "2.5 lakh" (an Indian writer's form;
        # "250,000" is Western grouping nobody in India would type).
        if scale_word in ("lakh", "lakhs", "crore", "crores"):
            if round(base, 2) == base:
                return f"{base:g} {scale_word}"
            return _indian_group(value)
    return _group(value)


_SMALL = ["zero", "one", "two", "three", "four", "five", "six", "seven",
          "eight", "nine"]


def _small_digit_to_word(w, i, out):
    """"2 kids" -> "two kids": a bare 1-9 used as a count, mid-sentence,
    followed by an ordinary word, with no other digit number in the same
    sentence (then digits stay, for consistency: "2 of the 15")."""
    toks = w.toks
    value = int(toks[i])
    if not 1 <= value <= 9:
        return None
    if w.sentence_start(i):
        return None
    if i + 1 >= len(toks) or toks[i + 1] != " ":
        return None  # "3:30", "2.5", "3%", "5," ...
    nj = w.next_word(i)
    if nj is None or not _is_word(toks[nj]):
        return None
    nxt = toks[nj]
    if (_lower(nxt) in _UNIT_WORDS or _lower(nxt) in _CURRENCY
            or _lower(nxt) in ("percent", "o'clock", "oclock", "and", "or", "to")
            or _ampm_after(w, i + 1) or nxt in _MONTHS or nxt.isupper()):
        return None
    pj = w.prev_word(i)
    if pj is not None and (_lower(toks[pj]) in _KEEP_DIGIT_AFTER or toks[pj] in _MONTHS
                           or toks[pj][0].isdigit() or toks[pj] in _CURRENCY.values()):
        return None
    if i > 0 and toks[i - 1] in ("$", "₹", "€", "£", "#", "-", "/", "."):
        return None
    # Another digit number in the same sentence keeps this one in digits.
    lo = i
    while lo > 0 and toks[lo - 1] not in (".", "!", "?", "\n"):
        lo -= 1
    hi = i + 1
    while hi < len(toks) and toks[hi] not in (".", "!", "?", "\n"):
        hi += 1
    if any(t[0].isdigit() for k, t in enumerate(toks[lo:hi], lo) if k != i):
        return None
    out.append(_SMALL[value])
    return i + 1
