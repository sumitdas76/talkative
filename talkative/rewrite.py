"""
Rewrite selected text by voice (Backlog voice-rewrite-selection,
PROJECT_CHECKS "Feature 2026-11-23" item 2). Select text, hold the rewrite
key (default Right Ctrl + Right Alt), say what to change ("make it
shorter", "turn this into a list"), let go: the selection is replaced by
the rewritten text. Cloud only: Groq's gpt-oss-20b (the user's own key, or
Talkative Cloud's /rewrite route).

This module is the pure part -- what to refuse and how to read the model's
reply (tools/rewrite_test.py). app.py reads the selection, records, calls
cloud_client.rewrite() and pastes.

Never replaces anything it isn't sure of: an empty reply, a reply that
says the instruction wasn't a rewrite (cloud_prompt.NOT_A_REWRITE), or a
selection that changed while the user spoke all leave the text alone.
Ctrl+Z in the app puts the original back (the rewrite is a paste).
"""

import re

from . import cloud_prompt, config

NEEDS_CLOUD = ("Rewriting selected text needs Cloud. Switch to Cloud in "
               "Settings > General to use it.")
NOTHING_SELECTED = ("Select some text first, then hold the rewrite key and "
                    "say what to change.")
NO_INSTRUCTION = "No words were heard, so the text was left as it was."
QUESTION = ("That sounded like a question, not a change, so the text was "
            "left as it was. Say what to change, like “make it shorter”.")

# A question about the text ("Who is this addressed to?") gets answered by
# gpt-oss, and the answer would replace the selection ("Rahul" pasted over
# a whole email, 2026-11-23; an extra prompt example didn't stop it). So an
# instruction that opens like a question and asks for no edit is refused
# before it's sent. "Can/could/would you..." are polite requests, not
# questions about the text, and pass.
_QUESTION_START = re.compile(
    r"^(who|whom|whose|what|what's|whats|when|where|which|why|how|is|isn't|"
    r"are|aren't|was|were|does|doesn't|do|did|has|have|should|tell me)\b", re.I)
_EDIT_WORDS = re.compile(
    r"\b(make|makes|turn|change|fix|rewrite|reword|rephrase|shorten|"
    r"lengthen|expand|trim|cut|translate|convert|add|remove|delete|drop|"
    r"replace|format|put|split|merge|join|simplify|summari[sz]e|polish|"
    r"clean|tidy|capitali[sz]e|uppercase|lowercase|bullet|list|soften|"
    r"improve|edit|write|use)\b", re.I)


def instruction_problem(said):
    """Why the spoken instruction can't be sent, or None."""
    if not said:
        return NO_INSTRUCTION
    if _QUESTION_START.match(said) and not re.match(r"how about\b", said, re.I) \
            and not _EDIT_WORDS.search(said):
        return QUESTION
    return None


def selection_problem(selected):
    """Why `selected` can't be rewritten, or None."""
    if not (selected or "").strip():
        return NOTHING_SELECTED
    if len(selected) > config.REWRITE_MAX_CHARS:
        return (f"That's more than {config.REWRITE_MAX_CHARS:,} characters. "
                "Select less text and try again.")
    return None


def instruction(raw):
    """The spoken instruction, tidied, or "" when nothing was said."""
    return " ".join((raw or "").split())


_TAGS = re.compile(r"^\s*<text>\s*\n?(.*?)\n?\s*</text>\s*$", re.S)


def _squash(s):
    return " ".join(s.lower().split())


# The prompt's own example texts and answers. With an instruction it can't
# act on ("Undo that." on "Regards, Sumit", 2026-11-23) the model once
# replied with an example's text instead of the user's.
_SHOTS = [(_squash(text), _squash(answer))
          for text, _instruction, answer in cloud_prompt.REWRITE_SHOTS]


def _echoes_example(original, reply):
    """Whether `reply` holds an example's text or answer that the user's own
    selection doesn't explain (they may really have selected that text)."""
    r, o = _squash(reply), _squash(original)
    for text, answer in _SHOTS:
        if text in o:
            continue
        if text in r or (answer != _squash(cloud_prompt.NOT_A_REWRITE) and answer in r):
            return True
    return False


def read_reply(original, reply):
    """-> (new text, None) to paste, or (None, reason) to leave the
    selection alone. `original` is the selected text as read."""
    reply = (reply or "").strip()
    m = _TAGS.match(reply)
    if m:
        reply = m.group(1).strip()
    # gpt-oss likes em dashes ("website work—₹45,000"); the user
    # chose (2026-11-23) that Talkative never adds one: ", " between words,
    # "-" as a line's list marker. Kept when the selection already has them.
    if "—" not in original:
        reply = re.sub(r"(?m)^(\s*)—\s*", r"\1- ", reply)
        reply = re.sub(r"\s*—\s*", ", ", reply)
        reply = re.sub(r",\s*([,.;:!?])", r"\1", reply)
    # gpt-oss ends lines with Markdown's two-space hard break ("Best
    # regards,  \nSumit", every bullet): the spaces would be pasted too.
    reply = "\n".join(line.rstrip() for line in reply.split("\n"))
    if cloud_prompt.NOT_A_REWRITE in reply:
        return None, QUESTION
    if not reply:
        return None, "Nothing came back, so the text was left as it was."
    if len(reply) > config.REWRITE_MAX_REPLY:
        return None, "The rewrite came back too long, so the text was left as it was."
    if reply == original.strip():
        return None, "The rewrite came back the same, so nothing was changed."
    if _echoes_example(original, reply):
        return None, ("The rewrite didn't match your text, so it was left as it "
                      "was. Say what to change, like “make it shorter”.")
    return keep_edges(original, reply), None


def keep_edges(original, new):
    """The whitespace around the selection stays: a selected paragraph
    often ends with its line break, and a double-clicked word with a space."""
    lead = original[:len(original) - len(original.lstrip())]
    trail = original[len(original.rstrip()):]
    return lead + new.strip() + trail


def same_selection(before, now):
    """The selection read before speaking still looks the same now (so the
    paste replaces what was rewritten). Line breaks and the no-break space
    some apps report are compared loosely."""
    def norm(s):
        return " ".join((s or "").replace("\xa0", " ").split())
    return norm(before) == norm(now)
