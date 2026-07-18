# Wispr Lite

Hold **Right Ctrl** anywhere on Windows, speak, release — your speech is
transcribed locally (offline, via faster-whisper) and pasted into whatever
text field currently has focus. If nothing focused can accept text, you get
an error popup instead.

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
.\.venv\Scripts\python main.py
```

The first run downloads the speech model (~150MB for the default `base.en`)
from Hugging Face and caches it under `%USERPROFILE%\.cache\huggingface`.
Subsequent runs start instantly from cache.

A tray icon appears (grey while the model loads, blue once ready, red while
recording). Right-click it to Quit.

## Usage

1. Click into a text box, document, or address bar.
2. Hold **Right Ctrl** and speak.
3. Release — the transcribed text is pasted in.

If no editable field is focused when you press the hotkey (or by the time
transcription finishes), a Windows error dialog pops up telling you to click
into a text field first.

## Tuning (`wispr_lite/config.py`)

- `HOTKEY` — change the hold-to-talk key (any `pynput.keyboard.Key`).
- `MODEL_SIZE` — `tiny.en` (fastest, least accurate) through `medium.en` /
  `large-v3` (slower, more accurate). Drop the `.en` suffix for multilingual
  models.
- `DEVICE` / `COMPUTE_TYPE` — set `DEVICE = "cuda"` if you have an NVIDIA GPU
  for much faster transcription.
- `ENABLE_SELF_CORRECTION` / `SELF_CORRECTION_TRIGGERS` — see below.

## Spoken self-correction

If you misspeak and correct yourself out loud — "Send it tomorrow, no wait,
send it on Friday." — the app detects the correction phrase and drops
everything since the last sentence boundary up to that phrase, keeping only
"Send it on Friday." This is a local, rule-based text cleanup (no LLM, no
network) in `wispr_lite/self_correction.py`, driven by the trigger phrase
list in `config.py`. Turn it off with `ENABLE_SELF_CORRECTION = False`, or
edit `SELF_CORRECTION_TRIGGERS` to add/remove phrases.

Known limitations: it only discards back to the most recent `.`/`!`/`?`, so
a correction after a full stop (rather than a comma/pause) won't retract the
previous sentence. Literal speech that happens to contain a trigger phrase
(e.g. "...scratch that itch") will also get mangled. These are inherent to a
rule-based approach with no real language understanding.

## How text insertion works

Transcribed text is placed on the clipboard and pasted via a simulated
Ctrl+V, then your previous clipboard contents are restored a moment later.
This is the most broadly compatible way to insert text across native apps,
browsers, and Electron apps.

## How the "can I type here?" check works

It uses Windows UI Automation to inspect the currently focused control, but
errs toward permissive: it only blocks dictation when it can positively
confirm you *can't* type there (nothing focused, the control is disabled,
or it's explicitly marked read-only via `ValuePattern`/legacy accessibility
state). Any other case — including controls that expose no recognizable
accessibility pattern at all, such as WhatsApp for Windows (React Native for
Windows) and some other custom-rendered UIs — is treated as editable and the
paste is attempted anyway. This trades a small chance of pasting into the
wrong place for working in far more apps.

## Known limitations

- Windows only.
- Mic input uses your system default recording device.
- Very short presses (<0.3s, see `MIN_RECORDING_SECONDS`) are ignored, to
  filter out accidental taps.

## Building a standalone EXE

```powershell
.\.venv\Scripts\pyinstaller WisprLite.spec
```

Produces `dist\WisprLite.exe` — a single portable, windowless file with all
Python dependencies bundled in. It still downloads the speech model to the
Hugging Face cache on first run, same as running from source. Copy the EXE
anywhere and double-click it to launch; no install step required.

`WisprLite.spec` was generated once with:

```powershell
.\.venv\Scripts\pyinstaller --onefile --windowed --name WisprLite --collect-all ctranslate2 --collect-all faster_whisper --collect-all av --collect-all tokenizers --collect-all uiautomation --hidden-import win32timezone main.py
```

(the `--collect-all` flags are needed because `ctranslate2`/`faster-whisper`
ship binary DLLs and `uiautomation` ships a DLL under its package's `bin/`
folder that PyInstaller doesn't discover automatically). Re-run the first
command whenever you change the source; only re-run the second if you add a
new dependency that needs its own bundling flags.
