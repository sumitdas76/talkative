"""
One-time "you're on Cloud" notice.

Talkative ships defaulting to Cloud processing mode (config.PROCESSING_MODE)
so there's nothing to download before first use. Shown once, the first
time Cloud mode actually activates, explaining that in plain language and
pointing at where to download Local models instead. A separate module from
try_it_now.py (not a generic notice framework) -- same small-dedicated-
module habit as the rest of this codebase.

Built as a tk.Toplevel on the shared overlay thread (see overlay_thread.py
-- multiple independent tk.Tk() roots across threads caused real crashes),
not its own Tk instance. Closing it (or clicking "Got it") records
CLOUD_NOTICE_DONE so it never appears again.
"""

import threading

from . import app_icon, config, overlay_thread, settings

_opened = False
_lock = threading.Lock()


def maybe_show():
    """Show the notice if it hasn't been shown before; otherwise do nothing."""
    global _opened
    if config.CLOUD_NOTICE_DONE:
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
        config.CLOUD_NOTICE_DONE = True
        settings.save({"cloud_notice_done": True})
    except Exception:
        pass


def _build(overlay):
    try:
        import tkinter as tk
        from tkinter import ttk

        root = tk.Toplevel(overlay.root)
        root.title("Talkative")
        app_icon.set_window_icon(root)
        root.geometry("460x260")
        root.resizable(False, False)
        root.attributes("-topmost", True)

        ttk.Label(
            root, padding=(16, 14, 16, 4), font=("Segoe UI", 11, "bold"),
            text="Talkative is running via Cloud",
        ).pack(anchor="w")
        ttk.Label(
            root, padding=(16, 0, 16, 8), wraplength=420,
            text="Nothing to download -- your dictation is processed on a "
                 "remote server instead of this device.",
        ).pack(anchor="w")
        ttk.Label(
            root, padding=(16, 0, 16, 0), wraplength=420,
            text="Prefer everything to stay on your PC? You can download "
                 "the voice and grammar models any time from Settings -> "
                 "General -> Processing.",
        ).pack(anchor="w")

        bar = ttk.Frame(root, padding=(16, 14, 16, 12))
        bar.pack(fill="x", side="bottom")

        def close():
            root.destroy()
            _mark_done()

        ttk.Button(bar, text="Got it", command=close).pack(side="right")
        root.protocol("WM_DELETE_WINDOW", close)
    except Exception:
        _mark_done()
