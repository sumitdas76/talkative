"""Write errors to %LOCALAPPDATA%\\Talkative\\errors.log.

The windowed EXE has no console (main.py points stderr at devnull), so
until this existed an exception in any background thread -- pystray's
tray loop, the hotkey listener, a worker -- vanished without a trace;
a user's tray icon disappeared twice with nothing to diagnose it from.
Only warnings and tracebacks are written, never dictated text. The file
is capped: once it passes _MAX_BYTES it is started over.
"""
import logging
import sys
import threading

from . import settings

_MAX_BYTES = 512 * 1024


def install():
    try:
        folder = settings.settings_dir()
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / "errors.log"
        if path.exists() and path.stat().st_size > _MAX_BYTES:
            path.unlink()
        handler = logging.FileHandler(path, encoding="utf-8", delay=True)
    except Exception:
        return
    handler.setLevel(logging.WARNING)
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s [%(threadName)s]: %(message)s"))
    root = logging.getLogger()
    root.addHandler(handler)
    if root.level > logging.WARNING or root.level == logging.NOTSET:
        root.setLevel(logging.WARNING)

    log = logging.getLogger("talkative")

    def thread_hook(args):
        if args.exc_type is SystemExit:
            return
        log.error("uncaught exception in thread %s",
                  args.thread.name if args.thread else "?",
                  exc_info=(args.exc_type, args.exc_value, args.exc_traceback))

    def main_hook(exc_type, exc_value, tb):
        log.error("uncaught exception", exc_info=(exc_type, exc_value, tb))

    threading.excepthook = thread_hook
    sys.excepthook = main_hook
