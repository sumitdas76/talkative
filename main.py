import os
import sys

# PyInstaller's --windowed build has no console attached, so sys.stdout/
# stderr are None rather than a real stream. Anything that tries to write
# to them (e.g. huggingface_hub's tqdm-based download progress bars,
# hit live 2026-09-19 via grammar_engine.download() -- "'NoneType' object
# has no attribute 'write'") crashes immediately. Only from-source runs
# have a real console, which is why this went unnoticed until the frozen
# EXE actually exercised that code path.
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")

# From source, Windows groups the app's windows under python(w).exe and
# shows Python's icon in the taskbar (user report 2026-10-23: "the icon of
# Talkative in my taskbar has changed"). An app ID of its own makes the
# taskbar use the window icon (app_icon.set_window_icon) instead. The
# frozen EXE has its own icon resource and doesn't need this.
if not getattr(sys, "frozen", False):
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("SumitDas.Talkative")
    except Exception:
        pass

from talkative import error_log
from talkative.app import TalkativeApp


def main():
    error_log.install()
    app = TalkativeApp()
    app.run()
    # Tray -> Quit returns here, but normal interpreter shutdown can hang
    # forever: garbage-collecting a Tk PhotoImage (Settings' checkbox
    # glyphs) calls into the Tk interpreter owned by overlay_thread's
    # daemon thread, which is already frozen -- both EXE processes stayed
    # in Task Manager after Quit (py-spy, 2026-09-26: stuck in
    # ImageTk.PhotoImage.__del__). Everything worth keeping (settings,
    # debug.log) is written as it happens, so skip finalization, as the
    # updater's exit already does.
    os._exit(0)


if __name__ == "__main__":
    main()
