"""
App-owned speech model storage.

Models live in %LOCALAPPDATA%\\Talkative\\models (not the shared Hugging
Face cache), so deleting them from the UI can't surprise other tools and
"storage used" is accurate. Downloads go through faster-whisper's own
download helper pointed at this folder; the same folder is passed to
WhisperModel as download_root at load time.

Fast only. The Accurate tier (large-v3-turbo) was removed 2026-07-20 at
the user's request, in favor of leaning on the grammar engine for quality
instead of a slower, larger speech model -- not just uninstalled, the
option itself no longer exists in the UI. See CLAUDE.md for the full
rationale and the guard changes that went with it in grammar_engine.py.
"""

import os
import shutil
from pathlib import Path

from .settings import settings_dir

MODELS = {
    "fast": {
        "size": "small.en",
        "label": "Fast",
        "tagline": "Instant response",
        "approx": "about 244 MB",
        "latency": "Text appears about 2–3 seconds after you stop speaking. "
                   "Longer sentences can take a bit more time.",
    },
}


def tier_for_size(size):
    for tier, info in MODELS.items():
        if info["size"] == size:
            return tier
    return None


def models_dir():
    d = settings_dir() / "models"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _repo_dir(size, base=None):
    base = models_dir() if base is None else Path(base)
    return next(base.glob(f"models--*faster-whisper-{size}"), None)


def is_downloaded(size):
    repo = _repo_dir(size)
    if repo is None:
        return False
    return any(repo.glob("snapshots/*/model.bin"))


def download(size):
    """Blocking download into the app model folder (call from a worker
    thread). Raises on failure; a partial download is not reported as
    downloaded by is_downloaded (it checks for model.bin)."""
    from faster_whisper.utils import download_model

    download_model(size, cache_dir=str(models_dir()))


def delete(size):
    repo = _repo_dir(size)
    if repo is not None:
        shutil.rmtree(repo, ignore_errors=True)


def storage_used_mb():
    total = 0
    for path in models_dir().rglob("*"):
        try:
            if path.is_file():
                total += path.stat().st_size
        except OSError:
            pass
    return total / (1024 * 1024)


def migrate_from_hf_cache():
    """One-time copy of already-downloaded faster-whisper models from the
    shared Hugging Face cache into the app folder, so existing users don't
    re-download. The shared cache is left untouched (other tools may use
    it)."""
    old_hub = Path(os.environ.get("USERPROFILE", str(Path.home()))) / ".cache" / "huggingface" / "hub"
    if not old_hub.is_dir():
        return
    for info in MODELS.values():
        size = info["size"]
        if is_downloaded(size):
            continue
        source = _repo_dir(size, base=old_hub)
        if source is not None and any(source.glob("snapshots/*/model.bin")):
            try:
                shutil.copytree(source, models_dir() / source.name, dirs_exist_ok=True)
            except Exception:
                pass
