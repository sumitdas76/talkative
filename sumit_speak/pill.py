"""
Floating "listening" pill (spec section 10.1).

A small always-on-top capsule that appears near the cursor while recording:
a red dot plus live audio-level bars, so the user can see the app is
hearing them. Disappears on release. It must never steal keyboard focus
(the user is mid-dictation into another window) -- the window gets
WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW, no taskbar entry, and is never
focused.

Built as a tk.Toplevel on the shared overlay thread (see overlay_thread.py
-- multiple independent tk.Tk() roots across threads caused real crashes),
not its own Tk instance. The app talks to it only through
show(level_source) / hide(), which are thread-safe and no-ops if the pill
failed to start. Pill problems must never break dictation.
"""

import ctypes
import ctypes.wintypes
import queue
import threading

from . import overlay_thread

_SCALE = 0.8  # sized down 20% at the user's request, July 20 2026
# Width widened from the original 172 (2026-08-23) to fit the live-preview
# text row added below the bars; _TEXT_HEIGHT reserves that row. The row is
# always built, even when live preview is off/empty, to avoid the
# complexity of resizing a live Tk canvas per recording -- it's just blank
# space in that case.
_WIDTH, _HEIGHT = round(210 * _SCALE), round(40 * _SCALE)
_TEXT_HEIGHT = round(54 * _SCALE)
_TOTAL_HEIGHT = _HEIGHT + _TEXT_HEIGHT
_BARS = 12
_DOT_MARGIN = round(14 * _SCALE)
_DOT_DIAM = round(12 * _SCALE)
_BAR_X0 = round(38 * _SCALE)
_BAR_RIGHT_MARGIN = round(16 * _SCALE)
_BAR_HALF_MIN = round(2 * _SCALE)
_BAR_MAX_MARGIN = round(8 * _SCALE)
_CURSOR_OFFSET_X = round(18 * _SCALE)
_CURSOR_OFFSET_Y = round(24 * _SCALE)
_SCREEN_BOTTOM_MARGIN = round(48 * _SCALE)
# Chroma-key color: anything painted this exact color becomes fully
# see-through (Windows-only Tk feature), so the canvas's own rectangular
# shape doesn't show as a box around the rounded capsule. Picked to not
# collide with any color actually used in the pill's drawing.
_TRANSPARENT_KEY = "#ff00fe"
_GWL_EXSTYLE = -20
_WS_EX_NOACTIVATE = 0x08000000
_WS_EX_TOOLWINDOW = 0x00000080


class _Pill:
    def __init__(self):
        self._commands = queue.Queue()
        self._level_source = None
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

    def show(self, level_source):
        self._level_source = level_source
        self._commands.put(("show", None))

    def hide(self):
        self._commands.put(("hide", None))

    def set_preview(self, text):
        self._commands.put(("preview", text))

    # ---- overlay thread ----

    def _build(self):
        try:
            import tkinter as tk

            self.root = tk.Toplevel(self._overlay.root)
            self.root.withdraw()
            self.root.overrideredirect(True)
            self.root.attributes("-topmost", True)
            self.root.attributes("-alpha", 0.93)
            self.root.attributes("-transparentcolor", _TRANSPARENT_KEY)
            self.root.configure(bg=_TRANSPARENT_KEY)
            self.canvas = tk.Canvas(
                self.root, width=_WIDTH, height=_TOTAL_HEIGHT,
                highlightthickness=0, bg=_TRANSPARENT_KEY,
            )
            self.canvas.pack()
            # Capsule background (rounded top, matching the original pill
            # shape) plus a flush, square-cornered ledge below it for the
            # live-preview text row.
            r = _HEIGHT // 2
            self.canvas.create_oval(0, 0, 2 * r, _HEIGHT, fill="#202020", outline="")
            self.canvas.create_oval(_WIDTH - 2 * r, 0, _WIDTH, _HEIGHT,
                                    fill="#202020", outline="")
            self.canvas.create_rectangle(r, 0, _WIDTH - r, _HEIGHT,
                                         fill="#202020", outline="")
            self.canvas.create_rectangle(r, _HEIGHT, _WIDTH - r, _TOTAL_HEIGHT,
                                         fill="#202020", outline="")
            self.preview_text = self.canvas.create_text(
                r + 6, _HEIGHT + 4, anchor="nw", width=_WIDTH - 2 * r - 12,
                fill="#cccccc", font=("Segoe UI", 8), justify="left", text="",
            )
            self.dot = self.canvas.create_oval(
                _DOT_MARGIN, _DOT_MARGIN,
                _DOT_MARGIN + _DOT_DIAM, _DOT_MARGIN + _DOT_DIAM,
                fill="#c82828", outline="",
            )
            self.bars = []
            x0 = _BAR_X0
            width = (_WIDTH - x0 - _BAR_RIGHT_MARGIN) / _BARS
            for i in range(_BARS):
                x = x0 + i * width
                bar = self.canvas.create_rectangle(
                    x + 1, _HEIGHT / 2 - _BAR_HALF_MIN,
                    x + width - 1, _HEIGHT / 2 + _BAR_HALF_MIN,
                    fill="#5a8fd8", outline="",
                )
                self.bars.append(bar)
            self._history = [0.0] * _BARS
            self._visible = False
            self.root.after(40, self._tick)
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
            x, y = point.x + _CURSOR_OFFSET_X, point.y + _CURSOR_OFFSET_Y
        except Exception:
            x = y = 200
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        x = max(8, min(x, screen_w - _WIDTH - 8))
        y = max(8, min(y, screen_h - _TOTAL_HEIGHT - _SCREEN_BOTTOM_MARGIN))
        self.root.geometry(f"{_WIDTH}x{_TOTAL_HEIGHT}+{x}+{y}")

    def _tick(self):
        try:
            while True:
                kind, payload = self._commands.get_nowait()
                if kind == "show" and not self._visible:
                    self._history = [0.0] * _BARS
                    self.canvas.itemconfigure(self.preview_text, text="")
                    self._place_near_cursor()
                    self.root.deiconify()
                    self._no_activate()
                    self._visible = True
                elif kind == "hide" and self._visible:
                    self.root.withdraw()
                    self._visible = False
                elif kind == "preview" and self._visible:
                    self.canvas.itemconfigure(self.preview_text, text=payload)
        except queue.Empty:
            pass

        if self._visible:
            source = self._level_source
            level = 0.0
            if source is not None:
                try:
                    level = min(1.0, source() * 12)  # speech RMS is small
                except Exception:
                    pass
            self._history = self._history[1:] + [level]
            mid = _HEIGHT / 2
            for bar, value in zip(self.bars, self._history):
                half = _BAR_HALF_MIN + value * (mid - _BAR_MAX_MARGIN)
                x0, _, x1, _ = self.canvas.coords(bar)
                self.canvas.coords(bar, x0, mid - half, x1, mid + half)
            # Blink the dot gently.
            import time

            on = int(time.time() * 2) % 2 == 0
            self.canvas.itemconfigure(self.dot, fill="#c82828" if on else "#802020")

        self.root.after(40, self._tick)


_pill = None
_lock = threading.Lock()


def _get():
    global _pill
    with _lock:
        if _pill is None:
            _pill = _Pill()
        return _pill


def show(level_source):
    """Show the pill; level_source is a zero-arg callable returning the
    current input RMS. Safe from any thread; no-op on failure."""
    try:
        pill = _get()
        pill._ready.wait(timeout=3)
        if not pill._failed:
            pill.show(level_source)
    except Exception:
        pass


def hide():
    try:
        pill = _get()
        if not pill._failed:
            pill.hide()
    except Exception:
        pass


def set_preview(text):
    """Update the live-preview text row; no-op if the pill isn't visible or
    failed to start. Safe from any thread."""
    try:
        pill = _get()
        if not pill._failed:
            pill.set_preview(text)
    except Exception:
        pass
