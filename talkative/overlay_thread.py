"""
Shared background Tk thread for floating, always-on-top overlays (the
listening pill, the error toast).

A process should have at most one tk.Tk() root. Tcl/Tk's threading model
is fragile when multiple independent interpreters run concurrently on
different threads in the same process -- pill.py and error_toast.py used
to each create their own tk.Tk() on their own thread, and that caused
repeated real crashes: Tcl's panic() firing (tcl86t.dll, exception
0x80000003), confirmed via Windows crash dumps on 2026-07-19 (before
error_toast.py even existed -- so pill.py's persistent Tk() thread
coexisting with settings/try-it-now/updater's own short-lived ones was
already fragile) and again on 2026-07-20 after error_toast.py added a
second permanent Tk() thread.

Both overlays now share this ONE Tk() root/thread; each gets its own
tk.Toplevel (a real, independently positioned window) off it instead of
its own interpreter. build(fn) runs fn() once, on this thread, to
construct an overlay's Toplevel/Canvas/`after()` polling loop -- callers
must never touch Tk objects from any other thread.
"""

import queue
import threading

from . import config

_overlay = None
_lock = threading.Lock()


def _effective_theme():
    if config.THEME in ("light", "dark"):
        return config.THEME
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        ) as key:
            light, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
        return "light" if light else "dark"
    except Exception:
        return "light"


def bg_color():
    """Current theme's background color, for a Toplevel's own .configure(bg=)
    -- ttk styling covers its own widgets but not the raw Tk background
    showing through gaps/padding on the window itself."""
    return "#2b2b2b" if _effective_theme() == "dark" else "#f0f0f0"


def _apply_base_theme(root):
    """Modern clam-based styling for the shared root, applied once so any
    window built off it -- even the very first one shown, before Settings
    has ever been opened -- looks like the rest of the app instead of
    Tk's plain default theme (reported as looking "very Windows XP").
    settings_window.py's own _apply_theme() re-applies (and extends, for
    its Notebook/Treeview/Combobox/checkbox-glyph needs) the same colors
    every time Settings opens -- this is just the baseline every other
    first-run window (onboarding, cloud_notice, try_it_now) also gets for
    free by virtue of sharing this one root."""
    try:
        from tkinter import ttk

        style = ttk.Style(root)
        style.theme_use("clam")
        if _effective_theme() == "dark":
            bg, fg, field, raised = "#2b2b2b", "#e6e6e6", "#3c3c3c", "#454545"
            border, hover = "#555555", "#5a5a5a"
        else:
            bg, fg, field, raised = "#f0f0f0", "#1a1a1a", "#ffffff", "#dcdcdc"
            border, hover = "#b0b0b0", "#cccccc"
        accent, accent_fg = "#4682b4", "#ffffff"  # steel blue, matches the tray icon

        root.configure(bg=bg)
        style.configure(".", background=bg, foreground=fg,
                        fieldbackground=field, bordercolor=border,
                        lightcolor=bg, darkcolor=bg, font=("Segoe UI", 9))
        style.configure("TLabelframe", background=bg, bordercolor=border)
        style.configure("TLabelframe.Label", background=bg, foreground=fg,
                        font=("Segoe UI", 9, "bold"))
        style.configure("TButton", background=raised, padding=(10, 5))
        style.map(
            "TButton",
            background=[("disabled", raised), ("active", hover)],
            foreground=[("disabled", border)],
        )
        style.configure("TCheckbutton", background=bg, foreground=fg)
        style.configure("TRadiobutton", background=bg, foreground=fg)
        style.map("TCheckbutton", background=[("active", bg)],
                  foreground=[("disabled", border)])
        style.map("TRadiobutton", background=[("active", bg)],
                  foreground=[("disabled", border)])
        style.configure("TProgressbar", background=accent, troughcolor=field,
                        bordercolor=border, lightcolor=accent, darkcolor=accent)
    except Exception:
        pass


class _OverlayThread:
    def __init__(self):
        self.root = None
        self._ready = threading.Event()
        self._failed = False
        self._build_queue = queue.Queue()
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        try:
            import tkinter as tk

            self.root = tk.Tk()
            self.root.withdraw()  # the shared root itself is never shown
            _apply_base_theme(self.root)
            self._ready.set()
            self.root.after(20, self._poll_builds)
            self.root.mainloop()
        except Exception:
            self._failed = True
            self._ready.set()

    def _poll_builds(self):
        try:
            while True:
                fn = self._build_queue.get_nowait()
                fn()
        except queue.Empty:
            pass
        self.root.after(20, self._poll_builds)

    def build(self, fn):
        """Run fn() on the overlay thread, the next time it polls. Safe
        from any thread. Each overlay calls this once, to construct its
        Toplevel/Canvas/`after()` loop on the correct thread."""
        self._build_queue.put(fn)


def get():
    """The shared overlay thread, starting it on first use. Callers must
    wait on the returned object's `_ready` event before using `.root` or
    calling `.build()`, and check `._failed` before relying on either."""
    global _overlay
    with _lock:
        if _overlay is None:
            _overlay = _OverlayThread()
        return _overlay
