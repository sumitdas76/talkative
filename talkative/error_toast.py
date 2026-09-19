"""
Floating on-screen error message (e.g. "no editable field focused").

A small always-on-top red box that flashes near the cursor and disappears
on its own after a few seconds -- no click needed, never steals focus.
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

from . import overlay_thread

_WIDTH, _HEIGHT = 360, 60
_DURATION_MS = 1500
_GWL_EXSTYLE = -20
_WS_EX_NOACTIVATE = 0x08000000
_WS_EX_TOOLWINDOW = 0x00000080
_BG = "#c82828"  # same red as the tray's recording icon (tray.py)
_FG = "#000000"
_DISMISS = object()  # sentinel put on the command queue to hide early


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
                highlightthickness=0, bd=0, bg=_BG,
            )
            self.canvas.pack()
            self.canvas.create_rectangle(0, 0, _WIDTH, _HEIGHT,
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
                cmd = self._commands.get_nowait()
                if cmd is _DISMISS:
                    self._hide()
                    continue
                self.canvas.itemconfigure(self.text_id, text=cmd)
                self._place_near_cursor()
                self.root.deiconify()
                self._no_activate()
                self._start_dismiss_listeners()
                if self._hide_job is not None:
                    self.root.after_cancel(self._hide_job)
                self._hide_job = self.root.after(_DURATION_MS, self._hide)
        except queue.Empty:
            pass
        self.root.after(60, self._poll)

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
