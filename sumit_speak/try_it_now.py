"""
First-run "try it now" box (spec sections 8 and 10.2).

Shown once, after the speech model is ready on the very first run: a small
window with a text box inviting the user to hold the hotkey and say
anything. Their first dictation lands here -- a controlled place where
success is visible -- instead of in some arbitrary app where a
non-editable field would greet them with an error popup.

Built as a tk.Toplevel on the shared overlay thread (see overlay_thread.py
-- multiple independent tk.Tk() roots across threads caused real
crashes), not its own Tk instance. Closing it (or clicking "Got it")
records first_run_done so it never appears again.
"""

import threading

from . import app_icon, config, overlay_thread, settings
from .keynames import friendly

_opened = False
_lock = threading.Lock()


def maybe_show():
    """Show the box if this is the first run; otherwise do nothing."""
    global _opened
    if config.FIRST_RUN_DONE:
        return
    with _lock:
        if _opened:
            return
        _opened = True

    overlay = overlay_thread.get()
    overlay._ready.wait(timeout=3)
    if overlay._failed:
        _mark_done()
        return
    overlay.build(lambda: _build(overlay))


def _mark_done():
    try:
        config.FIRST_RUN_DONE = True
        settings.save({"first_run_done": True})
    except Exception:
        pass


def _build(overlay):
    try:
        import tkinter as tk
        from tkinter import ttk

        root = tk.Toplevel(overlay.root)
        root.title("Sumit Speak")
        app_icon.set_window_icon(root)
        root.geometry("460x300")
        root.resizable(False, False)
        root.attributes("-topmost", True)

        key = friendly(config.HOTKEY)
        ttk.Label(
            root, padding=(16, 14, 16, 4), font=("Segoe UI", 11, "bold"),
            text="You're all set — try it now",
        ).pack(anchor="w")
        ttk.Label(
            root, padding=(16, 0, 16, 8), wraplength=420,
            text=f"Click into the box below, hold {key}, say anything, "
                 "then release the key. Your words will appear.",
        ).pack(anchor="w")
        text = tk.Text(root, height=6, wrap="word", font=("Segoe UI", 11),
                       relief="solid", borderwidth=1)
        text.pack(fill="both", expand=True, padx=16)
        text.focus_set()
        bar = ttk.Frame(root, padding=(16, 10, 16, 12))
        bar.pack(fill="x")
        ttk.Label(
            bar, foreground="grey",
            text="This works in any app — documents, chats, browsers.",
        ).pack(side="left")

        def close():
            root.destroy()
            _mark_done()

        ttk.Button(bar, text="Got it", command=close).pack(side="right")
        root.protocol("WM_DELETE_WINDOW", close)
    except Exception:
        _mark_done()
