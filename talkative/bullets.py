"""
Spoken points typed as bullets.

"We need three things. First, book the hall. Second, send the invites.
Third, order the food." becomes

    We need three things:
    • Book the hall
    • Send the invites
    • Order the food

User request 2026-10-11. Pure, local, rule-based, like the rest of the
cleanup. A list needs at least two markers counting up from one with no
gaps ("first ... second ...", "firstly ... secondly ...", "point one ...
point two ...", "number one ... number two ..."; "finally"/"lastly" may
close it), and every marker must open a clause -- start of the text,
after . ! ? : ; or a comma, optionally followed by "and". That keeps
"the first time ... a second chance" and "wait a second" as prose.
Anything that doesn't qualify is returned unchanged.
"""

import re

_ORDINAL = {
    "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5,
    "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10,
}
_LY = {"firstly": 1, "secondly": 2, "thirdly": 3, "fourthly": 4,
       "fifthly": 5}
_CARDINAL = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
             "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}
_CLOSERS = ("finally", "lastly")

BULLET = "• "

# A marker at a clause start. Group "lead" is the boundary before it, kept
# with the text in front; the marker itself and its comma are dropped.
_MARKER = re.compile(
    r"(?P<lead>^|[.!?:;,]\s*|\n\s*)(?:and\s+)?"
    r"(?P<marker>first\s+of\s+all|(?:point|number|step)\s+(?:[a-z]+|\d+)"
    r"|[a-z]+)"
    r"(?P<comma>\s*,)?(?=\s)",
    re.IGNORECASE,
)

_DIGIT_MARKER = re.compile(r"(?:^|(?<=\s))(?P<marker>(?P<n>[1-9])\.)\s+(?=[A-Za-z])")


def _marker_value(marker):
    m = marker.lower().split()
    if m[:3] == ["first", "of", "all"]:
        return 1
    if len(m) == 2:
        tail = m[1]
        if tail.isdigit():
            return int(tail)
        return _CARDINAL.get(tail)
    word = m[0]
    if word in _CLOSERS:
        return "close"
    return _ORDINAL.get(word) or _LY.get(word)


def _find_markers(text):
    """(start, end, value) for each candidate marker, in text order. start
    is where the marker (or its "and") begins, end is past its comma."""
    found = []
    for m in _MARKER.finditer(text):
        value = _marker_value(m.group("marker"))
        if value is None:
            continue
        # A bare ordinal needs its comma ("First, book the hall") or to
        # start a sentence; "point one" / "firstly" / "first of all" are
        # unambiguous enough without one.
        bare = m.group("marker").lower() in _ORDINAL
        if bare and not m.group("comma") and not re.search(
                r"(^|[.!?:\n])\s*$", m.group("lead")):
            continue
        found.append((m.start() + len(m.group("lead")), m.end(), value))
    # Whisper sometimes writes spoken points as its own inline list:
    # "1. The build is green 2. The release is tomorrow".
    for m in _DIGIT_MARKER.finditer(text):
        found.append((m.start("marker"), m.end(), int(m.group("n"))))
    return sorted(found)


def _ordered_run(found):
    """The longest run counting 1, 2, 3 ... (optionally ending with a
    closer), as a list of markers; [] if there's no run of two."""
    best = []
    for i, (_, _, v) in enumerate(found):
        if v != 1:
            continue
        run, want = [found[i]], 2
        for item in found[i + 1:]:
            if item[2] == want:
                run.append(item)
                want += 1
            elif item[2] == "close" and len(run) >= 2:
                run.append(item)
                break
        if len(run) >= 2 and len(run) > len(best):
            best = run
    return best


_SENTENCE_END = re.compile(r"[.!?](?=\s+[A-Z])")


def _clean_item(s):
    s = s.strip()
    s = re.sub(r"[,;]?\s+and$", "", s, flags=re.IGNORECASE)
    s = s.rstrip(",;: ").strip()
    if s[:1].islower():
        s = s[0].upper() + s[1:]
    return s


def format_bullets(text):
    if not text or "\n" in text:
        return text  # already laid out (grammar pass made its own list)
    run = _ordered_run(_find_markers(text))
    if not run:
        return text

    lead = text[:run[0][0]].strip()
    items = []
    for k, (start, end, _) in enumerate(run):
        stop = run[k + 1][0] if k + 1 < len(run) else len(text)
        items.append(text[end:stop])

    # The last item ends at its first sentence when the others were single
    # sentences; what follows is a closing remark, typed after the list.
    tail = ""
    single = all(len(_SENTENCE_END.findall(i.strip().rstrip(".!?"))) == 0
                 for i in items[:-1])
    if single:
        m = _SENTENCE_END.search(items[-1])
        if m:
            tail = items[-1][m.end():].strip()
            items[-1] = items[-1][:m.end()]

    items = [_clean_item(i) for i in items]
    if any(not i for i in items):
        return text
    if single:
        items = [i[:-1] if i.endswith(".") else i for i in items]

    lines = []
    if lead:
        lines.append(re.sub(r"[.,;:]*$", "", lead) + ":")
    lines += [BULLET + i for i in items]
    if tail:
        lines.append(tail)
    return "\n".join(lines)
