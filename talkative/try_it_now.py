"""
First-run "try it now" box (spec sections 8 and 10.2), and since
2026-10-31 also the microphone check.

Shown once, after the speech model is ready on the very first run: a small
window with a text box inviting the user to hold the hotkey and say
anything. Their first dictation lands here -- a controlled place where
success is visible -- instead of in some arbitrary app where a
non-editable field would greet them with an error popup.

Microphone check (user request 2026-10-31: "there can be thousands of
different types of microphones ... first runs a test on the
microphone"): the box shows the microphone in use with a picker, how
fast it starts (mic_warmup's start-up check, which runs as soon as the
Cloud/Local choice is made), and after each dictation what that
recording says about it (mic_check.analyse: nothing heard, too quiet,
distorting, noisy, first word cut). Settings > Audio & Output > Test
microphone opens the same box later (open_check).

Built as a tk.Toplevel on the shared overlay thread (see overlay_thread.py
-- multiple independent tk.Tk() roots across threads caused real
crashes), not its own Tk instance. Closing it (or clicking "Got it")
records first_run_done so it never appears again on its own.
"""

import logging
import threading

from . import app_icon, audio_devices, config, mic_check, mic_warmup, overlay_thread, settings
from .keynames import friendly

_opened = False
_lock = threading.Lock()
_window = None  # the open box's widgets (overlay thread only), or None

# Set by the app: get() -> the sounddevice index in use (None = Windows
# default), set(index) -> use and save another microphone.
controller = None


def maybe_show():
    """Show the box if this is the first run; otherwise do nothing."""
    global _opened
    if config.FIRST_RUN_DONE:
        return
    with _lock:
        if _opened:
            return
        _opened = True
    _open(first_run=True)


def open_check():
    """Settings > Audio & Output > Test microphone."""
    _open(first_run=False)


def is_open():
    return _window is not None


def report(audio, sample_rate, cold):
    """A dictation finished. If the box is open, show what it says about
    the microphone. Returns mic_check.analyse()'s list, or None when the
    box is closed. Any thread."""
    if _window is None:
        return None
    try:
        found = mic_check.analyse(audio, sample_rate, cold)
    except Exception:
        logging.getLogger(__name__).exception("microphone check failed")
        return None
    try:
        overlay_thread.get().build(lambda: _show_result(found))
    except Exception:
        pass
    return found


def _mark_done():
    try:
        config.FIRST_RUN_DONE = True
        settings.save({"first_run_done": True})
    except Exception:
        pass


def _open(first_run):
    overlay = overlay_thread.get()
    overlay._ready.wait(timeout=3)
    if overlay._failed:
        if first_run:
            _mark_done()
        return
    overlay.build(lambda: _build(overlay, first_run))


def _device():
    try:
        return controller.get() if controller else config.INPUT_DEVICE
    except Exception:
        return config.INPUT_DEVICE


def _show_result(found):
    w = _window
    if w is None:
        return
    try:
        ok = found[0][0] == "ok"
        text = "\n".join(("✓ " if kind == "ok" else "• ") + msg for kind, msg in found)
        w["result"].config(text=text, foreground="" if ok else w["warn"])
    except Exception:
        pass


def _build(overlay, first_run):
    global _window
    try:
        import tkinter as tk
        from tkinter import ttk

        if _window is not None:  # already open: bring it forward
            _window["root"].deiconify()
            _window["root"].lift()
            return

        root = tk.Toplevel(overlay.root)
        root.title("Talkative")
        app_icon.set_window_icon(root)
        root.configure(bg=overlay_thread.bg_color())
        root.resizable(False, False)
        root.attributes("-topmost", True)

        key = friendly(config.HOTKEY)
        ttk.Label(
            root, padding=(16, 14, 16, 4), font=("Segoe UI", 11, "bold"),
            text="You're all set. Try it now" if first_run else "Test your microphone",
        ).pack(anchor="w")
        ttk.Label(
            root, padding=(16, 0, 16, 8), wraplength=440,
            text=f"Click into the box below, hold {key}, say a sentence, "
                 "then release the key. Your words will appear, and "
                 "Talkative checks how your microphone sounds.",
        ).pack(anchor="w")

        mic = ttk.Frame(root, padding=(16, 0, 16, 6))
        mic.pack(fill="x")
        ttk.Label(mic, text="Microphone").pack(anchor="w")
        values, names = [None], ["System default"]
        for index, name in audio_devices.inputs():
            values.append(index)
            names.append(name)
        default = mic_warmup.device_key(None)
        if default:
            # Which one that is: the user may not know Windows' choice.
            names[0] = "System default: " + next(
                (n for n in names[1:] if n.startswith(default)), default)
        current = _device()
        if current not in values:
            values.append(current)
            names.append(str(current))
        combo = ttk.Combobox(mic, values=names, state="readonly", width=50)
        combo.current(values.index(current))
        combo.pack(anchor="w", pady=(2, 2))
        speed = ttk.Label(mic, style="Muted.TLabel", wraplength=440, text="")
        speed.pack(anchor="w")

        def on_pick(_event=None):
            chosen = values[combo.current()]
            if chosen == _device():
                return
            try:
                if controller:
                    controller.set(chosen)
            except Exception:
                logging.getLogger(__name__).exception("microphone change failed")
            result.config(text="", foreground="")

        combo.bind("<<ComboboxSelected>>", on_pick)

        from . import palette
        dark = overlay_thread._effective_theme() == "dark"
        m = palette.get()["dark" if dark else "light"]
        text = tk.Text(root, height=5, width=50, wrap="word", font=("Segoe UI", 11),
                       relief="flat", borderwidth=0, highlightthickness=1,
                       bg=m["field"], fg=m["fg"], insertbackground=m["fg"],
                       highlightbackground=m["border"], highlightcolor=m["border"])
        text.pack(fill="both", expand=True, padx=16, pady=(4, 0))
        text.focus_set()
        result = ttk.Label(root, padding=(16, 8, 16, 0), wraplength=440, text="")
        result.pack(anchor="w")

        bar = ttk.Frame(root, padding=(16, 10, 16, 12))
        bar.pack(fill="x")
        ttk.Label(
            bar, style="Muted.TLabel",
            text="This works in any app: documents, chats, browsers." if first_run
            else "Change the microphone here or in Settings.",
        ).pack(side="left")

        def refresh():
            if _window is None:
                return
            try:
                speed.config(text=mic_check.startup_text(_device()))
            except Exception:
                pass
            root.after(1000, refresh)

        def close():
            global _window
            _window = None
            root.destroy()
            if first_run:
                _mark_done()

        ttk.Button(bar, text="Got it" if first_run else "Done", command=close).pack(side="right")
        root.protocol("WM_DELETE_WINDOW", close)
        _window = {"root": root, "result": result, "warn": "#fb923c" if dark else "#c2410c"}
        refresh()
    except Exception:
        logging.getLogger(__name__).exception("try-it-now box failed")
        _window = None
        if first_run:
            _mark_done()
