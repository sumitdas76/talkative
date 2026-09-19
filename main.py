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

from talkative.app import TalkativeApp


def main():
    app = TalkativeApp()
    app.run()


if __name__ == "__main__":
    main()
