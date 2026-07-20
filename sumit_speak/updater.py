"""
Update system (spec section 7): manifest-driven model updates.

Publisher side is one manifest.json in a public GitHub repo (see
docs/manifest-sample.json); editing it in the browser is the whole
publishing act. Client side, in this module:

- At most once per day, at startup, the manifest is fetched (a few hundred
  bytes; offline or malformed silently skips -- updates must never break
  dictation).
- An applicable update shows ONE component-blind dialog ("An improvement
  update is available (X MB)") -- it never names the model. Download /
  Not now. "Not now" snoozes that update for a week; a newer version ends
  the snooze early.
- Download runs in the background into <models>/staging while dictation
  keeps working. The new model must load and pass a self-test
  (verify-then-swap) before the old one is touched; the swap waits for an
  idle moment. Any failure restores the previous state -- the user never
  ends up without a working model.
- The replaced version is kept in <models>/previous until the user has
  dictated UPDATE_GRACE_WORDS words with the new one (usage-based, then
  purged silently). While it exists, the Models tab shows "Undo last
  update" with a word countdown; using it restores the old version and
  permanently suppresses that update. Only one step back is ever kept.

State lives in %LOCALAPPDATA%\\SumitSpeak\\updater.json:
{ "last_check": "2026-07-19", "snoozed": {"grammar@2": "2026-07-26"},
  "suppressed": ["grammar@2"],
  "grace": {"key": "grammar", "version": "2", "words_left": 640} }
"""

import json
import shutil
import threading
import time
import urllib.request
from datetime import date, timedelta
from pathlib import Path

from . import app_icon, config, model_manager, overlay_thread

# Manifest key -> what it is locally. "speech" entries update the
# faster-whisper repo dirs; "grammar" updates the invisible engine.
# speech-accurate removed 2026-07-20 along with the Accurate model tier
# itself (see model_manager.py) -- no longer offered, so no longer checked.
MANAGED = {
    "speech-fast": {"kind": "speech", "size": "small.en"},
    "grammar": {"kind": "grammar"},
}

_state_lock = threading.Lock()
_busy = threading.Lock()  # one download/swap/undo at a time
_downloading = None  # manifest key while a download/swap runs (for the UI)


def state_path():
    return model_manager.models_dir().parent / "updater.json"


def _load_state():
    try:
        data = json.loads(state_path().read_text(encoding="utf-8-sig"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_state(state):
    try:
        state_path().write_text(
            json.dumps(state, indent=2), encoding="utf-8"
        )
    except Exception:
        pass


def _model_dir(key):
    info = MANAGED[key]
    if info["kind"] == "speech":
        return model_manager._repo_dir(info["size"])
    d = model_manager.models_dir() / config.GRAMMAR_MODEL_DIR
    return d if d.is_dir() else None


def installed_version(key):
    """Version marker of the locally installed model, or None when the
    model isn't installed (updates only improve what the user has).
    A model without a marker is the unversioned baseline: '1'."""
    d = _model_dir(key)
    if d is None:
        return None
    try:
        return (d / "version.txt").read_text(encoding="utf-8-sig").strip() or "1"
    except Exception:
        return "1"


def fetch_manifest():
    url = config.MANIFEST_URL
    if not url:
        return None
    try:
        with urllib.request.urlopen(url, timeout=8) as r:
            data = json.loads(r.read().decode("utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def find_update(manifest):
    """First applicable (key, entry) or None. Applicable: model installed,
    manifest version differs, not permanently suppressed, not snoozed."""
    state = _load_state()
    today = date.today().isoformat()
    models = manifest.get("models")
    if not isinstance(models, dict):
        return None
    for key in MANAGED:
        entry = models.get(key)
        if not isinstance(entry, dict):
            continue
        version = str(entry.get("version", "")).strip()
        if not version:
            continue
        local = installed_version(key)
        if local is None or local == version:
            continue
        tag = f"{key}@{version}"
        if tag in state.get("suppressed", []):
            continue
        if state.get("snoozed", {}).get(tag, "") >= today:
            continue
        if MANAGED[key]["kind"] == "grammar" and not entry.get("hf_repo"):
            continue  # not updatable until a repo is published
        return key, entry
    return None


def snooze(key, entry):
    state = _load_state()
    until = (date.today() + timedelta(days=7)).isoformat()
    state.setdefault("snoozed", {})[f"{key}@{entry.get('version')}"] = until
    _save_state(state)


def get_status():
    """For the Models tab: {'last_check', 'downloading', 'grace'}."""
    state = _load_state()
    return {
        "last_check": state.get("last_check"),
        "downloading": _downloading,
        "grace": state.get("grace"),
    }


def note_words(n):
    """Called after each successful dictation. Burns down the grace
    counter; at zero the previous version is purged silently."""
    with _state_lock:
        state = _load_state()
        grace = state.get("grace")
        if not grace:
            return
        grace["words_left"] = grace.get("words_left", 0) - max(0, n)
        if grace["words_left"] <= 0:
            shutil.rmtree(
                model_manager.models_dir() / "previous", ignore_errors=True
            )
            state.pop("grace", None)
        _save_state(state)


# ---------------------------------------------------------------------------
# Download, verify, swap
# ---------------------------------------------------------------------------

def _staging_dir():
    return model_manager.models_dir() / "staging"


def _previous_dir():
    return model_manager.models_dir() / "previous"


def _download_into_staging(key, entry):
    staging = _staging_dir() / key
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    info = MANAGED[key]
    if info["kind"] == "speech":
        from faster_whisper.utils import download_model

        download_model(info["size"], cache_dir=str(staging))
        return model_manager._repo_dir(info["size"], base=staging)
    from huggingface_hub import snapshot_download

    target = staging / "grammar"
    snapshot_download(entry["hf_repo"], local_dir=str(target))
    return target


def _verify(key, new_dir):
    """Self-test: the new model must actually load and run before the old
    one is touched."""
    info = MANAGED[key]
    if info["kind"] == "speech":
        import numpy as np

        from .transcriber import Transcriber

        staged_root = new_dir.parent  # hub-layout cache root in staging
        t = Transcriber(info["size"], config.DEVICE, config.COMPUTE_TYPE,
                        download_root=str(staged_root))
        t.transcribe(np.zeros(8000, dtype=np.float32), 16000)
        return
    import ctranslate2
    from tokenizers import Tokenizer

    gen = ctranslate2.Generator(str(new_dir), device="cpu", compute_type="int8")
    tok = Tokenizer.from_file(str(new_dir / "tokenizer.json"))
    gen.generate_batch([tok.encode("Hello").tokens], max_length=8)


def _swap(key, entry, new_dir, controller):
    """Move the live model aside to previous/, move the staged one live,
    reload. On any failure restore the old one. Returns True on success."""
    from . import grammar_engine

    info = MANAGED[key]
    live = _model_dir(key)
    previous = _previous_dir()
    shutil.rmtree(previous, ignore_errors=True)  # only one step back is kept
    previous.mkdir(parents=True)
    parked = previous / live.name

    is_active_speech = (
        info["kind"] == "speech" and info["size"] == config.MODEL_SIZE
    )
    try:
        if is_active_speech:
            controller.unload_speech()
        elif info["kind"] == "grammar":
            grammar_engine.unload()
        live.rename(parked)
        target = model_manager.models_dir() / live.name
        new_dir.rename(target)
        (target / "version.txt").write_text(
            str(entry.get("version")), encoding="utf-8"
        )
        if is_active_speech:
            controller.reload_speech()
        elif info["kind"] == "grammar":
            grammar_engine.load()
        return True
    except Exception:
        # Restore: put the old model back and bring it up again.
        try:
            target = model_manager.models_dir() / live.name
            shutil.rmtree(target, ignore_errors=True)
            if parked.is_dir():
                parked.rename(live)
        finally:
            if is_active_speech:
                controller.reload_speech()
            elif info["kind"] == "grammar":
                grammar_engine.load()
        shutil.rmtree(previous, ignore_errors=True)
        return False


def _run_update(key, entry, controller):
    global _downloading
    with _busy:
        _downloading = key
        try:
            new_dir = _download_into_staging(key, entry)
            if new_dir is None:
                return
            _verify(key, new_dir)
            while controller.is_busy():
                time.sleep(1.0)
            controller.begin_swap()
            try:
                ok = _swap(key, entry, new_dir, controller)
            finally:
                controller.end_swap(ok)
            if ok:
                with _state_lock:
                    state = _load_state()
                    state["grace"] = {
                        "key": key,
                        "version": str(entry.get("version")),
                        "words_left": config.UPDATE_GRACE_WORDS,
                    }
                    _save_state(state)
        except Exception:
            pass
        finally:
            _downloading = None
            shutil.rmtree(_staging_dir(), ignore_errors=True)


def undo_last_update(controller):
    """Restore the previous version, permanently suppress the undone
    update, clear the grace. Runs the same careful swap dance."""
    from . import grammar_engine

    with _busy:
        with _state_lock:
            state = _load_state()
            grace = state.get("grace")
        if not grace:
            return False
        key = grace["key"]
        info = MANAGED[key]
        live = _model_dir(key)
        parked = next(_previous_dir().glob("*"), None)
        if live is None or parked is None:
            return False
        is_active_speech = (
            info["kind"] == "speech" and info["size"] == config.MODEL_SIZE
        )
        while controller.is_busy():
            time.sleep(1.0)
        controller.begin_swap()
        ok = False
        try:
            if is_active_speech:
                controller.unload_speech()
            elif info["kind"] == "grammar":
                grammar_engine.unload()
            shutil.rmtree(live, ignore_errors=True)
            parked.rename(model_manager.models_dir() / parked.name)
            ok = True
        except Exception:
            pass
        finally:
            if is_active_speech:
                controller.reload_speech()
            elif info["kind"] == "grammar":
                grammar_engine.load()
            controller.end_swap(ok)
        if ok:
            with _state_lock:
                state = _load_state()
                state.setdefault("suppressed", []).append(
                    f"{key}@{grace['version']}"
                )
                state.pop("grace", None)
                _save_state(state)
            shutil.rmtree(_previous_dir(), ignore_errors=True)
        return ok


# ---------------------------------------------------------------------------
# Startup check + dialog
# ---------------------------------------------------------------------------

def _show_dialog(entry, on_download, on_cancel):
    """Component-blind update prompt. Built as a tk.Toplevel on the shared
    overlay thread (see overlay_thread.py -- multiple independent tk.Tk()
    roots across threads caused real crashes), not its own Tk instance;
    no grab, no focus stealing."""
    overlay = overlay_thread.get()
    overlay._ready.wait(timeout=3)
    if overlay._failed:
        return

    def build():
        try:
            import tkinter as tk
            from tkinter import ttk

            root = tk.Toplevel(overlay.root)
            root.title("Sumit Speak")
            app_icon.set_window_icon(root)
            root.resizable(False, False)
            size = entry.get("size_mb")
            note = str(entry.get("note", "")).strip()
            text = "An improvement update is available"
            if isinstance(size, (int, float)) and size > 0:
                text += f" ({size:.0f} MB)".replace(".0", "")
            text += "."
            if note:
                text += f"\n\n{note}"
            text += "\n\nDictation keeps working while it downloads."
            ttk.Label(root, text=text, wraplength=360, padding=16).pack()
            row = ttk.Frame(root, padding=(16, 0, 16, 14))
            row.pack(fill="x")

            def choose(c):
                root.destroy()
                (on_download if c == "download" else on_cancel)()

            ttk.Button(row, text="Download",
                       command=lambda: choose("download")).pack(side="right")
            ttk.Button(row, text="Not now",
                       command=lambda: choose("cancel")).pack(side="right", padx=8)
            root.protocol("WM_DELETE_WINDOW", lambda: choose("cancel"))
        except Exception:
            pass

    overlay.build(build)


def start_background_check(controller):
    """Call once at startup. Waits for things to settle, then does the
    at-most-once-a-day manifest check and drives the whole flow."""

    def run():
        time.sleep(10)  # let startup settle (spec: appears a few seconds in)
        with _state_lock:
            state = _load_state()
            today = date.today().isoformat()
            if state.get("last_check") == today:
                return
            state["last_check"] = today
            _save_state(state)
        manifest = fetch_manifest()
        if not manifest:
            return
        found = find_update(manifest)
        if not found:
            return
        key, entry = found
        _show_dialog(
            entry,
            on_download=lambda: threading.Thread(
                target=_run_update, args=(key, entry, controller), daemon=True
            ).start(),
            on_cancel=lambda: snooze(key, entry),
        )

    threading.Thread(target=run, daemon=True).start()
