"""Opt-in, local-only record of past dictations (what actually got pasted,
not raw ASR or intermediate cleanup stages -- that's what debug.log is
for). Off by default; only written to when config.ENABLE_HISTORY is on.

Mirrors settings.py's whole-file read/write JSON pattern and the same
"must never break dictation" philosophy: every operation is wrapped in
try/except and fails silently.
"""

import json
import threading
from datetime import datetime

from .settings import settings_dir

MAX_ENTRIES = 200
# add() (a dictation finishing, worker thread) and clear() (Settings) must
# not interleave: a clear between add()'s read and write brought the whole
# old history back (neutral QA 2026-11-23).
_lock = threading.Lock()


def _path():
    return settings_dir() / "history.json"


def load():
    try:
        data = json.loads(_path().read_text(encoding="utf-8-sig"))
        if isinstance(data, list):
            return data
    except Exception:
        pass
    return []


def add(text):
    if not text:
        return
    with _lock:
        _add(text)


def _add(text):
    try:
        entries = load()
        entries.append({
            "time": datetime.now().isoformat(timespec="seconds"),
            "text": text,
        })
        entries = entries[-MAX_ENTRIES:]
        path = _path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def clear():
    """True when the history is gone (or never existed)."""
    with _lock:
        try:
            _path().unlink(missing_ok=True)
            return True
        except Exception:
            return False
