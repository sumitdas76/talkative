# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Wispr Lite: a Windows tray app for hold-to-talk local dictation. Hold **Right
Ctrl**, speak, release — audio is transcribed offline via faster-whisper and
pasted (clipboard + simulated Ctrl+V) into whatever control currently has
focus. No network calls except the one-time model download from Hugging
Face on first run.

## Commands

```powershell
# Setup (first time, or after the venv is deleted)
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt

# Run from source
.\.venv\Scripts\python main.py
# or, to avoid a console window (matches how the built EXE behaves):
.\.venv\Scripts\pythonw.exe main.py

# Rebuild the standalone EXE after any source change
.\.venv\Scripts\pyinstaller --noconfirm --onefile --windowed --name WisprLite --collect-all ctranslate2 --collect-all faster_whisper --collect-all av --collect-all tokenizers --collect-all uiautomation --hidden-import win32timezone main.py
```

There is no test suite, linter, or CI in this project — verification is
manual (run it, dictate something, watch the tray icon / target app).

### IMPORTANT: two EXE copies, and the file-lock gotcha

The user keeps a working copy of `WisprLite.exe` at the **project root**
(not just `dist\`) and launches it from there directly — always copy a
fresh build to **both** locations:

```powershell
cp dist/WisprLite.exe WisprLite.exe
```

PyInstaller fails with `PermissionError: Access is denied` if either copy is
currently running (it can't overwrite a locked EXE). Before rebuilding,
check for and stop running instances:

```powershell
Get-Process WisprLite -ErrorAction SilentlyContinue | Select-Object Id,StartTime,Path
Stop-Process -Name WisprLite -Force -ErrorAction SilentlyContinue
```

The user frequently has an instance running to test something live — ask
before killing it rather than assuming it's safe to stop.

After PyInstaller finishes, do a launch smoke test (start it, confirm the
`WisprLite` process stays alive for a few seconds without exiting, then stop
it) — this has caught real packaging issues before (missing DLLs, bad hidden
imports).

## Architecture

Everything lives in `wispr_lite/`, wired together by `WisprLiteApp` in
`app.py`, which owns the hotkey listener, the recorder, the transcriber, and
the tray icon, and drives one linear pipeline per dictation:

```
hotkey press  → focus_check.is_focus_editable()   (gate: is anything typable focused?)
              → audio_recorder.AudioRecorder.start()
hotkey release→ audio_recorder.AudioRecorder.stop() → raw audio buffer (numpy)
              → transcriber.Transcriber.transcribe() → raw text (faster-whisper, verbatim)
              → self_correction.apply_self_corrections()  (drop retracted speech)
              → focus_check.is_focus_editable()   (re-checked: focus may have changed)
              → text_inserter.insert_text()        (clipboard + simulated Ctrl+V + restore)
```

Each stage is a separate module with no cross-dependencies beyond `config.py`
— when changing behavior, the fix almost always belongs in exactly one file:

- **`config.py`** — every tunable lives here (hotkey, model size/device,
  min recording length, self-correction trigger phrases and on/off switch).
  Prefer adding a new config constant over hardcoding a value in a module.
- **`focus_check.py`** — Windows UI Automation check, deliberately a
  **block-list, not an allow-list**: it only refuses dictation when it can
  positively confirm the focused control is non-editable (nothing focused,
  disabled, or explicitly read-only). This was a deliberate design change
  (see git history / conversation context) away from an earlier allow-list
  that only permitted known-good UIA patterns (Edit/Document/ComboBox) —
  that version silently failed in apps like WhatsApp for Windows (React
  Native for Windows) that don't expose standard accessibility patterns at
  all. Don't reintroduce an allow-list here without a strong reason.
- **`self_correction.py`** — pure, local, rule-based text post-processing
  (no LLM, no network — keep it that way). Detects spoken retraction
  phrases ("scratch that", "no wait", etc., configured in
  `config.SELF_CORRECTION_TRIGGERS`) and discards text back to the last
  sentence boundary before the trigger. Known, accepted limitation: it only
  looks back to the most recent `.`/`!`/`?`, so a correction after a full
  stop won't retract the previous sentence — this is an inherent trade-off
  of a non-semantic heuristic, not a bug to silently "fix" by adding an LLM
  call.
- **`transcriber.py`** — thin `faster_whisper.WhisperModel` wrapper, one-shot
  (not streaming) transcription of a single in-memory buffer.
- **`text_inserter.py`** — clipboard-based insertion is intentional: it's
  the most broadly compatible way to get text into arbitrary native/browser/
  Electron controls, more so than simulating individual keystrokes. Restores
  the user's previous clipboard contents after `config.CLIPBOARD_RESTORE_DELAY`.
- **`tray.py`** — icons are drawn in code with PIL (colored circles: grey
  loading / blue idle / red recording), not loaded from image assets — keep
  it that way so PyInstaller packaging doesn't need extra `--add-data` for
  icon files.

## Packaging notes

`WisprLite.spec` is checked in and reproducible — prefer re-running the
`pyinstaller` command above (which regenerates it) over hand-editing the
spec file. The `--collect-all` flags are load-bearing, not decorative:
`ctranslate2`/`faster-whisper` ship binary DLLs, and `uiautomation` ships a
DLL under its package's `bin/` subfolder that PyInstaller's default scan
doesn't discover — dropping any of these flags will silently produce a
broken EXE (imports fine in source but crashes or misbehaves when frozen).

The speech model is *not* bundled into the EXE — it downloads to
`%USERPROFILE%\.cache\huggingface\hub\models--Systran--faster-whisper-<MODEL_SIZE>`
on first run of a given `MODEL_SIZE`, same whether running from source or
from the built EXE. Changing `config.MODEL_SIZE` means a fresh download on
next launch, not an instant switch.
