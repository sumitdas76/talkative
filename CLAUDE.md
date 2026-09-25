# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Talkative (formerly Sumit Speak, formerly Wispr Lite -- renamed again
2026-08-23; the Python package, internal class names, and the GitHub repos
were brought in line with that rename on 2026-09-13, see CHANGELOG.md):
a Windows tray app for hold-to-talk dictation. Hold **Right Ctrl**, speak,
release — audio is transcribed, cleaned up (fillers, spoken corrections,
near-repeats, personal dictionary), and pasted (clipboard + simulated
Ctrl+V) into whatever control currently has focus. As of 2026-09-13,
**Cloud processing is the shipped default** (see "Cloud-by-default" below
and `cloud/`): transcription and grammar cleanup run on a Cloudflare
Worker unless the user switches to Local in Settings, in which case it's
the original fully-offline faster-whisper + local grammar engine pipeline
with no network calls beyond the one-time model download.

The full product direction (settings UI, model manager, update system,
grammar engine) is specced in the "Sumit Speak — Product Specification"
artifact from the July 2026 consulting sessions (written under the old
name; the spec itself was never renamed); Phase 1 (engine features, no UI)
is implemented.

## Commands

```powershell
# Setup (first time, or after the venv is deleted)
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt

# Run from source
.\.venv\Scripts\python main.py
# or, to avoid a console window (matches how the built EXE behaves):
.\.venv\Scripts\pythonw.exe main.py

# Rebuild the standalone EXE after any source change, and copy it to
# every location on this machine (project root, and the installed copy
# if one exists) -- see scripts/rebuild.ps1 for why this is scripted
# rather than a single manual command.
.\scripts\rebuild.ps1
```

(The raw PyInstaller command, with all `--collect-all` flags, is in
`scripts/rebuild.ps1` if you need it directly for debugging the build
itself.)

`--icon assets\icon.ico` sets the EXE's own icon resource (Explorer, taskbar
pin, Alt-Tab when no window is open). It does NOT change the icon Tk windows
show while open -- Tk defaults to its own "feather" icon regardless of the
EXE resource. That's handled separately in code via
`talkative/app_icon.py`'s `set_window_icon()`, called by each window that
creates its own `tk.Tk()` root (settings, try-it-now, the updater dialog).
Regenerate both `assets/icon.ico` and `talkative/app_icon.py` together by
re-running `assets/generate_icon.py` -- never hand-edit either output.

Use `python -m PyInstaller`, NOT the `.\.venv\Scripts\pyinstaller` exe shim:
the shim is broken in this venv — it exits 1 instantly with **no output at
all**, which looks like a successful quiet run if the exit code is masked
(e.g. by piping to `tail`). This once led to deploying a stale day-old EXE.
After every build, verify `dist\Talkative.exe` has a fresh LastWriteTime
before copying it anywhere.

There is no linter or CI. A sanity-test script for the pure text-pipeline
functions (cleanup, dictionary, self-correction) lives in the session
scratchpad pattern — exercise those functions with real sentences after
changing them. App-level verification is manual (run it, dictate something,
watch the tray icon / target app).

### IMPORTANT: multiple EXE copies, and the file-lock gotcha

Up to **three** copies of the EXE can exist on this machine and none of
them sync automatically: `dist\Talkative.exe` (PyInstaller's raw
output), the **project root** copy the user actually launches from, and
an **installed** copy at `%LOCALAPPDATA%\Programs\Talkative\` (from
testing the Inno Setup installer). `scripts\rebuild.ps1` builds and
copies to all of these that exist in one step — use it instead of
running PyInstaller directly and manually `cp`-ing. This exists
because on 2026-07-22 the installed copy sat two releases behind
without anyone noticing (source-only fixes and installer bumps kept
happening while that copy silently went stale) until the About tab
gave it away.

(Stale `WisprLite.exe` and `SumitSpeak.exe` copies from before each rename
may still exist; they are old builds under the app's previous names.)

PyInstaller fails with `PermissionError: Access is denied` if any copy is
currently running (it can't overwrite a locked EXE) — `rebuild.ps1` checks
for and refuses to run over a live `Talkative` process rather than
guessing whether it's safe to kill it. Before rebuilding manually, check
for and stop running instances yourself:

```powershell
Get-Process Talkative, SumitSpeak, WisprLite -ErrorAction SilentlyContinue | Select-Object Id,StartTime,Path
```

The user frequently has an instance running to test something live — ask
before killing it rather than assuming it's safe to stop.

After rebuilding, do a launch smoke test (start it, confirm the process
stays alive for a few seconds without exiting, then stop it) — this has
caught real packaging issues before (missing DLLs, bad hidden imports).

## Architecture

Everything lives in `talkative/`, wired together by `TalkativeApp` in
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
  reason. Also rejects a bare `ControlTypeName == "WindowControl"` result:
  with nothing actually focused (desktop showing, everything minimized),
  UIA doesn't report "no control" — it falls back to reporting the last
  active window's own top-level frame as focused, which would otherwise
  silently pass the block-list as editable.
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
  config.DEBUG_LOG -> %LOCALAPPDATA%\Talkative\debug.log.
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

## Cloud-by-default processing (added 2026-09-13)

`config.PROCESSING_MODE` defaults to `"cloud"` (was `"local"` when this
was a testers-only prototype). In Cloud mode the app never loads
faster-whisper or the local grammar engine at all -- `app.py`'s
`_cloud_active()`/`_sync_processing_mode()`/`run()` gate all local model
loading behind the mode, and the two model-backed pipeline stages
(`transcriber.Transcriber.transcribe()`, `grammar_engine.apply()`) are
swapped for `cloud_client.transcribe()`/`cloud_client.grammar_apply()`
instead. Local remains fully supported and downloadable any time from
Settings → General → Processing (a combined "Download local models"
button there calls `model_manager.download()` + the new
`grammar_engine.download()`).

**Backend**: `cloud/worker.js` (Cloudflare Worker, account
`sumitdas76@gmail.com` / account id `5c8fd5ee36a5fb2a729762b18950f5fb`),
deployed at `https://talkative-cloud.sumitdas76.workers.dev`. Two routes,
`/transcribe` and `/grammar` (Groq's `openai/gpt-oss-20b` since 2026-09-25,
Workers AI `@cf/meta/llama-3.2-3b-instruct` as automatic fallback; same system
prompt/few-shot shots as `grammar_engine.py`'s `_SYSTEM`/`_SHOTS` for
parity). Both routes require `X-Shared-Secret` (a soft deterrent only --
it's a literal constant in `config.py`, extractable/visible in the public
repo, not real auth) and `X-Install-Id` (the app's existing anonymous
per-install id from `feedback.install_id()`), enforced against a
per-install daily quota (300 combined requests/day, the `QuotaCounter`
Durable Object -- see "Cloud latency" below for why not KV) that returns HTTP 429 on overrun -- `cloud_client.py`
turns that into a friendly "Cloud is busy right now" message rather than a
raw error.

**`/transcribe` moved off Workers AI to Groq (2026-09-19)**: originally
ran `@cf/openai/whisper` (Cloudflare's smaller base model --
`whisper-large-v3-turbo` was tried first and rejected every audio input
shape tested against its schema). Live testing showed the accuracy wasn't
good enough (missed tag-question punctuation, homophone slips), so
`handleTranscribe` in `worker.js` now calls Groq's hosted
`whisper-large-v3-turbo` (the real large-v3-turbo weights) via
`https://api.groq.com/openai/v1/audio/transcriptions`, using a
`GROQ_API_KEY` secret (`wrangler secret put GROQ_API_KEY`, a free-tier key
from console.groq.com, no card required). `/grammar` is unchanged, still
on Workers AI's llama-3.2-3b-instruct (moved to Groq 2026-09-25, see
"Cloud latency" below). Verified live: punctuation
(question marks, ellipses) noticeably improved; occasional near-homophone
misses (e.g. "collars" heard as "colors") remain -- normal Whisper-family
ASR noise, not a regression from this change, and not fixable via
`dictionary.py` without breaking legitimate uses of the substituted word.

**Controlled A/B testing (2026-09-19)** found Cloud (Groq) and Local
(faster-whisper `small.en`) roughly tied on word accuracy given the exact
same audio (same buffer sent to both, via `cloud_client.transcribe()` and
a standalone `Transcriber` -- see the session's throwaway test script,
not checked into the repo), but surfaced one reproducible, fixable Cloud-
only bug: **trailing-silence hallucination**. Groq's endpoint reliably
appended a stock closing phrase ("Thank you." every time observed) when a
dictation ended in silence before the recording stopped -- a well-known
Whisper-family artifact from training on captioned video, 5-for-5
reproducible in testing. Local never did this once, because
faster-whisper's own `vad_filter=True` already drops trailing silence
before the model ever sees it. Fixed the same way for Cloud:
`cloud_client.py`'s new `_trim_trailing_silence()` does a coarse
energy-based trim of trailing near-silence from the audio buffer
*client-side, before it's sent* -- deliberately conservative (leaves
audio completely unchanged on any ambiguous signal) because blindly
stripping a trailing "Thank you." from the *text* instead would risk
deleting a genuinely spoken one, which a dictation tool ending an email
with "Thank you." would hit constantly. Root-cause fix, not a text-level
guard.

**The real cost ceiling is not the shared secret or the quota** -- it's
each upstream provider's own free-tier cap hard-erroring rather than
billing, as long as neither account has billing enabled: Workers AI's
account-wide 10,000 neurons/day (now only `/grammar`'s fallback), and
Groq's no-card free tier (~2,000 requests/day, ~8 hours of audio/day as of
2026-09) backing `/transcribe`, plus its separate per-model limits for
`gpt-oss-20b` backing `/grammar`. Do not add a payment method to either
account without re-deriving what that changes for worst-case cost
exposure.

**Cloud latency (2026-09-25)**: user reported 3-5s per Cloud dictation.
Each Worker response now carries a `timing` object (`quota_ms`,
`quota_count`, `upstream_ms`, `groq_total_ms`, `colo`) -- use it to measure
rather than guess. Findings, from the Mumbai colo (BOM): Workers AI grammar
took ~1-1.5s; the KV quota read+write cost ~600ms on *every* request; the
Groq model itself only ~67ms, with ~300ms more being the BOM<->Groq network
hop. Changes: `/grammar` moved to Groq `openai/gpt-oss-20b`
(`reasoning_effort: "low"`, `include_reasoning: false`; Workers AI kept as
fallback, response `via`/`groq_error` fields say which ran and why).
**Groq's Llama chat models are enterprise-only as of 2026-09** -- a free key
gets 404 `model_not_found` for `llama-3.1-8b-instant`. gpt-oss emits curly
quotes / narrow no-break spaces, normalized by `plainText()` in the Worker.
Quality spot-check was better than the 3B model (kept "before Friday",
idioms, "I want you to"), but it converts spoken numbers to digits, which
the client-side digit guard then rejects (falls back to un-grammared text)
-- the old model did this too; not yet addressed. Quota moved from KV to a
Durable Object because KV's per-colo read caching under-counted badly
(10 requests -> count of 2, even with awaited writes ~2x under); the DO
counts exactly but still costs ~75ms or ~650ms per call (bimodal, cause
not yet investigated). Smart Placement enabled in `wrangler.toml`; it only
takes effect after Cloudflare samples traffic (`Cf-Placement` response
header shows `local-BOM` until then). Net: ~2-3s -> ~1-1.7s for both calls.
`wrangler deploy` from Claude Code is blocked by the auto-mode classifier;
the user runs it via `! npx wrangler deploy` from `cloud/`.

**Hybrid grammar source (added 2026-09-19)**: `config.GRAMMAR_SOURCE`
("auto" default, or "local") decouples the grammar cleanup stage from
`PROCESSING_MODE` -- lets Cloud transcription pair with the local
`grammar_engine` instead of Cloud's own grammar model, for users who want
Cloud's STT but a locally-run grammar pass. `app.py`'s
`_grammar_uses_local()` is the single source of truth for which path runs
on a given dictation (falls back to Cloud grammar automatically if the
local model isn't installed); `_sync_grammar_source()` keeps the local
engine loaded/unloaded to match, independent of whether `PROCESSING_MODE`
itself just changed. Exposed in Settings → General → Processing as a
checkbox under the two radio buttons, only enabled while Cloud is
selected. `debug.log`'s per-dictation `[cloud]`/`[grammar]` tag now
reflects the actual grammar path used, not just `PROCESSING_MODE`.

**First-run onboarding screen (added 2026-09-19)**: `onboarding.py` (same
`overlay_thread.py`/single-shared-Tk-root pattern as `try_it_now.py` and
`cloud_notice.py`) shows a one-time Cloud-vs-Local choice screen with
plain-language RAM/disk numbers for each, gated by a new
`config.ONBOARDING_DONE` settings key. Because that key is absent from
every `settings.json` written before this existed, it defaults `False`
and the screen shows once to existing installs updating to this version
too, not just fresh ones -- deliberate, at the user's request. Non-
blocking by design: `app.py`'s `run()` starts dictation under whatever
`PROCESSING_MODE` is already configured (Cloud, normally) while the
screen is still open; its `on_choice` callback just calls
`_sync_processing_mode()` again if the user's answer differs from that
default, reusing the exact same sync path Settings already uses. Picking
Local downloads both models right there (blocking only the onboarding
window, with a progress bar) via the same `model_manager.download()` +
`grammar_engine.download()` pair Settings' "Download local models" button
calls, so onboarding hands off a fully working offline setup rather than
leaving the grammar engine as a separate later step. Picking Cloud also
pre-marks `CLOUD_NOTICE_DONE`, since the onboarding screen already covered
that ground -- avoids showing `cloud_notice.py`'s notice right on top of
it. The installer's uninstall data-removal prompt (see `installer/
Talkative.iss`) already deletes the whole `%LOCALAPPDATA%\Talkative`
folder (models included) when the user opts in -- only its wording was
tightened to say "voice and grammar models" explicitly, no new logic was
needed there.

**Genuine fresh-install test (2026-09-19) caught two more real bugs**,
neither reachable by running from source, both shipped in v1.3.0 until
fixed same-day. Method: backed up this dev machine's real
`%LOCALAPPDATA%\Talkative`, ran the actual built `TalkativeSetup.exe`
silently (`/VERYSILENT /SUPPRESSMSGBOXES`), and drove onboarding's Local
path for real -- not a code-review guess, which had originally (wrongly)
been judged sufficient confidence to skip this test.

1. `sys.stdout`/`sys.stderr` are `None` in a PyInstaller `--windowed`
   build (no console attached) -- `huggingface_hub`'s tqdm-based download
   progress bars write to them unconditionally and crashed with
   `'NoneType' object has no attribute 'write'` the instant a download
   actually ran inside the frozen EXE. Every prior test of this code path
   ran from source, where a real console exists, so this was invisible
   until now. Fixed in `main.py`, first thing, before importing
   `talkative.app`: redirect both to `open(os.devnull, "w")` when `None`.
2. Onboarding's window used a hardcoded `.geometry("540x520")`. Once the
   Local box grew to three bullet points the content exceeded that height
   and, since the window was also `resizable(False, False)`, the Continue
   button was silently pushed off-screen with no visible error -- looked
   like a missing button, not a sizing bug. Fixed by removing the
   `.geometry()` call entirely instead of guessing a bigger constant:
   `_build()` now calls `root.update_idletasks(); root.geometry(...)`
   nowhere at all, leaving Tk's own pack-based geometry propagation
   active continuously, so it also correctly re-sizes later when the
   download progress bar appears.

Also replaced the indeterminate "bouncing" progress bar with a real
determinate one during onboarding's download, at the user's request: no
per-file byte callback is wired through `huggingface_hub` (more invasive
than warranted), so it instead polls `model_manager.storage_used_mb()`
against a hardcoded approximate total (464 MB voice + 1490 MB grammar,
whichever are actually needed) every 500ms -- simple, good enough for a
progress indicator, not exact accounting.

**Known trap hit during setup**: `wrangler deploy` silently succeeds
uploading code but fails to make the Worker reachable until a workers.dev
subdomain route is explicitly enabled -- not exposed as a wrangler CLI
flag in a non-interactive shell; done once via the dashboard (Worker →
Domains → the "Worker URL" toggle, not the "Custom Domains and Routes"
section above it, which is a different, unrelated control). Also:
Cloudflare's edge bot-protection 403s Python's stock `urllib` User-Agent
before requests ever reach the Worker -- `cloud_client.py`'s `_headers()`
sends a browser-like User-Agent for exactly this reason, the same fix
already used in `feedback.py` for FormSubmit.

**Grammar engine on-demand download**: previously installer-bundled-or-
nothing (see the Deferred/known-issues section below, now superseded).
`config.GRAMMAR_HF_REPO` (`sumitdas76/talkative-grammar`) is meant to be a
public Hugging Face repo holding the same CTranslate2 int8 conversion;
`grammar_engine.download()` uses `huggingface_hub.snapshot_download()`
into `engine_dir()`. The Models tab's grammar tile now has a real Download
button (previously Delete-only).

**That repo did not actually exist until 2026-09-19.** Despite this
section claiming otherwise since it was written, `sumitdas76` had zero
public HF models -- `grammar_engine.download()` (and the identical
on-demand path onboarding.py's Local branch now also uses) 404'd for
*anyone* attempting a genuinely fresh download, this dev machine's own
already-cached copy (from the original July 2026 installer-bundled era)
just meant nobody had hit it. Caught by the fresh-install onboarding test
below, not by code review. Fixed by publishing this exact machine's
already-working `<models>/grammar` files (the same Qwen2.5-1.5B int8
conversion referenced throughout this doc) to that repo for real via
`HfApi().create_repo()` + `upload_folder()`, verified afterward with a
real `hf_hub_download()` call, not just `model_info()`. Pure data fix, no
app code changed -- v1.3.0 (already released, shipped with this same bug)
needed no new build or version bump, it just started working once the
repo existed.

**One-time notice**: `cloud_notice.py` (mirrors `try_it_now.py`'s exact
plumbing -- see that module's docstring) explains Cloud mode and points at
the Local download, shown once via `config.CLOUD_NOTICE_DONE`.

## Current status / resume point (saved July 19, 2026, Phase 3 session)

Phases 1–3 (engine, settings window, model manager) were implemented in
this era of the project (models live in an app-owned folder, migrated
from the Hugging Face cache on first launch of the new code).

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
`installer\SumitSpeak.iss` (renamed `installer\Talkative.iss` in the
2026-08-23 app rename — use the current filename, not this one);
compile from the project root with
`& "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe" installer\Talkative.iss`
(per-user winget install — NOT under Program Files) after a fresh
PyInstaller build. Output:
installer\Output\TalkativeSetup.exe (~1.6 GB — bundles the grammar
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

**Change-request queue items 1-8 implemented July 20, 2026** (shipped in
later releases; source notes below are kept only where they explain a
convention or a one-way decision, not as a build-status log):

- **Benefit-framing rule for user-facing labels:** never use
  "AI"/"LLM"/"grammar model"/"engine" wording in the UI — the grammar
  engine is presented as "Optimize Narration". "Grammar Engine" was
  considered and rejected for breaking this same rule.
- **Deleting the grammar engine is a one-way door in-app** (no HF repo
  published yet): the confirm dialog says reinstalling the app is the
  only way to get it back.
- **Feedback channel loose ends, still open:** `feedback.py` sends via
  FormSubmit.co, tagged with a persisted `install_id` settings key.
  (a) `replies.json` doesn't exist yet in the sumit-speak-updates repo —
  reply-polling silently finds nothing until it's created (e.g.
  `{"replies": {"<install_id>": {"reply_id": "1", "text": "..."}}}`);
  (b) FormSubmit requires a one-time confirmation click in Gmail on the
  very first real Send before it starts forwarding — unclear whether
  that's happened yet.
- **Cloud speech-to-text: rejected, not deferred.** Asked directly
  (provider choice + who pays for the API key), the answer was to skip
  the concept entirely — the app stays local-models-only. Don't
  re-propose this without the user raising it first.

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
- **DEBUG_LOG privacy:** `%LOCALAPPDATA%\Talkative\debug.log` stores
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
  call left in `talkative/` (`overlay_thread.py` is the only one) so
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

## Resume point (end of session, 2026-07-21 ~01:15)

**Published:** v1.1.0 is live on GitHub (source pushed and merged with
the product-page repo's history, `CHANGELOG.md` added, installer rebuilt
and published as the new "latest" release). Full detail in the sections
above; see `CHANGELOG.md` for the user-facing summary of this whole
session.

**Tray icon:** now shows the mic glyph inside the squircle badge (was a
plain color block before this fix -- `tray._make_icon_image` draws it at
4x and downsamples, same technique as everywhere else). Confirmed correct
by extracting the actual pixels and viewing them, not just by reasoning
about the code.

**Not yet resolved -- start here next session:** the taskbar icon still
shows a stale icon (reported as looking like a floppy disk) even though
the EXE's own embedded icon resource is confirmed correct (extracted and
viewed directly via `System.Drawing.Icon]::ExtractAssociatedIcon`). This
points to Windows' icon cache holding onto an old icon for this EXE path
across the many rebuilds tonight, not a bug in the build. Standard fix:
clear the icon cache and restart `explorer.exe` -- flagged to the user as
a real system-wide action (briefly closes/reopens all Explorer windows,
not just this app) and awaiting their go-ahead before doing it. If a
pinned taskbar shortcut exists, it may need unpinning/re-pinning too
(pinned shortcuts can carry their own separately-cached icon reference
independent of the target EXE).

**Also still open (from the grammar-engine section above):** finding an
actually faster/different grammar model remains unstarted -- needs its
own dedicated evaluation pass (download candidates, convert to
CTranslate2, test against real debug.log transcripts), not a quick swap.

## Resume point (end of session, 2026-07-22)

**Crash fixed and shipped to source (not yet a numbered release):** the
user reported dictating with no window focused, seeing the red error
toast, then the app crashing. Root-caused from a live Windows crash
dump (`%LOCALAPPDATA%\CrashDumps\SumitSpeak.exe.3864.dmp`, captured
07:09 that morning) by hand-parsing the minidump's exception stream and
module list (no windbg/cdb available on this machine) -- exception was
`STATUS_HEAP_CORRUPTION` (`0xC0000374`) faulting inside `ntdll.dll`,
with `sapi`/`_tkinter`/`tcl86t.dll` strings present, pointing at the
no-target-focus path (`app._no_target_cue`, which calls `speech.speak`
-- SAPI via `win32com.client.Dispatch`).

Actual bug: `app.py`'s `_on_press` had no guard against Windows' OS
key-repeat. While the user held Ctrl over an unfocused window,
`_recording` never became `True` (recording never starts on that path),
so *every* repeat event replayed the full handler body, including the
SAPI/COM voice-cue call -- flooding many concurrent
`win32com.client.Dispatch` calls in a short window. pywin32's
gencache/type-building isn't safe under concurrent first-use from
multiple threads, which is the likely proximate cause of the heap
corruption. Fixed with a `self._chord_active` guard: only the first
physical key-down of the configured hotkey chord is handled; a release
re-arms it (`_on_press`/`_on_release`/`_apply_settings` in `app.py`).
Also serialized the SAPI `Dispatch`/`Speak` sequence in `speech.py`
behind a module-level lock as defense-in-depth, independent of whether
the repeat bug is the only trigger.

**Any future hotkey-triggered handler needs the same repeat-awareness**
-- `pynput`'s `on_press` does not deduplicate OS auto-repeat on
Windows; only guard against it once, centrally, if adding new
press-triggered logic outside the existing chord-active check.

Rebuilt `SumitSpeak.exe` (PyInstaller command must be run from
PowerShell in this repo, not Bash/Git Bash -- Bash eats the backslash
in `--icon assets\icon.ico`, silently mangling it to `assetsicon.ico`
and failing the build), copied to both `dist\` and the project root,
smoke-tested (launched, stayed alive, left running for the user to
manually confirm holding the hotkey over an unfocused window no longer
crashes). Committed as its own commit (`sumit_speak/app.py`,
`sumit_speak/speech.py` only) and pushed to `origin/main`, along with
the previously-unpushed 2026-07-21 resume-point commit. `CHANGELOG.md`
got an `[Unreleased]` section for this fix, also committed and pushed.

## Resume point (end of session, 2026-09-13)

**Context:** this was the session that finished the sumit_speak→talkative
rename and built Cloud-by-default processing (see that section above) --
both already staged/implemented when this particular resume began. This
part of the session focused on a live accuracy bug the user hit testing
Cloud mode.

**Bug found (via debug.log, not guesswork):** Cloud-mode dictations were
coming back with the *grammar* stage paraphrasing perfectly clear,
already-grammatical sentences instead of leaving them alone -- e.g. raw
transcript "I don't know what's happening man, but I think everything is
going to the dogs." came back from the grammar pass as "I don't know
what's happening, but everything seems to be falling apart." The `raw`
transcript was accurate both times; this is not an STT/accuracy problem,
it's the grammar-cleanup LLM over-applying the "reword garbled/unclear
sentences" instruction added 2026-07-20 to sentences that were never
garbled, just idiomatic. It passed the word-retention guards fine (~57%
kept, well above the 0.4 floor) since those guards check *how much*
survives, not *whether rewording was warranted*. Cloud's weaker model
(`@cf/meta/llama-3.2-3b-instruct` vs. local's evaluated Qwen2.5-1.5B)
triggers this more often, but the same prompt wording is shared by both
engines, so local mode is presumably exposed to a lesser degree too --
worth re-checking against debug.log if it turns up there.

**Two fixes made and verified compiling, not yet re-tested live end to
end:**

1. `talkative/grammar_engine.py`'s `_SYSTEM` and `cloud/worker.js`'s
   `SYSTEM` (kept in sync per existing convention) were both reworded to
   state plainly that most sentences are already clear and should only
   get grammar/punctuation fixes -- rewording is only for genuinely
   garbled/hard-to-follow sentences, and idioms/word choices should be
   left alone even if a plainer version occurs to the model. **worker.js
   has been deployed** (`wrangler deploy`, Version ID
   `0c348824-5022-4941-a754-feccc64aa1a8`) -- this half is live. The
   `grammar_engine.py` half only takes effect on the next run-from-source
   or rebuild (see below -- not done yet).
2. A second, smaller confusion the user hit while debugging the above:
   `debug.log`'s per-dictation timing line always appended
   `[{config.GRAMMAR_MODEL_DIR}]` (a static `"grammar"` string) whenever
   any grammar pass ran, local *or* cloud -- so cloud-mode log lines
   looked like evidence the local engine had run, when `app.py`'s
   `_cloud_active()` branch (line ~391) was actually correctly calling
   `cloud_client.grammar_apply()` the whole time. Fixed at `app.py`'s
   `_debug_log` call site to print `[cloud]` when `_cloud_active()`, the
   existing `[grammar]` tag otherwise.

**Blocked, needs the user:** rebuilding to pick up fix #2 (and the local
half of fix #1) requires stopping the currently-running `Talkative.exe`
(PID 2964 at last check, launched 22:39:38 from the pre-fix build) --
`scripts\rebuild.ps1` refuses to run over a live process by design.
Killing it via `Stop-Process` was denied by the Claude Code auto-mode
permission classifier ("Interfere With Workloads") even after the user
had already authorized stopping it earlier in the session -- it needs
either the user closing the app themselves (tray icon -> Exit, or Task
Manager) or a fresh explicit confirmation next session.

**Next steps on resume, in order:**
1. Stop the running `Talkative.exe`.
2. `.\scripts\rebuild.ps1`, then the usual launch smoke test (stays alive
   a few seconds, no crash).
3. Re-test the exact repro phrase ("everything is going to the dogs") in
   both Cloud and Local mode, confirm the grammar pass now leaves the
   idiom alone and that `debug.log` shows `[cloud]` for the cloud-mode
   run.
4. `CHANGELOG.md`'s `[Unreleased]` entry does not yet mention either fix
   from this part of the session -- add a line once the retest confirms
   they actually work, don't just narrate the intent.
5. Nothing from this session has been committed yet (still the same
   large staged rename + unstaged cloud-feature diff from before this
   part of the session began) -- commit is still the user's call.

## Resume point (end of session, 2026-09-20)

**Shipped this session:** a deep stress-testing pass (six rounds of
synthesized-audio QA covering fast/rambling speech, chained corrections,
technical text, and accents -- Indian English, New York English) found
and fixed several real dictation-pipeline bugs across `cleanup.py`,
`self_correction.py`, `grammar_engine.py`, `dictionary.py` (filler/period
corruption, `collapse_repeats` over-deletion, a stopword-bypass in the
grammar retention guard, self-correction's whole-span retraction having
no size cap -- twice tightened after live testing found it too
permissive -- and a dictionary-expansion-inside-fused-paths bug), plus
redeployed `cloud/worker.js` (the idiom-preservation fix from an earlier
session had been committed but never actually pushed live). Released as
**v1.3.2**. Two more real bugs surfaced by the user actually using the
installed app -- a Settings-window layout bug (hardcoded `600x480`
geometry no longer fit the content, squeezing the Save/Close bar to
~1px on every tab) and the app not stopping on uninstall (installer had
zero process-termination logic) -- released as **v1.3.3**. A follow-up
UX fix (Cloud endpoint field made read-only, since a mistyped value
there silently broke Cloud dictation with a confusing raw error) shipped
as **v1.3.4**, currently the live "Latest" release.

**New standing QA scope** (saved to memory, carries into future
sessions): UI/window layout (scripted `winfo_reqheight()` checks, no
visual tooling exists in this environment) and process lifecycle
(confirmed live: force-killing the onefile bootloader's parent process
does NOT reliably kill its child -- verified by deliberately killing a
parent and watching the child survive as an orphan for minutes).

**Rough-cut stage, not yet final-quality rendered or published:** a
cinematic walkthrough video (install + full Settings tour) at
`videos/talkative-walkthrough/`, built via a long-running forked agent
(resume by messaging agent id/name `aa9fba3d1dbdeb3f8` in this project's
session if further changes are needed, or check `ListAgents` if that's
gone stale). No desktop-control tooling exists in this environment, so
the installer/onboarding/Settings scenes are faithful HTML recreations
of the real UI (pulled from `settings_window.py`/`onboarding.py`'s
actual copy and control layout, not screen capture); the GitHub
release-page scenes are real captures via Chrome automation. Voiceover
is local Kokoro TTS (`am_adam`); music is local MusicGen (called
directly via a standalone Python script, since no hyperframes CLI
command invokes it and no HeyGen credential exists for the catalog path)
in a moody synthwave/retro-electronic style -- genre direction only,
deliberately not reproducing any specific copyrighted melody.

Current render (committed to git):
`videos/talkative-walkthrough/renders/talkative-walkthrough-v6.mp4`,
2:06.7 (126.7s). This is the sixth revision round; each prior round's
notes and fixes are in this session's conversation history if the exact
history of what changed matters later. As of this render: dead-time gaps
closed across every scene (audited from the real on-disk timeline, not
assumed), the scene-1 jitter root-caused to parallel-render-worker
capture divergence and fixed via single-worker rendering (no animation
code changed), cursor targets on the SmartScreen mockup and install
wizard re-measured against actual rendered button positions, the
install wizard tightened to 7.3s (third round), and the listening-pill
scene rebuilt to match `pill.py`'s real behavior (rolling 12-bar level
meter, not a static pulse). **Known open item:** the music bed is
last-round's synthwave attempt trimmed to fit, not a fresh generation --
new MusicGen attempts at the current runtime hit the model's hard
2048-token position limit and errored; a longer-form generation approach
(chunking, or accepting a shorter loop with a crossfaded seam instead of
the current hard-repeat loop) is still open if a better track is wanted.
No thumbnail/YouTube-metadata pass has happened against this specific
render yet (the existing `thumbnail.png` predates several revision
rounds) -- reconfirm it still matches before publishing anywhere.

Two things still open beyond the video: YouTube title/description were
drafted in-conversation (not saved to a file); and the LinkedIn post
draft from earlier in the session was never actually posted by the
user, last known state was a revision incorporating their voice/tone
feedback.

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
