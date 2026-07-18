"""
User settings: JSON overrides for config defaults.

Stored at %LOCALAPPDATA%\\SumitSpeak\\settings.json, outside the EXE, so
behavior can change without a rebuild -- the settings UI writes this file,
and editing it by hand works too. config.py remains the source of defaults;
this module overlays whatever valid keys the file contains at startup.
Missing file, malformed JSON, or unknown keys silently fall back to
defaults: settings must never be able to break dictation.
"""

import json
import os
from pathlib import Path

from pynput import keyboard

from . import config

# json key -> config attribute. Only these keys are honored.
_KEYS = {
    "model_size": "MODEL_SIZE",
    "cleanup_mode": "CLEANUP_MODE",
    "filler_words": "FILLER_WORDS",
    "dictionary": "DICTIONARY",
    "self_correction_triggers": "SELF_CORRECTION_TRIGGERS",
    "enable_self_correction": "ENABLE_SELF_CORRECTION",
    "enable_repeat_collapse": "ENABLE_REPEAT_COLLAPSE",
    "insert_mode": "INSERT_MODE",
    "append_space": "APPEND_SPACE",
    "press_enter_after": "PRESS_ENTER_AFTER",
    "start_with_windows": "START_WITH_WINDOWS",
    "play_sounds": "PLAY_SOUNDS",
    "debug_log": "DEBUG_LOG",
}

# Keys handled outside the type-checked table.
_SPECIAL_KEYS = ("hotkey", "input_device")


def settings_dir():
    return Path(os.environ.get("LOCALAPPDATA", ".")) / "SumitSpeak"


def settings_path():
    return settings_dir() / "settings.json"


def _parse_hotkey(name):
    """A key name like "ctrl_r" or "f9" (pynput Key attribute), or a single
    character. Returns None if unrecognized."""
    if not isinstance(name, str) or not name:
        return None
    key = getattr(keyboard.Key, name, None)
    if key is not None:
        return key
    if len(name) == 1:
        return keyboard.KeyCode.from_char(name)
    return None


def load_into_config(path=None):
    """Overlay the settings file onto config module attributes. Returns the
    raw dict that was applied (empty if none)."""
    path = settings_path() if path is None else Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}

    applied = {}
    for key, attr in _KEYS.items():
        if key not in data:
            continue
        value = data[key]
        default = getattr(config, attr)
        # Type-check against the default so a malformed value can't crash
        # the pipeline later (bool is checked exactly: bool is an int
        # subclass and 1/0 must not silently become flags).
        if isinstance(default, bool) != isinstance(value, bool):
            continue
        if not isinstance(value, type(default)):
            continue
        setattr(config, attr, value)
        applied[key] = value

    hotkey = _parse_hotkey(data.get("hotkey"))
    if hotkey is not None:
        config.HOTKEY = hotkey
        applied["hotkey"] = data["hotkey"]

    # input_device: None (default) or a sounddevice input index / name.
    if "input_device" in data and isinstance(data["input_device"], (type(None), int, str)):
        config.INPUT_DEVICE = data["input_device"]
        applied["input_device"] = data["input_device"]

    return applied


def save(values, path=None):
    """Merge the given known keys into the settings file (creating it if
    needed). Unknown keys are ignored."""
    path = settings_path() if path is None else Path(path)
    try:
        current = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(current, dict):
            current = {}
    except Exception:
        current = {}

    for key, value in values.items():
        if key in _KEYS or key in _SPECIAL_KEYS:
            current[key] = value

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(current, indent=2, ensure_ascii=False), encoding="utf-8")
    return current
