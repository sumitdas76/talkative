"""
Floating "listening" indicator (spec section 10.1).

Since 2026-10-26 a single thin line, like a heart monitor's trace, near
the bottom-center of the screen while recording (user request: "a
minimalistic analogue line like a heartbeat ... instead of an entire pill
animation"; it replaced a capsule with a red dot and level bars). Flat
with a faint ripple while the user is quiet; speech scrolls in from the
right as a wave whose height follows the voice. After release it stays
as a dimmed flat line with a bright streak sweeping along it while the
dictation is processed (busy()), and goes when the text is typed or the
reason it wasn't has been shown (done()) -- added 2026-10-27, user
report: up to 10 s and more with nothing on screen.
It must never steal keyboard focus (the user is mid-dictation into
another window) -- the window gets WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW,
no taskbar entry, and is never focused.

Built as a tk.Toplevel on the shared overlay thread (see overlay_thread.py
-- multiple independent tk.Tk() roots across threads caused real crashes),
not its own Tk instance. The app talks to it only through
show(level_source) / hide(), which are thread-safe and no-ops if the
indicator failed to start. Its problems must never break dictation.
"""

import ctypes
import math
import queue
import random
import threading
import time

from . import overlay_thread, palette

_SCALE = 0.8  # sized down 20% at the user's request, July 20 2026
_WIDTH, _HEIGHT = round(172 * _SCALE), round(40 * _SCALE)
_POINTS = 46  # along the line; the newest enters at the right
_EDGE = 3  # pixels kept clear at each end for the halo
_LINE_WIDTH = 2
_HALO_WIDTH = 4  # dark outline under the line, so it shows on light windows
_CYCLE = 7  # points per wave: an analogue sine, not a point-to-point zigzag
_SCREEN_BOTTOM_MARGIN = round(48 * _SCALE)
_TICK_MS = 40  # 25 frames a second, only while recording
_ALERT = "#ef4444"  # the line turns red when the microphone or Cloud fails
# Chroma-key color: anything painted this exact color becomes fully
# see-through (Windows-only Tk feature), so only the line itself shows.
# Picked to not collide with any color actually used in the drawing.
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

    def busy(self):
        self._commands.put("busy")
        self._overlay.build(self._wake)

    def done(self):
        self._commands.put("done")

    def alert(self):
        self._commands.put("alert")

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
            self.root.attributes("-transparentcolor", _TRANSPARENT_KEY)
            self.root.configure(bg=_TRANSPARENT_KEY)
            self.canvas = tk.Canvas(
                self.root, width=_WIDTH, height=_HEIGHT,
                highlightthickness=0, bg=_TRANSPARENT_KEY,
            )
            self.canvas.pack()
            # Colors come from palette.py (_recolor). The halo is the same
            # line, wider and dark, underneath.
            flat = self._flat()
            self.halo = self.canvas.create_line(
                *flat, width=_HALO_WIDTH, smooth=True, capstyle="round", joinstyle="round")
            self.line = self.canvas.create_line(
                *flat, width=_LINE_WIDTH, smooth=True, capstyle="round", joinstyle="round")
            # The streak that sweeps along the flat line while processing.
            self.sweep = self.canvas.create_line(
                0, 0, 0, 0, width=_LINE_WIDTH + 1, capstyle="round", state="hidden")
            self._mode = "listen"
            self._alert = False
            self._recolor()
            self._wave = [0.0] * _POINTS
            self._level = 0.0
            self._phase = 0.0
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
        busy = self._mode == "busy"
        color = _ALERT if self._alert else pal["line"]
        self.canvas.itemconfigure(
            self.line, fill=_mix(color, pal["line_halo"], 0.55) if busy else color)
        self.canvas.itemconfigure(self.halo, fill=pal["line_halo"])
        self.canvas.itemconfigure(self.sweep, fill=_mix(pal["line"], "#ffffff", 0.35),
                                  state="normal" if busy else "hidden")

    def _flat(self):
        step = (_WIDTH - 2 * _EDGE) / (_POINTS - 1)
        mid = _HEIGHT / 2
        coords = []
        for i in range(_POINTS):
            coords += [_EDGE + i * step, mid]
        return coords

    def _wake(self):
        if not self._ticking:
            self._ticking = True
            self._tick()

    def _tick(self):
        try:
            while True:
                cmd = self._commands.get_nowait()
                if cmd == "alert":
                    self._alert = True
                    self._recolor()
                    continue
                if cmd in ("show", "busy"):
                    mode = "listen" if cmd == "show" else "busy"
                    if cmd == "show" and not (self._visible and self._mode == "listen"):
                        self._alert = False  # a new dictation starts clean
                    if mode != self._mode or not self._visible:
                        self._mode = mode
                        self._wave = [0.0] * _POINTS
                        self._level = 0.0
                        self._shown_at = time.time()
                        self._recolor()
                    if not self._visible:
                        self._place_bottom_center()
                        self.root.deiconify()
                        self._no_activate()
                        self._visible = True
                elif self._visible and (cmd == "hide" or (cmd == "done" and self._mode == "busy")):
                    # "done" never hides a new dictation's listening line.
                    self.root.withdraw()
                    self._visible = False
        except queue.Empty:
            pass

        if self._visible:
            self._draw(time.time() - self._shown_at)
            self.root.after(_TICK_MS, self._tick)
        else:
            # Hidden: stop until the next show() (_wake), so it costs
            # nothing between dictations.
            self._ticking = False

    def _draw(self, t):
        if self._mode == "busy":
            self._draw_busy(t)
            return
        source = self._level_source
        target = 0.0
        if source is not None:
            try:
                target = min(1.0, source() * 20)  # speech RMS is small
            except Exception:
                pass
        # Quick to rise, slower to fall, so speech looks smooth, not jumpy.
        rate = 0.55 if target > self._level else 0.18
        self._level += (target - self._level) * rate
        # A sine wave whose height follows the voice (a little uneven, like
        # a real trace); new points enter at the right, older ones scroll
        # left.
        self._phase += math.tau / _CYCLE
        swing = math.sin(self._phase) * self._level * (0.75 + 0.25 * random.random())
        self._wave = self._wave[1:] + [swing]

        mid = _HEIGHT / 2
        room = mid - _HALO_WIDTH
        step = (_WIDTH - 2 * _EDGE) / (_POINTS - 1)
        coords = []
        for i, value in enumerate(self._wave):
            # Fades out over the left half as it scrolls away, and eases in
            # over the last few points so the right end isn't a hard edge;
            # a faint slow ripple keeps it alive in pauses.
            fade = (math.sin(math.pi / 2 * min(1.0, i / (_POINTS * 0.45)))
                    * min(1.0, 0.35 + (_POINTS - 1 - i) / 4))
            idle = 0.06 * math.sin(t * 4 - i * 0.35)
            coords += [_EDGE + i * step, mid - (value + idle) * fade * room]
        self.canvas.coords(self.halo, *coords)
        self.canvas.coords(self.line, *coords)


    def _draw_busy(self, t):
        """Flat line, a bright streak sweeping left to right about once a
        second -- "working on it"."""
        mid = _HEIGHT / 2
        self.canvas.coords(self.halo, *self._flat())
        self.canvas.coords(self.line, *self._flat())
        span = _WIDTH - 2 * _EDGE
        head = (t * 0.9 % 1.3) - 0.15  # runs a little past both ends
        x0 = _EDGE + max(0.0, head - 0.22) * span
        x1 = _EDGE + min(1.0, max(0.0, head)) * span
        if x1 - x0 < 2:
            x0 = x1 = -10  # between sweeps: off the canvas
        self.canvas.coords(self.sweep, x0, mid, x1, mid)


def _rgb(color):
    return tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))


def _mix(a, b, amount):
    """Color `amount` (0-1) of the way from a to b."""
    ra, rb = _rgb(a), _rgb(b)
    return "#%02x%02x%02x" % tuple(round(x + (y - x) * amount) for x, y in zip(ra, rb))


_pill = None
_lock = threading.Lock()


def _get():
    global _pill
    with _lock:
        if _pill is None:
            _pill = _Pill()
        return _pill


def show(level_source):
    """Show the line; level_source is a zero-arg callable returning the
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


def alert():
    """Something is wrong with this dictation (app._live_problem): red line."""
    try:
        pill = _get()
        if not pill._failed:
            pill.alert()
    except Exception:
        pass


def busy():
    """After release: the line shows the dictation is being processed."""
    try:
        pill = _get()
        if not pill._failed:
            pill.busy()
    except Exception:
        pass


def done():
    """Processing finished: hide, unless a new dictation is listening."""
    try:
        pill = _get()
        if not pill._failed:
            pill.done()
    except Exception:
        pass
