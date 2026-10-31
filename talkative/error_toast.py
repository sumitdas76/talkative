"""
Floating on-screen message: errors (e.g. "no editable field focused", why
a dictation wasn't typed) in red, and notices ("still working on it") in
a quiet dark style.

A small always-on-top red box that flashes near the text cursor and
disappears on its own after a few seconds -- no click needed, never steals
focus. Placed just above the line being typed in (screen_context.
caret_rect), or, when that can't be found, just above the listening line
at the bottom of the screen -- not at the mouse pointer, which is often
parked at the top of the screen (2026-10-28, user report: "Still
working" showed up where nobody looks).
A Windows tray balloon can be silently suppressed or routed straight to
Action Center; this can't be missed the way that can.

Also dismissible early: click the box, click anywhere else on screen, or
press Escape. The click/Escape dismiss is
implemented as global input hooks (same mechanism as the hotkey listener
in app.py), not window focus -- WS_EX_NOACTIVATE below means this window
is never activated and never receives real keyboard/mouse messages of its
own, so dismissal can't be wired the normal Tk-binding way for anything
off the box itself.

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

from pynput import keyboard, mouse

from . import overlay_thread, pill, screen_context

_WIDTH, _HEIGHT = 360, 60  # grows taller for a longer message
_DURATION_MS = 1500  # default; reasons a dictation wasn't typed stay longer
_GWL_EXSTYLE = -20
_WS_EX_NOACTIVATE = 0x08000000
_WS_EX_TOOLWINDOW = 0x00000080
_BG = "#c82828"  # same red as the tray's recording icon (tray.py)
_FG = "#ffffff"  # 5.5:1 on the red (black was 3.8:1)
_INFO_BG, _INFO_FG = "#22262e", "#ffffff"  # "still working" notices
_DISMISS = object()  # sentinel put on the command queue to hide early
_LOCATE_WAIT = 0.4  # seconds to find the text cursor before using the fallback spot
_GAP = 12  # pixels between the message and the line it points at


class _MonitorInfo(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.wintypes.DWORD), ("rcMonitor", ctypes.wintypes.RECT),
                ("rcWork", ctypes.wintypes.RECT), ("dwFlags", ctypes.wintypes.DWORD)]


def _work_area(x, y):
    """(left, top, right, bottom) of the work area of the monitor at x, y."""
    user32 = ctypes.windll.user32
    user32.MonitorFromPoint.restype = ctypes.c_void_p
    user32.GetMonitorInfoW.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    mon = user32.MonitorFromPoint(ctypes.wintypes.POINT(x, y), 2)  # nearest
    info = _MonitorInfo(cbSize=ctypes.sizeof(_MonitorInfo))
    if not mon or not user32.GetMonitorInfoW(mon, ctypes.byref(info)):
        raise OSError("no monitor info")
    w = info.rcWork
    return w.left, w.top, w.right, w.bottom


def _locate():
    """The text cursor's rectangle, or None if not found within _LOCATE_WAIT."""
    box = []
    worker = threading.Thread(target=lambda: box.append(screen_context.caret_rect()),
                              daemon=True)
    worker.start()
    worker.join(_LOCATE_WAIT)
    return box[0] if box else None


def place(rect, width, height, screen_w, screen_h, work=None):
    """Top-left (x, y) for a width x height message: just above `rect` (the
    text cursor), or below it when there's no room above; with no rect,
    just above the listening line. Kept inside `work` (the monitor's work
    area) when given, else the primary screen. Pure, for testing."""
    if rect is not None:
        left, top, right, bottom = rect
        x, y = left - 24, top - height - _GAP
        wl, wt, wr, wb = work or (0, 0, screen_w, screen_h)
        if y < wt + 8:
            y = bottom + _GAP
    else:
        x = (screen_w - width) // 2
        y = screen_h - pill._SCREEN_BOTTOM_MARGIN - pill._HEIGHT - _GAP - height
        wl, wt, wr, wb = work or (0, 0, screen_w, screen_h)
    x = max(wl + 8, min(x, wr - width - 8))
    y = max(wt + 8, min(y, wb - height - 8))
    return x, y


class _Toast:
    def __init__(self):
        self._commands = queue.Queue()
        self._seq = 0  # order of show() calls; the spot is found off-thread
        self._seq_lock = threading.Lock()
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

    def show(self, text, seconds=None, info=False, at_line=False):
        # Finding the text cursor is a UIA call into another app, which can
        # take a while: never on the caller's thread (it may be the
        # keyboard hook) and never on the overlay thread (the listening
        # line would stall).
        with self._seq_lock:
            self._seq += 1
            seq = self._seq

        def job():
            # at_line: about the listening line itself (a slow microphone),
            # so shown just above it, not at the text cursor.
            self._commands.put((text, seconds, info, None if at_line else _locate(), seq))
            # The poll loop stops while nothing is shown; the shared overlay
            # thread (which polls anyway) restarts it.
            self._overlay.build(self._wake)

        threading.Thread(target=job, daemon=True).start()

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
                highlightthickness=0, bd=0, bg=_BG,
            )
            self.canvas.pack()
            self.box = self.canvas.create_rectangle(0, 0, _WIDTH, _HEIGHT,
                                                    fill=_BG, outline="")
            self.text_id = self.canvas.create_text(
                _WIDTH / 2, _HEIGHT / 2, text="", fill=_FG,
                font=("Segoe UI", 10, "bold"), width=_WIDTH - 28,
            )
            # Clicking anywhere on the toast dismisses it early (no visible
            # button needed -- WS_EX_NOACTIVATE below still delivers mouse
            # clicks to the window; it only stops the window from stealing
            # keyboard focus/activation).
            self.canvas.bind("<Button-1>", lambda e: self._dismiss())
            self._hide_job = None
            self._mouse_listener = None
            self._key_listener = None
            self._polling = False
            self._height = _HEIGHT
            self._shown_seq = 0
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

    def _place(self, rect):
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        work = None
        if rect is not None:
            try:
                work = _work_area(rect[0], rect[1])
            except Exception:
                pass
        x, y = place(rect, _WIDTH, self._height, screen_w, screen_h, work)
        self.root.geometry(f"{_WIDTH}x{self._height}+{x}+{y}")

    def _wake(self):
        if not self._polling:
            self._polling = True
            self._poll()

    def _show(self, text, seconds, info, rect=None, seq=0):
        if seq < self._shown_seq:
            return  # a newer message is already up (found its spot sooner)
        self._shown_seq = seq
        bg, fg = (_INFO_BG, _INFO_FG) if info else (_BG, _FG)
        self.canvas.itemconfigure(self.text_id, text=text, fill=fg)
        x0, y0, x1, y1 = self.canvas.bbox(self.text_id)
        self._height = max(_HEIGHT, y1 - y0 + 26)
        self.canvas.configure(height=self._height, bg=bg)
        self.canvas.coords(self.box, 0, 0, _WIDTH, self._height)
        self.canvas.itemconfigure(self.box, fill=bg)
        self.canvas.coords(self.text_id, _WIDTH / 2, self._height / 2)
        self._place(rect)
        self.root.deiconify()
        self._no_activate()
        self._start_dismiss_listeners()
        if self._hide_job is not None:
            self.root.after_cancel(self._hide_job)
        ms = _DURATION_MS if seconds is None else int(seconds * 1000)
        self._hide_job = self.root.after(ms, self._hide)

    def _poll(self):
        try:
            while True:
                cmd = self._commands.get_nowait()
                if cmd is _DISMISS:
                    self._hide()
                    continue
                self._show(*cmd)
        except queue.Empty:
            pass
        if self._hide_job is not None:
            self.root.after(60, self._poll)
        else:
            self._polling = False  # nothing shown: wait for the next show()

    def _dismiss(self):
        """User-initiated early dismiss (click or Escape) -- routed through
        the command queue so it's handled on the overlay thread like
        everything else touching Tk objects."""
        self._commands.put(_DISMISS)

    def _start_dismiss_listeners(self):
        # Global hooks, same mechanism as the hotkey listener in app.py --
        # they don't require this window to have focus, so Escape/an
        # outside click can dismiss the toast without it ever stealing
        # keyboard focus from whatever the user is dictating into.
        if self._mouse_listener is None:
            self._mouse_listener = mouse.Listener(on_click=self._on_global_click)
            self._mouse_listener.start()
        if self._key_listener is None:
            self._key_listener = keyboard.Listener(on_press=self._on_global_key)
            self._key_listener.start()

    def _stop_dismiss_listeners(self):
        if self._mouse_listener is not None:
            self._mouse_listener.stop()
            self._mouse_listener = None
        if self._key_listener is not None:
            self._key_listener.stop()
            self._key_listener = None

    def _on_global_click(self, x, y, button, pressed):
        if pressed:
            self._dismiss()

    def _on_global_key(self, key):
        if key == keyboard.Key.esc:
            self._dismiss()

    def _hide(self):
        self.root.withdraw()
        self._hide_job = None
        self._stop_dismiss_listeners()


_toast = None
_lock = threading.Lock()


def _get():
    global _toast
    with _lock:
        if _toast is None:
            _toast = _Toast()
        return _toast


def show(text, seconds=None, info=False, at_line=False):
    """Flash `text` in a small topmost, non-activating box near the
    text cursor (or, with at_line=True, just above the listening line) for
    `seconds` (default 1.5), red, or dark with info=True.
    Safe from any thread; no-op on failure."""
    try:
        toast = _get()
        toast._ready.wait(timeout=3)
        if not toast._failed:
            toast.show(text, seconds, info, at_line)
    except Exception:
        pass
