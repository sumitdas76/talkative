"""
Floating "listening" pill (spec section 10.1).

A small always-on-top capsule that appears near the cursor while recording:
a red dot plus live audio-level bars, so the user can see the app is
hearing them. Disappears on release. It must never steal keyboard focus
(the user is mid-dictation into another window) -- the window gets
WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW, no taskbar entry, and is never
focused.

Runs a dedicated Tk instance on its own daemon thread; the app talks to it
only through show(level_source) / hide(), which are thread-safe and no-ops
if the pill failed to start. Pill problems must never break dictation.
"""

import ctypes
import ctypes.wintypes
import queue
import threading

_WIDTH, _HEIGHT = 172, 40
_BARS = 12
_GWL_EXSTYLE = -20
_WS_EX_NOACTIVATE = 0x08000000
_WS_EX_TOOLWINDOW = 0x00000080


class _PillThread:
    def __init__(self):
        self._commands = queue.Queue()
        self._level_source = None
        self._ready = threading.Event()
        self._failed = False
        threading.Thread(target=self._run, daemon=True).start()

    # ---- public, called from any thread ----

    def show(self, level_source):
        self._level_source = level_source
        self._commands.put("show")

    def hide(self):
        self._commands.put("hide")

    # ---- pill thread ----

    def _run(self):
        try:
            import tkinter as tk

            self.root = tk.Tk()
            self.root.withdraw()
            self.root.overrideredirect(True)
            self.root.attributes("-topmost", True)
            self.root.attributes("-alpha", 0.93)
            self.canvas = tk.Canvas(
                self.root, width=_WIDTH, height=_HEIGHT,
                highlightthickness=0, bg="#f0f0f0",
            )
            self.canvas.pack()
            # Capsule background.
            r = _HEIGHT // 2
            self.canvas.create_oval(0, 0, 2 * r, _HEIGHT, fill="#202020", outline="")
            self.canvas.create_oval(_WIDTH - 2 * r, 0, _WIDTH, _HEIGHT,
                                    fill="#202020", outline="")
            self.canvas.create_rectangle(r, 0, _WIDTH - r, _HEIGHT,
                                         fill="#202020", outline="")
            self.dot = self.canvas.create_oval(14, 14, 26, 26,
                                               fill="#c82828", outline="")
            self.bars = []
            x0 = 38
            width = (_WIDTH - x0 - 16) / _BARS
            for i in range(_BARS):
                x = x0 + i * width
                bar = self.canvas.create_rectangle(
                    x + 1, _HEIGHT / 2 - 2, x + width - 1, _HEIGHT / 2 + 2,
                    fill="#5a8fd8", outline="",
                )
                self.bars.append(bar)
            self._history = [0.0] * _BARS
            self._visible = False
            self.root.after(40, self._tick)
            self._ready.set()
            self.root.mainloop()
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
            x, y = point.x + 18, point.y + 24
        except Exception:
            x = y = 200
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        x = max(8, min(x, screen_w - _WIDTH - 8))
        y = max(8, min(y, screen_h - _HEIGHT - 48))
        self.root.geometry(f"{_WIDTH}x{_HEIGHT}+{x}+{y}")

    def _tick(self):
        try:
            while True:
                cmd = self._commands.get_nowait()
                if cmd == "show" and not self._visible:
                    self._history = [0.0] * _BARS
                    self._place_near_cursor()
                    self.root.deiconify()
                    self._no_activate()
                    self._visible = True
                elif cmd == "hide" and self._visible:
                    self.root.withdraw()
                    self._visible = False
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
                half = 2 + value * (mid - 8)
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
            _pill = _PillThread()
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
