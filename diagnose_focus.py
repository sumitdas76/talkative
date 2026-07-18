"""
Run this, then within 4 seconds click into the WhatsApp message box
(or whichever text field is failing to receive dictated text).

Prints what Windows UI Automation sees about the focused control, so we
can tell exactly why Sumit Speak thinks it isn't editable.
"""

import time

import pythoncom
import uiautomation as auto

print("Click into the target text field now... checking in 4 seconds.")
time.sleep(4)

pythoncom.CoInitialize()

control = auto.GetFocusedControl()

if control is None:
    print("RESULT: No control detected as focused at all.")
    raise SystemExit

print(f"ControlTypeName : {control.ControlTypeName}")
print(f"ClassName       : {control.ClassName}")
print(f"Name            : {control.Name!r}")
print(f"Exists(0,0)     : {control.Exists(0, 0)}")

try:
    print(f"IsEnabled       : {control.IsEnabled}")
except Exception as exc:
    print(f"IsEnabled       : ERROR {exc}")

try:
    vp = control.GetValuePattern()
    print(f"ValuePattern    : {vp}  IsReadOnly={vp.IsReadOnly if vp else None}")
except Exception as exc:
    print(f"ValuePattern    : ERROR {exc}")

try:
    tp = control.GetTextPattern()
    print(f"TextPattern     : {tp}")
except Exception as exc:
    print(f"TextPattern     : ERROR {exc}")

try:
    legacy = control.GetLegacyIAccessiblePattern()
    state = legacy.State if legacy else None
    print(f"LegacyPattern   : {legacy}  State={state}")
except Exception as exc:
    print(f"LegacyPattern   : ERROR {exc}")

print()
print("Sumit Speak treats a control as editable only if:")
print("  - ValuePattern exists and IsReadOnly is False, OR")
print("  - TextPattern exists AND ControlTypeName is Edit/Document/ComboBox, OR")
print("  - LegacyIAccessiblePattern exists AND ControlTypeName is Edit/Document/ComboBox")
print("    and its State does not include the read-only flag (0x40).")
