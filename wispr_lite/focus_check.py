"""
Detect whether the currently focused UI control can accept typed text.

Uses Windows UI Automation, which works across classic Win32 edit controls
(Notepad, WordPad), browser address bars and web form fields (Chrome/Edge),
and most Electron/UWP apps. Some apps (e.g. WhatsApp for Windows, built with
React Native for Windows, and other custom-rendered controls) don't expose
the standard accessibility patterns at all even though they happily accept
pasted/typed text.

To support dictating "wherever you can type," this only refuses when it can
positively confirm you *can't* type there: nothing is focused, the control
is disabled, or it's explicitly marked read-only. Anything else (including
controls that expose no recognizable pattern) is assumed to be editable and
the paste is attempted anyway.
"""

import pythoncom
import uiautomation as auto

_READONLY_STATE_FLAG = 0x40  # STATE_SYSTEM_READONLY


def _ensure_com_initialized():
    try:
        pythoncom.CoInitialize()
    except Exception:
        pass


def is_focus_editable():
    _ensure_com_initialized()

    try:
        control = auto.GetFocusedControl()
    except Exception:
        # Can't inspect focus at all -- don't block on an inconclusive check.
        return True

    if control is None or not control.Exists(0, 0):
        return False

    try:
        if not control.IsEnabled:
            return False
    except Exception:
        pass

    # Explicit read-only signal via ValuePattern.
    try:
        value_pattern = control.GetValuePattern()
        if value_pattern is not None:
            return not value_pattern.IsReadOnly
    except Exception:
        pass

    # Explicit read-only signal via legacy accessibility state.
    try:
        legacy = control.GetLegacyIAccessiblePattern()
        if legacy is not None:
            state = legacy.State or 0
            if state & _READONLY_STATE_FLAG:
                return False
    except Exception:
        pass

    # No pattern told us anything definitive either way -- assume editable
    # rather than blocking, so custom-rendered controls (WhatsApp, some
    # Electron/React Native apps) still get dictated text.
    return True
