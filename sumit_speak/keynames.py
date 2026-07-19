"""
Friendly display names for pynput keys.

UI text only -- config and settings.json keep storing the pynput name
(e.g. "ctrl_l"); this is how that name is shown to the user ("Left Ctrl").
"""

_KEY_NAMES = {
    "ctrl_l": "Left Ctrl", "ctrl_r": "Right Ctrl", "ctrl": "Ctrl",
    "alt_l": "Left Alt", "alt_r": "Right Alt", "alt_gr": "Right Alt (AltGr)",
    "alt": "Alt",
    "shift_l": "Left Shift", "shift_r": "Right Shift", "shift": "Shift",
    "cmd": "Windows key", "cmd_l": "Left Windows key",
    "cmd_r": "Right Windows key",
    "caps_lock": "Caps Lock", "space": "Space", "tab": "Tab", "esc": "Esc",
    "enter": "Enter", "backspace": "Backspace", "delete": "Delete",
    "insert": "Insert", "home": "Home", "end": "End",
    "page_up": "Page Up", "page_down": "Page Down",
    "up": "Up Arrow", "down": "Down Arrow",
    "left": "Left Arrow", "right": "Right Arrow",
    "num_lock": "Num Lock", "scroll_lock": "Scroll Lock",
    "print_screen": "Print Screen", "pause": "Pause", "menu": "Menu",
}


def friendly(key_or_name):
    """Display name for a pynput Key/KeyCode or a raw key-name string."""
    if isinstance(key_or_name, str):
        name = key_or_name
    else:
        name = (getattr(key_or_name, "name", None)
                or getattr(key_or_name, "char", None))
    if not name:
        return "?"
    if name in _KEY_NAMES:
        return _KEY_NAMES[name]
    if len(name) == 1:
        return name.upper()
    if name[0] == "f" and name[1:].isdigit():
        return name.upper()
    return name.replace("_", " ").title()
