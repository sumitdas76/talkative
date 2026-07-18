"""
Register or unregister Sumit Speak in the per-user Windows Run key so it
starts at login. Uses HKCU (no admin rights); synced from
config.START_WITH_WINDOWS at every launch so the registry always mirrors
the config.
"""

import sys
import winreg
from pathlib import Path

from . import config

_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_VALUE_NAME = "Sumit Speak"


def _launch_command():
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    script = Path(__file__).resolve().parent.parent / "main.py"
    return f'"{pythonw}" "{script}"'


def sync_autostart(enabled=None):
    enabled = config.START_WITH_WINDOWS if enabled is None else enabled
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE)
    except OSError:
        return
    with key:
        if enabled:
            winreg.SetValueEx(key, _VALUE_NAME, 0, winreg.REG_SZ, _launch_command())
        else:
            try:
                winreg.DeleteValue(key, _VALUE_NAME)
            except FileNotFoundError:
                pass
