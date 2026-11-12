"""
Start Talkative when the user signs in to Windows, mirroring
config.START_WITH_WINDOWS. Synced at every launch and whenever the setting
changes.

Two ways, depending on how this copy was installed (packaging.py):
- GitHub installer / from source: the per-user Run key (HKCU, no admin).
- Microsoft Store (MSIX): the "TalkativeStartup" StartupTask declared in
  store/AppxManifest.xml. Inside a package a Run-key write is virtualised
  and Windows never sees it. The user can also turn the task off in
  Settings > Apps > Startup or Task Manager; after that the app is not
  allowed to turn it back on itself (DisabledByUser), so the caller tells
  the user where to do it.
"""

import asyncio
import logging
import sys
import threading
import winreg
from pathlib import Path

from . import config, packaging

log = logging.getLogger(__name__)

_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_VALUE_NAME = "Talkative"
# Pre-rename (2026-08-23) value name -- cleaned up on the next sync so a
# stale "Sumit Speak" entry doesn't linger pointing at a path that no
# longer exists once the exe/install folder are renamed.
_OLD_VALUE_NAME = "Sumit Speak"

STARTUP_TASK_ID = "TalkativeStartup"   # must match store/AppxManifest.xml

# What sync_autostart reports.
ON, OFF = "on", "off"
BLOCKED_BY_USER = "blocked_by_user"       # turned off in Windows' Startup apps
BLOCKED_BY_POLICY = "blocked_by_policy"   # an administrator's policy
FAILED = "failed"

BLOCKED_MESSAGE = ("Windows has Talkative's start-up turned off. To turn it on, open "
                   "Windows Settings > Apps > Startup and switch Talkative on.")


def _launch_command():
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    script = Path(__file__).resolve().parent.parent / "main.py"
    return f'"{pythonw}" "{script}"'


def _sync_run_key(enabled):
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE)
    except OSError:
        return FAILED
    with key:
        try:
            winreg.DeleteValue(key, _OLD_VALUE_NAME)
        except FileNotFoundError:
            pass
        if enabled:
            winreg.SetValueEx(key, _VALUE_NAME, 0, winreg.REG_SZ, _launch_command())
            return ON
        try:
            winreg.DeleteValue(key, _VALUE_NAME)
        except FileNotFoundError:
            pass
        return OFF


def _state_result(state, names):
    """Map a StartupTaskState to ON/OFF/BLOCKED_*. `names` is the enum
    (passed in so tests can use a stand-in)."""
    if state in (names.ENABLED, names.ENABLED_BY_POLICY):
        return ON
    if state == names.DISABLED_BY_USER:
        return BLOCKED_BY_USER
    if state == names.DISABLED_BY_POLICY:
        return BLOCKED_BY_POLICY
    return OFF


async def _sync_task_async(enabled, task_api, names):
    task = await task_api.get_async(STARTUP_TASK_ID)
    if enabled and task.state == names.DISABLED:
        await task.request_enable_async()   # silent for a desktop app's own task
    elif not enabled and task.state == names.ENABLED:
        task.disable()
    return _state_result(task.state, names)


def _sync_startup_task(enabled, task_api=None, names=None):
    if task_api is None:
        from winrt.windows.applicationmodel import StartupTask, StartupTaskState
        task_api, names = StartupTask, StartupTaskState
    result = [FAILED]

    def run():
        # Own thread: WinRT's async calls need an event loop and a COM
        # apartment, and the callers (tray menu thread, the app's main
        # thread) must not get either set up as a side effect.
        try:
            result[0] = asyncio.run(_sync_task_async(enabled, task_api, names))
        except Exception:
            log.warning("start with Windows (StartupTask) failed", exc_info=True)

    worker = threading.Thread(target=run, name="startup-task", daemon=True)
    worker.start()
    worker.join(10)
    return result[0]


def sync_autostart(enabled=None):
    """Make Windows match the setting. Returns ON, OFF, BLOCKED_BY_USER,
    BLOCKED_BY_POLICY or FAILED. Never raises."""
    enabled = config.START_WITH_WINDOWS if enabled is None else enabled
    try:
        if packaging.is_store_build():
            return _sync_startup_task(enabled)
        return _sync_run_key(enabled)
    except Exception:
        log.warning("start with Windows sync failed", exc_info=True)
        return FAILED
