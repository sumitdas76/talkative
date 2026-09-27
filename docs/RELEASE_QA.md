# Release QA checklist

Every check here exists because a real bug shipped or nearly shipped. Run
it for every release, on the **CI-built** files, before publishing the
draft (see `.claude/skills/release/SKILL.md`).

```powershell
# Automated checks (IDs marked "auto" below). Needs a desktop session:
# it opens windows and a sandboxed copy of the app.
.\.venv\Scripts\python scripts\release_qa.py --exe <path to the CI-built Talkative.exe>
# add --grammar to also run the grammar-guard evaluation (~3 min)
```

Then do the manual items and note any skipped ones in the release notes
or the tracker. A check that has never been done is marked **never
verified** -- do it the next time it's practical.

## Build & packaging

| ID | Check | How | Why it exists |
|---|---|---|---|
| B1 | Version identical in `talkative/__init__.py` and `installer/Talkative.iss` (and the tag) | auto + CI | About tab showed the old version in v1.1.1 and v1.1.2 |
| B2 | The EXE bundles Tcl/Tk data | auto + CI | 1.3.6-1.3.8 crashed at launch: Python 3.14.7's Tcl 9 couldn't be bundled |
| B3 | The launched EXE shows no crash dialog | auto + CI | Same bug; the old smoke test passed because the dialog keeps the process alive |
| B4 | Only one `tk.Tk()` in `talkative/` | auto | Repeated `tcl86t.dll` crashes from several Tk roots (July 2026) |
| B5 | Local builds: `python -m PyInstaller`, never the `pyinstaller` shim; `dist\Talkative.exe` has a fresh timestamp | manual | The shim exits silently; a day-old EXE got deployed (July 2026) |
| B6 | Release asset named exactly `TalkativeSetup.exe`, with a `sha256:` digest on `/releases/latest` | manual (release skill step 7) | The in-app updater looks for that name and refuses an update without a digest |

## First run (fresh sandbox, CI-built EXE)

| ID | Check | How | Why it exists |
|---|---|---|---|
| F1 | A fresh launch opens exactly one window (the Cloud/Local choice) and leaves the Windows startup list alone | auto | Two first-run windows at once (found in the 1.3.9 test); a test copy could rewrite the Run key |
| F2 | Every control on that window is visible (Continue included) | manual: look at the window | Continue pushed off-screen by a fixed window size (v1.3.0) |
| F3 | Choosing Local completes with **real** downloads: dictation ready after the voice model, Optimize Narration arrives in the background | manual (release skill step 4b), whenever Local setup or downloads changed | Download crash inside the frozen EXE and a Hugging Face repo that didn't exist (both v1.3.0) |
| F4 | Nothing is recorded before the Cloud/Local choice | auto (hotkey test) | Privacy promise in PRIVACY.md (1.3.7) |
| F5 | The installer shows the privacy page and installs without admin rights | manual | SignPath requirement (1.3.8) |

## Updating from the previous version

| ID | Check | How | Why it exists |
|---|---|---|---|
| U1 | One-click update from N-1 to N: the installed EXE's hash matches N and the app relaunches | manual (pre-release method in CLAUDE.md, "Testing an update end to end") | `taskkill /T` killed the installer mid-update (1.3.5) |
| U2 | Settings survive, including a `settings.json` saved with a BOM | manual | A BOM once silently reset every setting |

## Windows and UI

| ID | Check | How | Why it exists |
|---|---|---|---|
| W1 | Every Settings tab and the "How to say code" window fit their content | auto (layout test) | Save/Close bar squeezed to about 1px on every tab (v1.3.3) |

## Process lifecycle

| ID | Check | How | Why it exists |
|---|---|---|---|
| P1 | Tray Quit ends both EXE processes | manual | Quit hung in Tk cleanup and left both processes running (1.3.6) |
| P2 | Uninstalling stops the running app | manual | The app kept running after uninstall (v1.3.3) |
| P3 | Killing one of the two processes in Task Manager leaves no orphan | manual, **never verified** | The onefile parent can die while its child keeps running (seen in testing, Sept 2026) |

## Dictation

| ID | Check | How | Why it exists |
|---|---|---|---|
| D1 | Normal and developer hotkeys, chord upgrade, key repeat | auto (hotkey test) | OS key-repeat flooded the error cue and crashed the app (July 2026) |
| D2 | The real dictation pipeline with a faked transcript: code lines come out as code, with the right speech prompt | auto (pipeline test) | Cloud mode silently dropped the speech prompt until 2026-09-25 |
| D3 | Code-dictation scores at or above the recorded baseline, and ordinary sentences stay sentences | auto (all corpora, offline) | Classifier and rule regressions |
| D4 | Cloud: a silent key press sends nothing and types nothing | manual | Groq invented "Thank you." on silence (fixed 1.3.6) |
| D7 | Cloud fallback when Groq is busy: a forced-fallback request is answered `via: workers-ai-large-v3-turbo` (after any `cloud/worker.js` change) | manual: `tools/grammar_eval/fallback_bench.py fallback` | One shared free Groq key made several users at once see "Cloud is busy" (fixed 2026-09-27) |
| D5 | Grammar changes: guard rejections and meaning flags no worse than baseline | auto with `--grammar` | A dropped question and I/you swaps that passed the guards |
| D6 | One real dictation in each mode (Cloud, Local, code key) on the release build | manual | Everything above is simulated; this is the only check with a real microphone |

## Baselines

`scripts/release_qa_baseline.json` holds the minimum scores for D3 and
D5. When a change improves a score, the runner says so; raise the
baseline in the same commit so the gain can't silently slip back.
