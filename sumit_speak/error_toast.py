"""
Floating on-screen error message (e.g. "no editable field focused").

A small always-on-top red box that flashes near the cursor and disappears
on its own after a few seconds -- no click needed, never steals focus.
A Windows tray balloon can be silently suppressed or routed straight to
Action Center; this can't be missed the way that can.

Built as a tk.Toplevel on the shared overlay thread (see overlay_thread.py
-- multiple independent tk.Tk() roots across threads caused real crashes),
not its own Tk instance. The app talks to it only through show(text),
which is thread-safe and a no-op if the toast failed to start. Toast
problems must never break dictation.
"""

import ctypes
import ctypes.wintypes
import queue
import threading

from . import overlay_thread

_WIDTH, _HEIGHT = 360, 60
_DURATION_MS = 3500
_GWL_EXSTYLE = -20
_WS_EX_NOACTIVATE = 0x08000000
_WS_EX_TOOLWINDOW = 0x00000080


class _Toast:
    def __init__(self):
        self._commands = queue.Queue()
        self._ready = threading.Event()
        self._failed = False

        overlay = overlay_thread.get()
        overlay._ready.wait(timeout=3)
        if overlay._failed:
            self._failed = True
            self._ready.set()
            return
        self._overlay = overlay
        overlay.build(self._build)

    # ---- public, called from any thread ----

    def show(self, text):
        self._commands.put(text)

    # ---- overlay thread ----

    def _build(self):
        try:
            import tkinter as tk

            self.root = tk.Toplevel(self._overlay.root)
            self.root.withdraw()
            self.root.overrideredirect(True)
            self.root.attributes("-topmost", True)
            self.root.attributes("-alpha", 0.96)
            self.canvas = tk.Canvas(
                self.root, width=_WIDTH, height=_HEIGHT,
                highlightthickness=0, bg="#8a1f1f",
            )
            self.canvas.pack()
            self.canvas.create_rectangle(0, 0, _WIDTH, _HEIGHT,
                                         fill="#8a1f1f", outline="")
            self.text_id = self.canvas.create_text(
                _WIDTH / 2, _HEIGHT / 2, text="", fill="#ffffff",
                font=("Segoe UI", 10, "bold"), width=_WIDTH - 28,
            )
            self._hide_job = None
            self.root.after(60, self._poll)
            self._ready.set()
        except Exception:
            self._failed = True
            self._ready.set()

    def _no_activate(self):
        try:
            hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id()) or self.root.winfo_id()
            style = ctypes.windll.user32.GetWindowLongW(hwnd, _GWL_EXSTYLE)
            ctypes.windll.user32.SetWindowLongW(
                hwnd, _GWL_EXSTYLE,
                style | _WS_EX_NOACTIVATE | _WS_EX_TOOLWINDOW,
            )
        except Exception:
            pass

    def _place_near_cursor(self):
        try:
            point = ctypes.wintypes.POINT()
            ctypes.windll.user32.GetCursorPos(ctypes.byref(point))
            x, y = point.x - _WIDTH // 2, point.y - _HEIGHT - 24
        except Exception:
            x = y = 200
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        x = max(8, min(x, screen_w - _WIDTH - 8))
        y = max(8, min(y, screen_h - _HEIGHT - 8))
        self.root.geometry(f"{_WIDTH}x{_HEIGHT}+{x}+{y}")

    def _poll(self):
        try:
            while True:
                text = self._commands.get_nowait()
                self.canvas.itemconfigure(self.text_id, text=text)
                self._place_near_cursor()
                self.root.deiconify()
                self._no_activate()
                if self._hide_job is not None:
                    self.root.after_cancel(self._hide_job)
                self._hide_job = self.root.after(_DURATION_MS, self._hide)
        except queue.Empty:
            pass
        self.root.after(60, self._poll)

    def _hide(self):
        self.root.withdraw()
        self._hide_job = None


_toast = None
_lock = threading.Lock()


def _get():
    global _toast
    with _lock:
        if _toast is None:
            _toast = _Toast()
        return _toast


def show(text):
    """Flash `text` in a small topmost, non-activating box near the
    cursor for a few seconds. Safe from any thread; no-op on failure."""
    try:
        toast = _get()
        toast._ready.wait(timeout=3)
        if not toast._failed:
            toast.show(text)
    except Exception:
        pass
