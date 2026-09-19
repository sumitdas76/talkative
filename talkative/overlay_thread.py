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

_overlay = None
_lock = threading.Lock()


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
