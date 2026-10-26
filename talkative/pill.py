"""
Floating "listening" pill (spec section 10.1).

A small always-on-top capsule fixed at the bottom-center of the screen
while recording: a red dot plus live audio-level bars, so the user can see
the app is hearing them. Disappears on release. It must never steal
keyboard focus (the user is mid-dictation into another window) -- the
window gets WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW, no taskbar entry, and is
never focused.

Built as a tk.Toplevel on the shared overlay thread (see overlay_thread.py
-- multiple independent tk.Tk() roots across threads caused real crashes),
not its own Tk instance. The app talks to it only through
show(level_source) / hide(), which are thread-safe and no-ops if the pill
failed to start. Pill problems must never break dictation.
"""

import ctypes
import math
import queue
import threading
import time

from . import overlay_thread, palette

_SCALE = 0.8  # sized down 20% at the user's request, July 20 2026
_WIDTH, _HEIGHT = round(172 * _SCALE), round(40 * _SCALE)
_DOT_X = round(20 * _SCALE)  # center of the recording dot
_DOT_R = round(5 * _SCALE)
_RING_MAX = round(11 * _SCALE)  # the pulse ring grows to this radius
_BARS = 15  # odd: one center bar, the rest mirrored around it
_BAR_X0 = round(40 * _SCALE)
_BAR_RIGHT_MARGIN = round(14 * _SCALE)
_BAR_WIDTH = max(2, round(3.5 * _SCALE))
_BAR_HALF_MIN = round(1.5 * _SCALE)
_BAR_MAX_MARGIN = round(4.5 * _SCALE)
_SCREEN_BOTTOM_MARGIN = round(48 * _SCALE)
_TICK_MS = 33  # ~30 frames a second, only while recording
# Colors come from palette.py (redesigned 2026-10-26, user request: "a
# cooler animation"); read when the pill is built.
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
        self._commands.put("show")
        # The drawing loop stops while hidden; the shared overlay thread
        # (which polls anyway) restarts it.
        self._overlay.build(self._wake)

    def hide(self):
        self._commands.put("hide")

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
                self.root, width=_WIDTH, height=_HEIGHT,
                highlightthickness=0, bg=_TRANSPARENT_KEY,
            )
            self.canvas.pack()
            # Capsule background (colored by _recolor).
            r = _HEIGHT // 2
            self.capsule = [
                self.canvas.create_oval(0, 0, 2 * r, _HEIGHT, outline=""),
                self.canvas.create_oval(_WIDTH - 2 * r, 0, _WIDTH, _HEIGHT, outline=""),
                self.canvas.create_rectangle(r, 0, _WIDTH - r, _HEIGHT, outline=""),
            ]
            mid = _HEIGHT / 2
            self.ring = self.canvas.create_oval(0, 0, 0, 0, width=2)
            self.dot = self.canvas.create_oval(
                _DOT_X - _DOT_R, mid - _DOT_R, _DOT_X + _DOT_R, mid + _DOT_R,
                outline="",
            )
            # Rounded bars (lines with round caps), mirrored around the
            # center one: the newest level drives the center and older ones
            # ripple outwards.
            self.bars = []
            step = (_WIDTH - _BAR_X0 - _BAR_RIGHT_MARGIN) / (_BARS - 1)
            for i in range(_BARS):
                x = _BAR_X0 + i * step
                bar = self.canvas.create_line(
                    x, mid - _BAR_HALF_MIN, x, mid + _BAR_HALF_MIN,
                    width=_BAR_WIDTH, capstyle="round",
                )
                self.bars.append((bar, x))
            self._recolor()
            self._history = [0.0] * (_BARS // 2 + 1)
            self._level = 0.0
            self._shown_at = 0.0
            self._visible = False
            self._ticking = False
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

    def _place_bottom_center(self):
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        x = (screen_w - _WIDTH) // 2
        y = screen_h - _HEIGHT - _SCREEN_BOTTOM_MARGIN
        self.root.geometry(f"{_WIDTH}x{_HEIGHT}+{x}+{y}")

    def _recolor(self):
        """Colors from the current scheme; re-read on every show, so a
        scheme picked in Settings applies from the next dictation."""
        pal = palette.get()
        self._bg, self._dot_color = pal["pill_bg"], pal["pill_dot"]
        for item in self.capsule:
            self.canvas.itemconfigure(item, fill=self._bg)
        self.canvas.itemconfigure(self.dot, fill=self._dot_color)
        self._bar_colors = [gradient_color(i / (_BARS - 1), pal["pill_bars"])
                            for i in range(_BARS)]

    def _wake(self):
        if not self._ticking:
            self._ticking = True
            self._tick()

    def _tick(self):
        try:
            while True:
                cmd = self._commands.get_nowait()
                if cmd == "show" and not self._visible:
                    self._history = [0.0] * len(self._history)
                    self._level = 0.0
                    self._shown_at = time.time()
                    self._recolor()
                    self._place_bottom_center()
                    self.root.deiconify()
                    self._no_activate()
                    self._visible = True
                elif cmd == "hide" and self._visible:
                    self.root.withdraw()
                    self._visible = False
        except queue.Empty:
            pass

        if self._visible:
            self._draw(time.time() - self._shown_at)
            self.root.after(_TICK_MS, self._tick)
        else:
            # Hidden: stop until the next show() (_wake), so the pill costs
            # nothing between dictations.
            self._ticking = False

    def _draw(self, t):
        source = self._level_source
        target = 0.0
        if source is not None:
            try:
                target = min(1.0, source() * 12)  # speech RMS is small
            except Exception:
                pass
        # Quick to rise, slower to fall, so speech looks smooth, not jumpy.
        rate = 0.55 if target > self._level else 0.18
        self._level += (target - self._level) * rate
        self._history = [self._level] + self._history[:-1]

        mid = _HEIGHT / 2
        room = mid - _BAR_MAX_MARGIN
        center = _BARS // 2
        for i, ((bar, x), color) in enumerate(zip(self.bars, self._bar_colors)):
            k = abs(i - center)
            # Taller in the middle; a slow wave keeps it alive in pauses.
            shape = 1.0 - 0.45 * (k / center) ** 2
            idle = 0.07 * (1 + math.sin(t * 5 - k * 0.8)) / 2
            value = min(1.0, self._history[k] * shape + idle)
            half = _BAR_HALF_MIN + value * room
            self.canvas.coords(bar, x, mid - half, x, mid + half)
            self.canvas.itemconfigure(bar, fill=_mix(color, "#ffffff", 0.35 * self._history[k]))

        # The dot breathes, and a ring pulses out from it once a second.
        phase = (t % 1.0)
        r = _DOT_R + 0.8 * math.sin(t * math.tau)
        self.canvas.coords(self.dot, _DOT_X - r, mid - r, _DOT_X + r, mid + r)
        ring = _DOT_R + phase * (_RING_MAX - _DOT_R)
        self.canvas.coords(self.ring, _DOT_X - ring, mid - ring, _DOT_X + ring, mid + ring)
        self.canvas.itemconfigure(self.ring, outline=_mix(self._dot_color, self._bg, phase))


def _rgb(color):
    return tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))


def _mix(a, b, amount):
    """Color `amount` (0-1) of the way from a to b."""
    ra, rb = _rgb(a), _rgb(b)
    return "#%02x%02x%02x" % tuple(round(x + (y - x) * amount) for x, y in zip(ra, rb))


def gradient_color(pos, stops):
    """The color at pos 0-1 along `stops`."""
    pos = min(1.0, max(0.0, pos)) * (len(stops) - 1)
    i = min(int(pos), len(stops) - 2)
    return _mix(stops[i], stops[i + 1], pos - i)


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
