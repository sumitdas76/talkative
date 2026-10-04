"""Remove unpacked copies of Talkative left in %TEMP% by earlier runs.

The EXE is a PyInstaller onefile build: each launch unpacks ~250 MB into
%TEMP%\\_MEI<n>, and the launcher process deletes it on a normal exit.
When the app is killed instead (End task, a crash, killing only the
launcher in Task Manager), the folder stays forever -- 107 of them,
4.9 GB, piled up on the dev PC by 2026-10-04.

Only folders that are clearly Talkative's are touched (they hold both
faster_whisper and uiautomation; other PyInstaller apps use the same
_MEI prefix). A folder still in use -- another running copy, or the old
one during an update -- can't be renamed on Windows while any file inside
is open, so it is renamed first and deleted only if that worked; a
half-deleted live copy would crash that instance.
"""
import logging
import os
import shutil
import sys
import tempfile
from pathlib import Path

_MARKERS = ("faster_whisper", "uiautomation")


def sweep():
    """Delete stale Talkative _MEI folders. Frozen EXE only; never raises.
    Returns the number of folders removed."""
    own = getattr(sys, "_MEIPASS", None)
    if not getattr(sys, "frozen", False) or not own:
        return 0
    removed = 0
    try:
        candidates = list(Path(tempfile.gettempdir()).glob("_MEI*"))
    except OSError:
        return 0
    for d in candidates:
        try:
            if (not d.is_dir() or os.path.samefile(d, own)
                    or not all((d / m).is_dir() for m in _MARKERS)):
                continue
            trash = d.with_name(d.name + "-talkative-old")
            os.rename(d, trash)  # fails while any file inside is in use
        except OSError:
            continue
        shutil.rmtree(trash, ignore_errors=True)
        removed += 1
    if removed:
        logging.info("Removed %d leftover temp copies of Talkative", removed)
    return removed
