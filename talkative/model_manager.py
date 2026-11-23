"""
App-owned speech model storage.

Models live in %LOCALAPPDATA%\\Talkative\\models, or beside the EXE when
it was installed outside the user's profile (choose_models_dir; not the
shared Hugging Face cache), so deleting them from the UI can't surprise other tools and
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
# Bytes on disk once downloaded (MiB, measured 2026-11-11): the progress
# bar's 100%. A later model update may differ a little, so the bar stops
# at 99% until the download really ends.
GRAMMAR_DOWNLOAD_MB = 1486

MODELS = {
    "fast": {
        "size": "small.en",
        "label": "Fast",
        "tagline": "Instant response",
        "approx": "about 0.5 GB",
        "download_gb": 0.5,
        "download_mb": 464,
        "ram_mb": 400,
        # Shown while switching to it (load measured 2026-11-11: ~1.5 s / 12 s).
        "load_note": "a few seconds",
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
        "download_mb": 1446,
        "ram_mb": 900,
        "load_note": "about 10 to 20 seconds",
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


_models_dir = None


def _under(path, parent):
    try:
        Path(path).resolve().relative_to(Path(parent).resolve())
        return True
    except (ValueError, OSError):
        return False


def _writable(d):
    try:
        d.mkdir(parents=True, exist_ok=True)
        probe = d / ".talkative-write-test"
        probe.write_bytes(b"")
        probe.unlink()
        return True
    except OSError:
        return False


def choose_models_dir(exe=None, frozen=None, store=None, profile=None, default=None):
    """Where the models live (2026-11-23, user: let people pick where
    Talkative installs, and have the models follow, so installing on D:
    really keeps the gigabytes off C:).

    - Installed copy outside the user's profile (the installer's "Install
      location"): <install folder>\\models.
    - Otherwise, from source, the Store build, or the default install
      under %LOCALAPPDATA%\\Programs: %LOCALAPPDATA%\\Talkative\\models.
    - Models already in %LOCALAPPDATA%\\Talkative\\models are kept there
      (no surprise re-download for existing installs), and an install
      folder that can't be written falls back there too.
    Arguments are for tests; the app calls models_dir()."""
    import sys
    from . import packaging
    default = Path(default) if default else settings_dir() / "models"
    exe = Path(exe or sys.executable)
    frozen = getattr(sys, "frozen", False) if frozen is None else frozen
    store = packaging.is_store_build() if store is None else store
    profile = profile or os.environ.get("USERPROFILE", "")
    if not frozen or store or (profile and _under(exe, profile)):
        return default
    if default.is_dir() and any(p.is_dir() and any(p.iterdir()) for p in default.iterdir()):
        return default
    beside = exe.parent / "models"
    return beside if _writable(beside) else default


def models_dir():
    """Chosen once per run (see choose_models_dir), so it can't change
    under a download or a loaded model."""
    global _models_dir
    if _models_dir is None:
        _models_dir = choose_models_dir()
    _models_dir.mkdir(parents=True, exist_ok=True)
    return _models_dir


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


def folder_mb(path):
    """MiB of files under `path` (0 if missing), partial downloads included."""
    total = 0
    if path is None or not Path(path).is_dir():
        return 0.0
    for p in Path(path).rglob("*"):
        try:
            if p.is_file():
                total += p.stat().st_size
        except OSError:
            pass
    return total / (1024 * 1024)


def download_percent(done_mb, needed_mb, finished=False):
    """0-100 for a progress bar; never 100 before the download ends."""
    if finished:
        return 100
    if needed_mb <= 0:
        return 0
    return max(0, min(99, int(done_mb / needed_mb * 100)))


def speech_download_mb(size):
    """MiB of this voice model on disk so far (its Hugging Face cache
    folder holds the partial files while downloading)."""
    if "/" in size:
        return folder_mb(models_dir() / ("models--" + size.replace("/", "--")))
    return folder_mb(_repo_dir(size))


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
