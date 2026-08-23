"""Opt-in, local-only record of past dictations (what actually got pasted,
not raw ASR or intermediate cleanup stages -- that's what debug.log is
for). Off by default; only written to when config.ENABLE_HISTORY is on.

Mirrors settings.py's whole-file read/write JSON pattern and the same
"must never break dictation" philosophy: every operation is wrapped in
try/except and fails silently.
"""

import json
import os
from datetime import datetime
from pathlib import Path

MAX_ENTRIES = 200


def _path():
    return Path(os.environ.get("LOCALAPPDATA", ".")) / "SumitSpeak" / "history.json"


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
    try:
        _path().unlink(missing_ok=True)
    except Exception:
        pass
