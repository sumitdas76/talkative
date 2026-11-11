"""
App-owned speech model storage.

Models live in %LOCALAPPDATA%\\Talkative\\models (not the shared Hugging
Face cache), so deleting them from the UI can't surprise other tools and
"storage used" is accurate. Downloads go through faster-whisper's own
download helper pointed at this folder; the same folder is passed to
WhisperModel as download_root at load time.

Two tiers. Fast (small.en) is the default. Accurate came back 2026-11-11
as distil-large-v3.5 (the old large-v3-turbo Accurate tier was removed
2026-07-20), after tools/grammar_eval/local_stt_bench.py on 59 real clips:
word errors 16.4% -> 12.4% (Indian English 19% -> 12%), but about 5 s per
dictation at any length (its large encoder always reads a 30 s window).
"""

import os
import shutil
from pathlib import Path

from .settings import settings_dir

# RAM figures shown in Settings > General > Local, measured 2026-11-11 with
# tools/grammar_eval/ram_probe.py (working set while loaded, 60 s
# dictation; loading briefly peaks higher). APP_RAM_MB is Talkative
# itself with no model (UI, hotkey hook, audio).
APP_RAM_MB = 200
GRAMMAR_RAM_MB = 1700

MODELS = {
    "fast": {
        "size": "small.en",
        "label": "Fast",
        "tagline": "Instant response",
        "approx": "about 0.5 GB",
        "download_gb": 0.5,
        "ram_mb": 400,
        # Card bullets in Settings; download size and RAM are added after.
        "points": ["Text in 1–2 seconds", "Less accurate, most of all with accents"],
        "advice": "Recommended for most people.",
    },
    "accurate": {
        "size": "distil-whisper/distil-large-v3.5-ct2",
        "english_only": True,
        "label": "Accurate",
        "tagline": "Fewer mistakes",
        "approx": "about 1.5 GB",
        "download_gb": 1.5,
        "ram_mb": 900,
        "points": ["Text in about 5 seconds, even for a few words",
                   "About 25% fewer mistakes, most of all with accents"],
        "advice": "Pick this if Fast often mishears you.",
    },
}


def tier_for_size(size):
    for tier, info in MODELS.items():
        if info["size"] == size:
            return tier
    return None


def english_only(size):
    """True when the model only knows English, so the language is fixed
    instead of detected (detection costs time and can guess wrong)."""
    info = MODELS.get(tier_for_size(size) or "", {})
    return size.endswith(".en") or bool(info.get("english_only"))


def ram_mb(size, grammar_on):
    """About how much RAM Talkative uses in Local mode with this voice
    model, plus the grammar model when it's switched on."""
    info = MODELS.get(tier_for_size(size) or "fast", MODELS["fast"])
    return APP_RAM_MB + info["ram_mb"] + (GRAMMAR_RAM_MB if grammar_on else 0)


def gb(mb):
    """'0.6 GB' style text for a size in MB."""
    return f"{mb / 1000:.1f} GB"


def models_dir():
    d = settings_dir() / "models"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _repo_dir(size, base=None):
    base = models_dir() if base is None else Path(base)
    if "/" in size:  # a Hugging Face repo id: "distil-whisper/distil-large-v3.5-ct2"
        repo = base / ("models--" + size.replace("/", "--"))
        return repo if repo.is_dir() else None
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
