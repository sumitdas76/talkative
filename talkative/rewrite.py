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
"Scratch that" puts the original back (last_dictation keeps it).
"""

import re

from . import cloud_prompt, config

NEEDS_CLOUD = ("Rewriting selected text needs Cloud. Switch to Cloud in "
               "Settings > General to use it.")
NOTHING_SELECTED = ("Select some text first, then hold the rewrite key and "
                    "say what to change.")
NO_INSTRUCTION = "No words were heard, so the text was left as it was."


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


def read_reply(original, reply):
    """-> (new text, None) to paste, or (None, reason) to leave the
    selection alone. `original` is the selected text as read."""
    reply = (reply or "").strip()
    m = _TAGS.match(reply)
    if m:
        reply = m.group(1).strip()
    if cloud_prompt.NOT_A_REWRITE in reply:
        return None, ("That sounded like a question, not a change, so the text was "
                      "left as it was. Say what to change, like “make it shorter”.")
    if not reply:
        return None, "Nothing came back, so the text was left as it was."
    if len(reply) > config.REWRITE_MAX_REPLY:
        return None, "The rewrite came back too long, so the text was left as it was."
    if reply == original.strip():
        return None, "The rewrite came back the same, so nothing was changed."
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
