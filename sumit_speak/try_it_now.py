"""
First-run "try it now" box (spec sections 8 and 10.2).

Shown once, after the speech model is ready on the very first run: a small
window with a text box inviting the user to hold the hotkey and say
anything. Their first dictation lands here -- a controlled place where
success is visible -- instead of in some arbitrary app where a
non-editable field would greet them with an error popup.

Own thread + Tk instance, same pattern as the settings window. Closing it
(or clicking "Got it") records first_run_done so it never appears again.
"""

import threading

from . import config, settings
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
    threading.Thread(target=_run, daemon=True).start()


def _run():
    try:
        import tkinter as tk
        from tkinter import ttk

        root = tk.Tk()
        root.title("Sumit Speak")
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
        ttk.Button(bar, text="Got it", command=root.destroy).pack(side="right")
        root.protocol("WM_DELETE_WINDOW", root.destroy)
        root.mainloop()
    except Exception:
        pass
    finally:
        try:
            config.FIRST_RUN_DONE = True
            settings.save({"first_run_done": True})
        except Exception:
            pass
