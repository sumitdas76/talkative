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

New app versions: the same daily pass checks config.RELEASES_API_URL (the
latest GitHub release). If it's newer than the running __version__, an
Update / Not now prompt appears. Update downloads TalkativeSetup.exe in the
background, verifies it against the release asset's sha256 digest, waits
for an idle moment, starts it with /VERYSILENT /UPDATE and exits; the
installer replaces the EXE and relaunches Talkative (see
installer/Talkative.iss). "Not now" snoozes that version for a week, same
as model updates ("app@<version>" in snoozed).

State lives in %LOCALAPPDATA%\\Talkative\\updater.json:
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

from . import __version__, app_icon, config, model_manager, overlay_thread

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


_INSTALLER_NAME = "TalkativeSetup.exe"


def _parse_version(s):
    """'v1.3.5' / '1.3.5' -> (1, 3, 5); None if it isn't all dotted ints."""
    parts = str(s).strip().lstrip("vV").split(".")
    try:
        return tuple(int(p) for p in parts)
    except ValueError:
        return None


def _request(url):
    return urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": f"Talkative/{__version__}",
    })


def fetch_latest_release():
    """{'version', 'page', 'installer_url', 'size', 'sha256'} for the latest
    published release, or None. The installer asset must carry GitHub's
    sha256 digest -- without it there's nothing to verify the download
    against, so no one-click update is offered. Offline, rate-limited, or
    malformed all silently return None. (GitHub's /releases/latest never
    returns drafts or pre-releases, so a pre-release is only reachable by
    pointing releases_api_url at its /releases/tags/<tag> URL -- that's how
    the updater itself is tested without users ever seeing the test.)"""
    url = config.RELEASES_API_URL
    if not url:
        return None
    try:
        with urllib.request.urlopen(_request(url), timeout=8) as r:
            data = json.loads(r.read().decode("utf-8"))
        if not isinstance(data, dict):
            return None
        version = str(data.get("tag_name", "")).strip().lstrip("vV")
        page = str(data.get("html_url", "")).strip()
        asset = next(
            (a for a in data.get("assets", [])
             if isinstance(a, dict) and a.get("name") == _INSTALLER_NAME),
            None,
        )
        if not version or not page.startswith("https://github.com/") or not asset:
            return None
        digest = str(asset.get("digest") or "")
        installer_url = str(asset.get("browser_download_url", ""))
        if not digest.startswith("sha256:") or not installer_url.startswith("https://github.com/"):
            return None
        return {
            "version": version,
            "page": page,
            "installer_url": installer_url,
            "size": int(asset.get("size") or 0),
            "sha256": digest.split(":", 1)[1].lower(),
        }
    except Exception:
        return None


def find_app_update(release):
    """The release if it's newer than the running app and not snoozed."""
    if not release:
        return None
    version = release["version"]
    latest, running = _parse_version(version), _parse_version(__version__)
    if latest is None or running is None or latest <= running:
        return None
    if _load_state().get("snoozed", {}).get(f"app@{version}", "") >= date.today().isoformat():
        return None
    return release


def snooze_app(version):
    with _state_lock:
        state = _load_state()
        until = (date.today() + timedelta(days=7)).isoformat()
        state.setdefault("snoozed", {})[f"app@{version}"] = until
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

def _prompt(text, on_download, on_cancel):
    """Download / Not now prompt. Built as a tk.Toplevel on the shared
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
            root.title("Talkative")
            root.configure(bg=overlay_thread.bg_color())
            app_icon.set_window_icon(root)
            root.resizable(False, False)
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


def _show_dialog(entry, on_download, on_cancel):
    """Component-blind model update prompt -- never names the model."""
    size = entry.get("size_mb")
    note = str(entry.get("note", "")).strip()
    text = "An improvement update is available"
    if isinstance(size, (int, float)) and size > 0:
        text += f" ({size:.0f} MB)".replace(".0", "")
    text += "."
    if note:
        text += f"\n\n{note}"
    text += "\n\nDictation keeps working while it downloads."
    _prompt(text, on_download, on_cancel)


def _app_updates_dir():
    return model_manager.models_dir().parent / "updates"


def _download_installer(release, progress):
    """Stream the installer into <appdata>/updates, verifying its sha256
    against the release's digest. Returns the path, or raises -- a file
    that fails verification is deleted, never run."""
    import hashlib

    folder = _app_updates_dir()
    shutil.rmtree(folder, ignore_errors=True)  # stale earlier attempts
    folder.mkdir(parents=True)
    path = folder / f"TalkativeSetup-{release['version']}.exe"
    sha = hashlib.sha256()
    with urllib.request.urlopen(_request(release["installer_url"]), timeout=30) as r, \
            open(path, "wb") as f:
        progress["total"] = int(r.headers.get("Content-Length") or release["size"] or 0)
        while True:
            chunk = r.read(256 * 1024)
            if not chunk:
                break
            f.write(chunk)
            sha.update(chunk)
            progress["done"] += len(chunk)
    if sha.hexdigest() != release["sha256"]:
        path.unlink(missing_ok=True)
        raise ValueError("installer checksum mismatch")
    return path


def _launch_installer(path):
    """Start the installer detached, with a clean environment: it inherits
    ours and later relaunches Talkative, and a PyInstaller onefile EXE that
    starts with its parent's _PYI_*/_MEIPASS* variables set mistakes itself
    for a child process and fails to start."""
    import os
    import subprocess

    env = {k: v for k, v in os.environ.items()
           if not k.upper().startswith(("_PYI", "_MEI"))}
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    subprocess.Popen(
        [str(path), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/UPDATE"],
        env=env,
        close_fds=True,
        creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
    )


def _run_app_update(release, controller, progress):
    """Download + verify in the background, wait for an idle moment, hand
    off to the installer, and exit so it can replace the EXE. The installer
    (/UPDATE mode, see installer/Talkative.iss) relaunches the new version.
    Any failure before the handoff leaves the running app untouched."""
    import os

    try:
        path = _download_installer(release, progress)
    except Exception:
        shutil.rmtree(_app_updates_dir(), ignore_errors=True)
        progress["state"] = "failed"
        return
    progress["state"] = "installing"
    while controller.is_busy():
        time.sleep(1.0)
    controller.begin_swap()  # blocks new dictations during the handoff
    try:
        _launch_installer(path)
    except Exception:
        controller.end_swap(False)
        progress["state"] = "failed"
        return
    time.sleep(1.5)  # let the "restarting" message be seen
    controller.quit_app()
    time.sleep(1.0)
    os._exit(0)  # don't let a lingering non-daemon thread hold the EXE open


def _show_app_dialog(release, controller):
    """One-click app update prompt, on the shared overlay thread like
    _prompt() (see its docstring for why). Closing the window while
    downloading just hides it; the update still finishes."""
    overlay = overlay_thread.get()
    overlay._ready.wait(timeout=3)
    if overlay._failed:
        return
    version = release["version"]

    def build():
        try:
            import tkinter as tk
            from tkinter import ttk

            root = tk.Toplevel(overlay.root)
            root.title("Talkative")
            # Without this the raw Tk background (light grey) shows through
            # around the progress bar in dark mode -- seen live as a white
            # strip behind the bar.
            root.configure(bg=overlay_thread.bg_color())
            app_icon.set_window_icon(root)
            root.resizable(False, False)
            label = ttk.Label(
                root, wraplength=360, padding=(16, 16, 16, 8),
                text=(f"A new version of Talkative is available: {version} "
                      f"(you have {__version__}).\n\nUpdating takes about a "
                      "minute. Talkative will close and reopen by itself, "
                      "and your settings are kept."),
            )
            label.pack(fill="x")
            bar = ttk.Progressbar(root, mode="determinate", length=328, maximum=100)
            row = ttk.Frame(root, padding=(16, 8, 16, 14))
            row.pack(fill="x")
            progress = {"done": 0, "total": 0, "state": "downloading"}

            def poll():
                if not root.winfo_exists():
                    return
                state = progress["state"]
                if state == "downloading":
                    total = progress["total"]
                    if total:
                        bar["value"] = 100 * progress["done"] / total
                        label["text"] = (
                            f"Downloading Talkative {version}… "
                            f"{progress['done'] // 1048576} of {total // 1048576} MB"
                        )
                    root.after(300, poll)
                elif state == "installing":
                    bar["value"] = 100
                    label["text"] = (f"Installing Talkative {version}. "
                                     "It will reopen by itself in a moment.")
                    root.after(300, poll)
                else:
                    bar.pack_forget()
                    label["text"] = ("The update couldn't be downloaded. "
                                     "Talkative will offer it again tomorrow.")
                    ttk.Button(row, text="Close", command=root.destroy).pack(side="right")
                    row.pack(fill="x")
                    root.deiconify()
                    root.protocol("WM_DELETE_WINDOW", root.destroy)

            def update():
                # The button row goes away entirely while downloading (an
                # empty row left a blank band under the bar).
                for w in row.winfo_children():
                    w.destroy()
                row.pack_forget()
                bar.pack(padx=16, pady=(4, 16))
                label["text"] = f"Downloading Talkative {version}…"
                root.protocol("WM_DELETE_WINDOW", root.withdraw)
                threading.Thread(
                    target=_run_app_update, args=(release, controller, progress),
                    daemon=True,
                ).start()
                root.after(300, poll)

            def not_now():
                root.destroy()
                snooze_app(version)

            ttk.Button(row, text="Update", command=update).pack(side="right")
            ttk.Button(row, text="Not now", command=not_now).pack(side="right", padx=8)
            root.protocol("WM_DELETE_WINDOW", not_now)
        except Exception:
            pass

    overlay.build(build)


def start_background_check(controller):
    """Call once at startup. Waits for things to settle, then does the
    at-most-once-a-day manifest check and drives the whole flow."""

    def run():
        time.sleep(10)  # let startup settle (spec: appears a few seconds in)
        # The installer a previous one-click update ran from; it's been
        # used by now (or failed and rolled back -- a retry re-downloads).
        shutil.rmtree(_app_updates_dir(), ignore_errors=True)
        with _state_lock:
            state = _load_state()
            today = date.today().isoformat()
            if state.get("last_check") == today:
                return
            state["last_check"] = today
            _save_state(state)
        release = find_app_update(fetch_latest_release())
        if release:
            _show_app_dialog(release, controller)
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
