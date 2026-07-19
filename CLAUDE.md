# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Sumit Speak (formerly Wispr Lite): a Windows tray app for hold-to-talk local
dictation. Hold **Right Ctrl**, speak, release — audio is transcribed offline
via faster-whisper, cleaned up (fillers, spoken corrections, near-repeats,
personal dictionary), and pasted (clipboard + simulated Ctrl+V) into whatever
control currently has focus. No network calls except the one-time model
download from Hugging Face on first run.

The full product direction (settings UI, model manager, update system,
grammar engine) is specced in the "Sumit Speak — Product Specification"
artifact from the July 2026 consulting sessions; Phase 1 (engine features,
no UI) is implemented.

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
.\.venv\Scripts\python -m PyInstaller --noconfirm --onefile --windowed --name SumitSpeak --collect-all ctranslate2 --collect-all faster_whisper --collect-all av --collect-all tokenizers --collect-all uiautomation --hidden-import win32timezone main.py
```

Use `python -m PyInstaller`, NOT the `.\.venv\Scripts\pyinstaller` exe shim:
the shim is broken in this venv — it exits 1 instantly with **no output at
all**, which looks like a successful quiet run if the exit code is masked
(e.g. by piping to `tail`). This once led to deploying a stale day-old EXE.
After every build, verify `dist\SumitSpeak.exe` has a fresh LastWriteTime
before copying it anywhere.

There is no linter or CI. A sanity-test script for the pure text-pipeline
functions (cleanup, dictionary, self-correction) lives in the session
scratchpad pattern — exercise those functions with real sentences after
changing them. App-level verification is manual (run it, dictate something,
watch the tray icon / target app).

### IMPORTANT: two EXE copies, and the file-lock gotcha

The user keeps a working copy of the EXE at the **project root** (not just
`dist\`) and launches it from there directly — always copy a fresh build to
**both** locations:

```powershell
cp dist/SumitSpeak.exe SumitSpeak.exe
```

(Stale `WisprLite.exe` copies from before the rename may still exist; they
are the old build.)

PyInstaller fails with `PermissionError: Access is denied` if either copy is
currently running (it can't overwrite a locked EXE). Before rebuilding,
check for and stop running instances:

```powershell
Get-Process SumitSpeak, WisprLite -ErrorAction SilentlyContinue | Select-Object Id,StartTime,Path
```

The user frequently has an instance running to test something live — ask
before killing it rather than assuming it's safe to stop.

After PyInstaller finishes, do a launch smoke test (start it, confirm the
process stays alive for a few seconds without exiting, then stop it) — this
has caught real packaging issues before (missing DLLs, bad hidden imports).

## Architecture

Everything lives in `sumit_speak/`, wired together by `SumitSpeakApp` in
`app.py`, which owns the hotkey listener, the recorder, the transcriber, and
the tray icon, and drives one linear pipeline per dictation:

```
hotkey press  → focus_check.is_focus_editable()   (gate: is anything typable focused?)
              → audio_recorder.AudioRecorder.start()
hotkey release→ audio_recorder.AudioRecorder.stop() → raw audio buffer (numpy)
              → transcriber.Transcriber.transcribe()  (faster-whisper; dictionary
                vocabulary fed as initial_prompt to bias recognition)
              → cleanup.remove_fillers()             (cleaned_up mode only)
              → self_correction.apply_self_corrections()  (cleaned_up mode only)
              → cleanup.collapse_repeats()           (cleaned_up mode only)
              → dictionary.apply_dictionary()        (always)
              → focus_check.is_focus_editable()   (re-checked: focus may have changed)
              → text_inserter.insert_text()        (clipboard + simulated Ctrl+V + restore)
```

Fillers are removed *before* correction triggers run so "sorry, um, I mean"
still matches the "sorry I mean" trigger.

Each stage is a separate module with no cross-dependencies beyond `config.py`
— when changing behavior, the fix almost always belongs in exactly one file:

- **`config.py`** — every tunable lives here (hotkey, model size/device,
  cleanup mode, filler list, dictionary, output options, autostart flag).
  Prefer adding a new config constant over hardcoding a value in a module.
  Phase 2 (settings UI) will move user-editable values to a settings file;
  until then constants are the config store.
- **`focus_check.py`** — Windows UI Automation check, deliberately a
  **block-list, not an allow-list**: it only refuses dictation when it can
  positively confirm the focused control is non-editable. This was a
  deliberate design change away from an allow-list that silently failed in
  apps like WhatsApp for Windows (React Native) that don't expose standard
  accessibility patterns. Don't reintroduce an allow-list without a strong
  reason.
- **`self_correction.py`** — pure, local, rule-based (no LLM, no network —
  keep it that way). Detects spoken retraction phrases (compound only —
  bare "sorry" is deliberately not a trigger because it appears in real
  dictated content). Comma-separated trigger words ("No, sorry") are only
  trusted at the start of a sentence -- Whisper punctuates real retractions
  that way, but mid-sentence "I said no, sorry, I was busy" is literal
  content and no rule can tell the difference (grammar engine's job later).
  Periods never join trigger words. The retraction span starts at the last
  sentence boundary (or one sentence further back when the trigger itself
  starts a sentence -- Whisper often puts a period right before a
  retraction). Within that span, if a comma is present, retract the part
  that resembles the correction (a retraction is a restatement): the whole
  span or only its last comma clause; ties delete the smaller. This exists
  because Whisper glues separate spoken sentences with commas. Retraction
  never reaches more than one sentence back. Debug per-stage output via
  config.DEBUG_LOG -> %LOCALAPPDATA%\SumitSpeak\debug.log.
- **`cleanup.py`** — rule-based filler removal and conservative near-repeat
  sentence collapsing (word-level similarity + shared opening word; keep the
  last version). Governing principle: wrongly deleting intended words is the
  worst failure a dictation tool can have — anything ambiguous is left
  alone. Loose rephrasings are out of scope for rules (future grammar
  engine's job).
- **`dictionary.py`** — personal spoken→typed replacements, whole-word,
  case-preserving at sentence start. Typed forms are matched-to-themselves
  so already-expanded phrases don't double-expand. Also builds the
  vocabulary bias prompt for the transcriber.
- **`transcriber.py`** — thin `faster_whisper.WhisperModel` wrapper, one-shot
  (not streaming) transcription; accepts `initial_prompt` for vocabulary
  biasing.
- **`text_inserter.py`** — clipboard-based insertion is intentional: most
  broadly compatible way into arbitrary native/browser/Electron controls.
  Honors INSERT_MODE (paste vs clipboard-only), APPEND_SPACE, and
  PRESS_ENTER_AFTER. Restores the previous clipboard after
  `config.CLIPBOARD_RESTORE_DELAY` (paste mode only).
- **`autostart.py`** — syncs `config.START_WITH_WINDOWS` to the HKCU Run key
  at every launch; handles frozen-EXE vs from-source launch commands.
- **`tray.py`** — icons are drawn in code with PIL (colored circles: grey
  loading / blue idle / red recording), not loaded from image assets — keep
  it that way so PyInstaller packaging doesn't need extra `--add-data`.

## Current status / resume point (saved July 19, 2026, Phase 3 session)

Phases 1–3 (engine, settings window, model manager) are implemented, built,
and deployed to both EXE copies. Phase 3 wiring done this session:

- `app.py` runs `migrate_from_hf_cache()` at load, points the Transcriber
  at the app-owned model folder, and gained `reload_model(size, on_done)`
  (background swap, revert on failure, persists model_size on success) and
  `unload_model()`; a SimpleNamespace controller (reload/unload/has_model)
  is passed into `open_settings`.
- `settings_window.py` Models tab: two tiles with states
  none/download/load/delete/in_use/not_in_use, ~300ms poll loop (workers
  write `_model_ops`/`_model_errors`; only the Tk thread touches widgets),
  indeterminate progressbar during download (no cancel in v1), the three
  delete confirmation flows, storage-used line.
- Verified: migration copied small.en into
  `%LOCALAPPDATA%\SumitSpeak\models` (464 MB — HF layout duplicates blobs
  into snapshots on Windows, so ~2× model size on disk), model loads from
  the app folder, window builds/polls cleanly, EXE launch smoke test OK.

Later that session: soft volume-controlled tones (config.SOUND_VOLUME),
punctuation initial_prompt + cleanup.finish_sentence, latency notes on the
model tiles, and the **grammar engine** (spec Phase 3 step 2):

- `grammar_engine.py` — CTranslate2 Generator + tokenizers (no new deps),
  few-shot leash prompt, deterministic guards (digit runs verbatim, ≥70%
  word retention, length bounds) that fall back to rules-only on any
  violation. Invisible in UI. Loads in background at startup.
- **A/B decided (live test, July 19): Qwen2.5-1.5B int8 won** and lives
  in `<models>/grammar` (~1.5 GB; ~2s grammar pass on short dictations,
  ~8s on long ones). Qwen2.5-0.5B was removed after it silently deleted
  an opening sentence in live use (that failure also motivated the
  per-sentence retention guard); Qwen3-0.6B was disqualified earlier for
  mangling numbers. debug.log logs per-dictation transcribe/grammar
  seconds.
- Conversion recipe (dev-only): scratchpad venv with torch-cpu +
  transformers + ctranslate2, `ct2-transformers-converter --model
  Qwen/... --quantization int8 --copy_files tokenizer.json
  tokenizer_config.json`.
- settings.json is read utf-8-sig (a BOM once silently reset all
  settings).

**Updater (spec §7) implemented and integration-tested** (July 19):
`updater.py` — daily manifest check (MANIFEST_URL in config, default ""
= disabled; `manifest_url` settings key overrides, file:// URLs work for
testing), component-blind dialog, background download to
<models>/staging, verify-then-swap with idle-wait and automatic revert,
1000-word grace file, Undo button on the Models tab, permanent
suppression of undone versions. State: %LOCALAPPDATA%\SumitSpeak\
updater.json. Publisher format: docs/manifest-sample.json. The full
download-swap-undo cycle passed an isolated integration test against a
temp models root. **Not yet done: the actual public GitHub repo hosting
manifest.json (needs user's account; MANIFEST_URL stays "" until then),
and publishing the grammar ct2 conversion to HF so its entry becomes
updatable.**

**Installer (spec §8) built and test-installed** (July 19):
`installer\SumitSpeak.iss`; compile from the project root with
`& "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe" installer\SumitSpeak.iss`
(per-user winget install — NOT under Program Files) after a fresh
PyInstaller build. Output:
installer\Output\SumitSpeakSetup.exe (~1.6 GB — bundles the grammar
engine from this machine's %LOCALAPPDATA%\SumitSpeak\models\grammar,
plus vc_redist downloaded to installer\redist\, both gitignored).
Per-user, no UAC; uninstall's remove-data prompt defaults to KEEP under
/SUPPRESSMSGBOXES. DEBUG_LOG now defaults off; this dev machine keeps it
on via the debug_log settings key.

**Update manifest is LIVE** (July 19): public repo
https://github.com/sumitdas76/sumit-speak-updates holds manifest.json
(all models at baseline "1"); MANIFEST_URL in config points at its raw
URL and the live fetch was verified (no update offered at baseline).
gh CLI installed and authed as sumitdas76. Publishing an update = edit
manifest.json in the browser, bump a version string, commit.

Remaining: GitHub Releases upload of the installer + download page →
first-run flow. Then Phase 4 polish (listening pill, failure toasts,
try-it-now). The source repo itself has no remote — pushing it public
is the user's call, not required by the update system.
Note: user changed the hotkey to Left Ctrl (ctrl_l) via the settings UI.

The July 19 session had blanket user approval for kill-rebuild-relaunch
cycles; re-confirm in a new session before stopping a running instance.

## Deferred / known issues

- **Retraction span ambiguity (parked July 2026, revisit in Phase 3):** the
  clause-aware similarity heuristic in `self_correction.py` handles the
  observed live cases, but Whisper's inconsistent punctuation means some
  retractions are still missed (all-comma loose triggers) or mis-scoped.
  The user has decided not to iterate further with rules -- the grammar
  engine (spec Phase 3) is the real fix. The debug.log corpus of real
  transcripts is the audition data for it.
- **DEBUG_LOG privacy:** `%LOCALAPPDATA%\SumitSpeak\debug.log` stores
  transcript text on disk, which contradicts the spec's "nothing is saved"
  privacy statement. Fine during development; must default off (or be
  disclosed) before any distribution.

## Packaging notes

`--collect-all` flags in the pyinstaller command are load-bearing:
`ctranslate2`/`faster-whisper` ship binary DLLs, and `uiautomation` ships a
DLL under its package's `bin/` subfolder that PyInstaller's default scan
doesn't discover — dropping any of these flags silently produces a broken
EXE (imports fine in source but crashes when frozen).

The speech model is *not* bundled into the EXE — it downloads to
`%USERPROFILE%\.cache\huggingface\hub\models--Systran--faster-whisper-<MODEL_SIZE>`
on first run of a given `MODEL_SIZE`. Changing `config.MODEL_SIZE` means a
fresh download on next launch, not an instant switch. (The spec's Phase 3
moves models to an app-owned folder.)
