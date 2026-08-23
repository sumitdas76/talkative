"""
User settings: JSON overrides for config defaults.

Stored at %LOCALAPPDATA%\\Talkative\\settings.json, outside the EXE, so
behavior can change without a rebuild -- the settings UI writes this file,
and editing it by hand works too. config.py remains the source of defaults;
this module overlays whatever valid keys the file contains at startup.
Missing file, malformed JSON, or unknown keys silently fall back to
defaults: settings must never be able to break dictation.

settings_dir() is the single source of truth for the app's data folder --
model_manager.py and history.py both reuse it rather than recomputing the
path themselves, so a future rename only needs to change it here.
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
    "enable_spoken_symbols": "ENABLE_SPOKEN_SYMBOLS",
    "enable_repeat_collapse": "ENABLE_REPEAT_COLLAPSE",
    "enable_grammar_engine": "ENABLE_GRAMMAR_ENGINE",
    "enable_history": "ENABLE_HISTORY",
    "grammar_model": "GRAMMAR_MODEL_DIR",
    "manifest_url": "MANIFEST_URL",
    "insert_mode": "INSERT_MODE",
    "append_space": "APPEND_SPACE",
    "press_enter_after": "PRESS_ENTER_AFTER",
    "start_with_windows": "START_WITH_WINDOWS",
    "play_sounds": "PLAY_SOUNDS",
    "theme": "THEME",
    "first_run_done": "FIRST_RUN_DONE",
    "debug_log": "DEBUG_LOG",
    "install_id": "INSTALL_ID",
    "feedback_last_check": "FEEDBACK_LAST_CHECK",
    "feedback_last_seen": "FEEDBACK_LAST_SEEN",
    "feedback_last_reply": "FEEDBACK_LAST_REPLY",
}

# Keys handled outside the type-checked table.
_SPECIAL_KEYS = ("hotkey", "input_device")


def settings_dir():
    return Path(os.environ.get("LOCALAPPDATA", ".")) / "Talkative"


def settings_path():
    return settings_dir() / "settings.json"


def migrate_data_folder():
    """One-time move of the pre-rename (2026-08-23) %LOCALAPPDATA%\\
    SumitSpeak folder to the new %LOCALAPPDATA%\\Talkative folder --
    settings, history, debug.log, updater state, and downloaded models all
    live under here, so this must run before anything else touches the
    data folder (first line of app startup, before load_into_config()). A
    plain directory rename, not a copy, so it's fast even with multi-GB
    models inside. No-op (and safe to call every launch) once migrated, or
    if there's nothing to migrate, or if the new folder already has
    something in it -- never overwrites."""
    old = Path(os.environ.get("LOCALAPPDATA", ".")) / "SumitSpeak"
    new = settings_dir()
    try:
        if old.exists() and not new.exists():
            old.rename(new)
    except Exception:
        pass


def _parse_one_key(name):
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


def _parse_hotkey(value):
    """A single key name (old settings.json format, kept for backward
    compatibility) or a list of 1-2 key names (chord). Returns a tuple of
    1-2 pynput Key/KeyCode objects, or None if unrecognized/empty."""
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list) or not (1 <= len(value) <= 2):
        return None
    keys = tuple(_parse_one_key(name) for name in value)
    if any(k is None for k in keys):
        return None
    return keys


def load_into_config(path=None):
    """Overlay the settings file onto config module attributes. Returns the
    raw dict that was applied (empty if none)."""
    path = settings_path() if path is None else Path(path)
    try:
        # utf-8-sig: tolerate a BOM from Notepad or PowerShell hand-edits.
        data = json.loads(path.read_text(encoding="utf-8-sig"))
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

    # output_device: None (default) or a sounddevice output index / name.
    if "output_device" in data and isinstance(data["output_device"], (type(None), int, str)):
        config.OUTPUT_DEVICE = data["output_device"]
        applied["output_device"] = data["output_device"]

    return applied


def save(values, path=None):
    """Merge the given known keys into the settings file (creating it if
    needed). Unknown keys are ignored."""
    path = settings_path() if path is None else Path(path)
    try:
        current = json.loads(path.read_text(encoding="utf-8-sig"))
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
