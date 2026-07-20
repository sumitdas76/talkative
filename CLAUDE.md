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
.\.venv\Scripts\python -m PyInstaller --noconfirm --onefile --windowed --name SumitSpeak --icon assets\icon.ico --collect-all ctranslate2 --collect-all faster_whisper --collect-all av --collect-all tokenizers --collect-all uiautomation --hidden-import win32timezone main.py
```

`--icon assets\icon.ico` sets the EXE's own icon resource (Explorer, taskbar
pin, Alt-Tab when no window is open). It does NOT change the icon Tk windows
show while open -- Tk defaults to its own "feather" icon regardless of the
EXE resource. That's handled separately in code via
`sumit_speak/app_icon.py`'s `set_window_icon()`, called by each window that
creates its own `tk.Tk()` root (settings, try-it-now, the updater dialog).
Regenerate both `assets/icon.ico` and `sumit_speak/app_icon.py` together by
re-running `assets/generate_icon.py` -- never hand-edit either output.

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

**v1.0.1 released** (July 19): public product page
https://github.com/sumitdas76/sumit-speak (README only — the source
repo still has no remote; publishing code is the user's call) with
SumitSpeakSetup.exe (1.57 GB) on the v1.0.1 release. Includes Phase 4's
listening pill (pill.py — no-activate floating level indicator) and
first-run try-it-now box (try_it_now.py, first_run_done settings key).

**Change-request queue items 1-8 implemented July 20, 2026** (source-level;
NOT yet built into the EXE or manually smoke-tested — see "Next session"
below). Built in dependency order (each item's UI additions finished
before the theme audit that has to cover them):

- **Models tab redesign (was #1):** Fast/Accurate tiles now side by side
  (`ttk.Frame` with two equal-weight grid columns) with an "Optimize
  Narration" section below for the grammar engine (benefit-framed
  label, no "AI"/"LLM"/"grammar model"/"engine" wording, per the
  spec's benefit-framing rule; renamed from "Writing cleanup" on
  2026-07-20 at the user's request — "Grammar Engine" was considered
  and rejected for breaking that same rule) with a Delete button.
  `grammar_engine.delete()` added: unload() + gc.collect() before
  rmtree (Windows file-lock timing). Deleting is still a one-way door
  in-app (no HF repo published yet) — went with the "strong warning"
  option from the two agreed on July 19: the confirm dialog says
  reinstalling Sumit Speak is the only way back.
- **In-use tile visual state (was #2):** accent-bordered `ttk.LabelFrame`
  style (`InUse.TLabelframe` / `.Label`) plus a filled "✓ In use" badge
  (a plain `tk.Label`, not ttk) replaces the old "In use ✓" text.
- **New app icon (was #3):** `assets/generate_icon.py` draws a mic glyph
  on a steel-blue squircle (reuses the existing `#4682b4` brand blue, no
  new palette) and emits `assets/icon.ico` (multi-res, for
  `--icon`/`SetupIconFile`) plus `sumit_speak/app_icon.py` (a base64 PNG
  + `set_window_icon()`, since Tk windows show their own default
  "feather" icon regardless of the EXE's resource icon — wired into
  settings/try-it-now/updater-dialog). Tray circles restyled from plain
  ellipses to squircles to match. Re-run the generator script (never
  hand-edit its two outputs) if the design changes.
- **Feedback channel (was #4):** `feedback.py` — sends via FormSubmit.co
  (`https://formsubmit.co/ajax/sumitdas76@gmail.com`, chosen over
  Web3Forms/Formspree because it needs no signup), tagged with a random
  persisted `install_id` (settings key, added by this session's testing
  — already in the real settings.json). Replies are polled once a day
  from `FEEDBACK_REPLIES_URL` (a `replies.json` file in the
  sumit-speak-updates repo, same pattern as the update manifest) and
  shown both as a tray toast and persistently in the About tab. **Two
  loose ends:** (a) `replies.json` doesn't exist in the repo yet —
  polling silently finds nothing until Sumit creates it (e.g.
  `{"replies": {"<install_id>": {"reply_id": "1", "text": "..."}}}`);
  (b) FormSubmit requires a one-time confirmation click in Gmail on the
  very first real Send before it starts forwarding — hasn't happened
  yet, no live Send has been fired.
- **Spoken no-focus cue (was #5):** `speech.py` — SAPI renders into an
  `SpMemoryStream` (16kHz/16-bit/mono) instead of playing directly, so
  the PCM can go through sounddevice and honor `OUTPUT_DEVICE` like the
  tones do; prefers the "Zira" voice (confirmed present on this
  machine), falls back to the default. Replaces the old blocking
  `show_error_popup`/`no_target_message` at both focus-check sites with
  a toast + spoken cue (`app.py`'s `_no_target_cue`), volume scaled from
  `SOUND_VOLUME`.
- **Audio output-device dropdown (was #6):** new `OUTPUT_DEVICE` config
  + `output_device` settings key, second combobox on the Audio tab
  (mirrors the mic one, filtered on `max_output_channels`). Tones moved
  from `winsound` to `sounddevice.play(..., device=OUTPUT_DEVICE,
  blocking=True)` (`_tone_samples` replaces the old WAV-bytes
  `_tone_wav`).
- **Hotkey chords (was #7):** `config.HOTKEY` is now always a tuple (1
  or 2 pynput Key/KeyCode objects), even for a single key.
  `settings._parse_hotkey` accepts both the old plain-string format and
  a new list-of-1-2 format. `app.py`'s listener tracks a
  `_hotkey_pressed` set restricted to keys that are part of the
  configured chord; the full set down starts recording, any one release
  stops it. `keynames.friendly` now also accepts a tuple/list and joins
  with " + ". Settings' hotkey capture UI holds-and-releases up to two
  keys (capped, extra keys ignored) instead of firing on the first
  keypress.
- **Theme hover-highlight audit (was #8):** the reported bug (clam's
  unmapped "active" state painting checkbutton/radiobutton rows white)
  is fixed with `style.map(... background=[("active", bg)])`. Also
  audited and fixed: button disabled state, Treeview selected-row
  colors, the Combobox popdown listbox (a raw Tk Listbox — needs
  `option_add("*TCombobox*Listbox...")`, not `style.configure`),
  progressbar colors, entry focus border, and the raw feedback `tk.Text`
  box's colors (including on a live theme switch, which ttk widgets get
  for free but raw Tk widgets don't).
- **Cloud speech-to-text (was #9): rejected, not deferred.** Asked
  directly (provider choice + who pays for the API key), the answer was
  to skip the concept entirely — Sumit Speak stays local-models-only.
  Don't re-propose this in a future session without the user raising it
  first.

**Next session — start here:**
1. Rebuild the EXE (`--icon assets\icon.ico` is now part of the
   PyInstaller command — see Commands above) and copy to both EXE
   locations, per the usual gotchas in this file. Two `SumitSpeak.exe`
   instances were already running when this session's work was done, so
   none of it has been through a real build or manual smoke test yet —
   re-confirm kill-rebuild-relaunch approval before stopping them.
2. Manually exercise: the redesigned Models tab (including deleting/
   restoring the grammar engine's Delete button warning), the hotkey
   chord capture UI end-to-end with a real 2-key combo, the output
   device dropdown actually routing tones to a non-default device, the
   spoken cue by dictating with nothing focused, and both themes for
   leftover hover/contrast issues this session's audit might have
   missed.
3. When ready, click Send once in the About tab's Feedback box for
   real, then check sumitdas76@gmail.com for FormSubmit's one-time
   confirmation link.
4. Create `replies.json` in the sumit-speak-updates repo (empty
   `{"replies": {}}` is enough to start) so the reply-polling path has
   something to find.

Remaining Phase 4 after the queue: explanatory failure toasts with
distinct sounds (nothing heard / too short / no editable field),
recovery-clipboard toast. Optional later: GitHub Pages download page,
code signing (~$70-300/yr) to silence SmartScreen.
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
- **Tk multi-interpreter crashes (root-caused and fixed July 20, 2026,
  in two passes):** the app crashed repeatedly with the identical fault
  -- `tcl86t.dll`, exception `0x80000003` (Tcl's `panic()`), same offset
  every time, confirmed via Windows crash dumps
  (`%LOCALAPPDATA%\CrashDumps\SumitSpeak.exe.*.dmp`) 4 times across
  2026-07-19 and 2026-07-20. Root cause: a process should have at most
  one `tk.Tk()` root -- Tcl/Tk's threading model is fragile when
  independent interpreters run concurrently on different threads in the
  same process. Five places each created their own `tk.Tk()` on their
  own thread: `pill.py` and `error_toast.py` (both persistent background
  threads), plus `settings_window.py`, `try_it_now.py`, and
  `updater.py`'s update dialog (each spun one up on open).
  First pass fixed only `pill.py`/`error_toast.py` via a new
  `overlay_thread.py` owning one shared root; a crash with the identical
  signature happened again ~15 minutes later (13 minutes after the last
  dictation, no dictation activity logged in between -- consistent with
  Settings being open at the time), confirming the other three were
  still live risks. Second pass folded all three into the same
  `overlay_thread.py`: each now builds a `tk.Toplevel` off the one
  shared root instead of its own interpreter, and instead of blocking on
  their own `mainloop()` until closed, they hook cleanup (settings:
  `_on_closed`/revert-preview-mutations; try-it-now:
  `first_run_done`; update dialog: `on_download`/`on_cancel`) to the
  window's close action instead. `settings_window.py`'s
  `_model_delete` also had a latent bug this surfaced: it assumed a
  second model tier always existed to "switch to first" -- true before
  the Accurate-tier removal below, not after.
  Verified with a mixed concurrent stress test -- pill, toast, repeated
  Settings opens, and repeated update-dialog opens, all cycling at once
  from separate threads -- with no crash. As before, an intermittent
  crash can't be proven fixed by a short test; there is no other `tk.Tk()`
  call left in `sumit_speak/` (`overlay_thread.py` is the only one) so
  the *known* instances of this bug class are gone, but watch for
  recurrence.

## Grammar engine behavior change (2026-07-20) and open item

At the user's request, the app now runs **Fast (small.en) only** for
speech recognition, to lean more on the grammar pass for quality instead.
First pass only deleted the Accurate (large-v3-turbo) model's downloaded
files (~1.5 GB freed); the user clarified they wanted the *feature*
removed, not just its files, so `model_manager.MODELS` now has a single
"fast" entry (Accurate's entry deleted outright, not just unselected) and
`updater.MANAGED` no longer has a `speech-accurate` key, so it's not
checked for updates either. The Models tab's tile layout is no longer
hardcoded to two side-by-side columns -- it sizes to however many tiers
exist, so the one remaining tile spans the full width instead of leaving
an empty half. Re-adding a second tier later is a config change
(`model_manager.MODELS`), not a UI rewrite.

**Models tab follow-up (2026-07-21):** removed the "in use" accent
border/badge from the model tile (`InUse.TLabelframe` style deleted too,
now unused) -- meaningless with only one voice model to distinguish it
from. In its place, each tile now shows "Version N", reading the same
`version.txt` marker `updater.installed_version()` already wrote on every
update (no new tracking added) -- refreshed every poll cycle regardless
of tile-state caching, so it visibly ticks up if a background update
swaps in while Settings is open. This was in answer to the user asking
how an update is reflected in the tile -- previously nothing changed in
the tile itself during a background update, only a static text line
below the tiles ("An update is downloading in the background…"); there
was and still is no per-tile progress bar for updates specifically (the
tile's own "Downloading…" progress bar is only for the fresh-download
path via the Download button, a separate code path).

The grammar engine's leash was deliberately loosened to match: it no
longer only fixes grammar/punctuation, it now rewords genuinely garbled
or unclear sentences (`grammar_engine._SYSTEM` updated, a new few-shot
example added, `GRAMMAR_MIN_RETENTION` 0.7→0.4, per-sentence retention
floor 0.5→0.2). This is a real philosophy shift away from the original
"never substitute synonyms" strict leash, made with the user's informed
consent after being shown the tradeoff (the original strict guards exist
*because* a more liberal model version previously deleted a sentence
live).

Live-tested against the actual deployed model (Qwen2.5-1.5B int8) before
shipping, not just designed on paper. Found a real, concrete failure the
same night: "I want you to take care of this going ahead" →
"I will take care of this going ahead." — a pronoun swap that flips who's
responsible for an action, passing the word-retention guards fine since
the rest of the sentence survives (only "you" vanishes). Added
`grammar_engine._second_person_ok`: if "you"/"your"/"you're"/etc. appears
in the input, it must survive in the output, or the guard rejects and
falls back to unchanged text. Re-tested: catches that exact case, doesn't
regress the other (good) rewrites. This is a narrow patch for one
demonstrated failure mode, not a general solve for meaning-inverting
rewrites — watch debug.log for other patterns (e.g. a similar risk likely
exists for "I"/"we" swaps, negation flips ("won't" → "will"), or
conditional/certainty flips ("might" → "will")) and add guards as they
turn up.

**Open, not done:** the user also asked for "a better, more optimized"
grammar model and picked "faster, even if slightly less capable" when
asked what to optimize for. This is unstarted — the existing 1.5B model
is not swapped. A real attempt needs the same kind of dedicated
evaluation the July 19 session did (3 candidates compared against real
debug.log transcripts; two rejected for concrete failures: 0.5B dropped a
sentence, Qwen3-0.6B mangled numbers) — not a quick swap. Whatever
candidate is tried should be re-validated against the *loosened* guards
above (a smaller/faster model is more likely to trip them, not less).

## Checkbox glyph fix (2026-07-21) -- a real ttk theming trap

The clam theme's built-in checkbutton glyph renders as an X rather than a
checkmark on this Tcl/Tk build. This is not a `style.map` color problem --
the glyph shape is a baked-in theme resource, not a configurable color --
so it needed a custom-drawn indicator, same technique as the tray icons
and app icon (`settings_window._draw_checkbox_glyphs`, PIL, drawn at 4x
and downsampled for anti-aliasing).

**The trap:** the obvious approach --
`style.element_create("Checkbutton.indicator", "image", ...)`, reusing
clam's own element name to override it -- fails immediately with
`TclError: Duplicate element`, on the very first call in a fresh
interpreter, not just on re-registration. `"Checkbutton.indicator"` is
already registered the moment `style.theme_use("clam")` runs (verified:
`style.element_names()` shows it present immediately after that call,
before any of this app's code touches it). ttk's image elements don't
support "same name overrides the built-in" the way `style.configure` does
for colors.

**The fix:** create the custom glyph under a *different* name
(`_CHECKBOX_ELEMENT = "SumitCheck.indicator"`), then redefine
`TCheckbutton`'s layout (`style.layout(...)`) to reference that name in
place of clam's own `Checkbutton.indicator`, leaving the rest of the
layout tree (padding, focus ring, label) exactly as clam defines it.
`style.layout()` is idempotent and safe to call every time
`_apply_theme()` runs; `style.element_create()` is not -- guarded by a
module-level `_checkbox_images` flag (not per-window: every Settings
window now shares one persistent interpreter via `overlay_thread.py`, so
a per-`_SettingsWindow`-instance guard would itself hit the same
duplicate-element error the *second* time Settings is ever opened, which
is exactly the bug this went through before landing on the module-level
fix). On repeat theme applies, the already-registered PhotoImages are
repainted in place via `.paste()` rather than recreated, since Tk drops a
PhotoImage once nothing references it and a fresh `_SettingsWindow`
instance's own attributes wouldn't survive the window closing.

If radio buttons or other themed indicators ever need the same kind of
custom-glyph treatment, expect the identical trap and reuse this pattern
(unique element name + layout override + module-level create-once guard),
not the naive same-name override.

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
