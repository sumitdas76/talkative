# Changelog

All notable changes to Talkative (formerly Sumit Speak) are recorded here.

## [1.3.3] - 2026-09-20

### Fixed

- The Settings window's Save and Close buttons could shrink down to
  basically nothing and disappear when switching to certain tabs — the
  window was a fixed size that no longer had enough room once the Cloud
  vs. Local option was added to the General tab in an earlier release.
  The window now sizes itself to fit its actual content.
- Uninstalling did not stop the app if it was still running, so it could
  keep running in the background — and stay visible in Task Manager —
  even after being uninstalled. The installer now closes the app before
  installing or removing it.

## [1.3.2] - 2026-09-20

This release doesn't add anything new — it's entirely about making
dictation more trustworthy. It came out of a deep stress-testing pass:
made-up test recordings covering fast rambling speech, multiple
back-to-back corrections, technical text like file paths and version
numbers, and even different accents (Indian English and New York English),
specifically hunting for cases where the app could quietly get something
wrong. It found several, all now fixed.

### Fixed

- Removing filler words like "um" could accidentally delete the period at
  the end of a sentence, running two separate sentences together into one
  confusing block of text.
- Filler-word removal could mangle a real word like "uh-huh" into broken
  text ("-huh").
- The "remove duplicate sentences" cleanup could delete an entire sentence
  just because it was worded similarly to a nearby one, even when the two
  sentences actually said different things (for example, one about a
  number of people and another about a number of chairs).
- Dictating a file path, version number, or web address could get
  scrambled — and partly deleted — if a spoken correction ("scratch that,"
  "no wait," and similar) showed up anywhere later in the same dictation.
  The periods inside that kind of text were being mistaken for the ends of
  sentences.
- A personal dictionary word could wrongly expand itself in the middle of
  a dictated file path or web address and break it — for example, a
  folder named after you turning into your full name, which isn't a real
  folder.
- In rare cases where speech-to-text lost track of punctuation for a long
  stretch (something the cloud engine occasionally does), a single spoken
  correction could wipe out several unrelated sentences that had nothing
  to do with the correction. This is now caught and left alone instead of
  guessing wrong and deleting real content.
- The cloud grammar cleanup had a known issue, from the previous release,
  where it would sometimes reword already-clear sentences for no reason,
  occasionally flattening a colorful turn of phrase into something
  blander. The fix for this had been written but never actually went
  live — it's deployed now.

## [1.3.1] - 2026-09-19

### Fixed

- Choosing Local on the first-run onboarding screen would crash the
  download with "'NoneType' object has no attribute 'write'" -- a
  PyInstaller windowed-build quirk (no console, so `sys.stdout`/`stderr`
  are `None`) that the download progress library wrote to unconditionally.
  Downloading local models from Settings had the same underlying issue.
- The onboarding screen's Continue button could be pushed off-screen
  (window sized too small for its content) with no visible error.
- The onboarding download now shows a real percentage/MB progress bar
  instead of a generic animated one.

## [1.3.0] - 2026-09-19

### Added

- Cloud processing (Settings → General → Processing): speech-to-text and
  grammar cleanup now run by default on a remote Cloudflare Worker instead
  of on-device, so a fresh install skips the model download and its
  ~1-2GB RAM. Local remains fully supported -- switch back any time in
  Settings, with a "Download local models" button to fetch the
  faster-whisper and grammar models on demand -- and stays fully
  offline/no-network when selected. Cloud requests are capped by a
  per-install daily quota; a one-time notice on first Cloud use explains
  the mode and points at the Local download.
- Settings → General → Processing: a new checkbox lets Cloud transcription
  pair with the local grammar engine instead of Cloud's own grammar model,
  for a Cloud-STT + local-grammar mix (needs the local grammar model
  downloaded; falls back to Cloud grammar automatically if it isn't).
- A one-time onboarding screen on first launch -- shown to existing
  installs updating to this version too, not just fresh ones -- lets you
  choose Cloud or Local up front, with plain-language RAM/disk numbers for
  each. Picking Local downloads both models right there, so you land in a
  fully working offline setup instead of needing a second trip to
  Settings for the grammar engine.

### Changed

- Cloud transcription now runs on Groq's hosted `whisper-large-v3-turbo`
  instead of Cloudflare's smaller base Whisper model -- noticeably better
  punctuation and accuracy on live testing.
- Default processing mode is now Cloud, not Local -- a deliberate product
  decision, not just a new option (see CLAUDE.md's "Cloud-by-default
  processing" section for the mechanics and cost ceiling).
- Finished the Sumit Speak → Talkative rename that [1.2.0] deliberately
  left incomplete: the Python package (`sumit_speak/` → `talkative/`), the
  internal app class, and both GitHub repos (`sumit-speak` → `talkative`,
  `sumit-speak-updates` → `talkative-updates`) now all say Talkative.
  Update manifest and feedback-reply URLs updated to match; the
  FormSubmit feedback endpoint's Referer header was deliberately left
  pointing at the old repo URL, which GitHub still redirects, rather than
  risk re-triggering FormSubmit's account activation.

### Fixed

- Cloud transcription would reliably tack on a hallucinated "Thank you."
  when a dictation ended in silence (a known Whisper-family artifact from
  training on captioned video). Fixed by trimming trailing near-silence
  from the audio client-side before it's sent to Cloud at all -- the same
  root-cause fix Local mode already had via faster-whisper's own
  `vad_filter`.

## [1.2.1] - 2026-08-23

### Fixed

- The "listening" pill (the floating indicator that appears while
  holding the hotkey) followed the mouse cursor around the screen
  instead of staying put. It's now fixed at the bottom-center of the
  screen.

## [1.2.0] - 2026-08-23

### Changed

- Renamed the app from Sumit Speak to Talkative: display name, tray
  tooltip, window titles, the EXE (now `Talkative.exe`), and the
  install/data folders. A one-time, automatic migration moves existing
  settings, history, and downloaded models from the old
  `%LOCALAPPDATA%\SumitSpeak` folder to the new
  `%LOCALAPPDATA%\Talkative` folder on first launch after updating — no
  re-download needed. Feedback channel, update manifest, and the
  GitHub-hosted repos are unchanged for now.
- Dictation tab reorganized into labeled sections (Dictation style /
  History) instead of a flat list.

### Added

- Opt-in, local-only dictation history (Settings → Dictation → History):
  keeps a log of what you've dictated, viewable and clearable from
  Settings. Off by default.

### Fixed

- The "Cleaned up" grammar pass could fabricate an answer to a question
  instead of just cleaning it up (e.g. turning "will there be any
  difference?" into an invented "there will be no difference."). Added
  a guard rejecting any rewrite that drops every "?" from the input.
- The grammar pass could turn the speaker's own first-person statement
  into one about the listener (e.g. "If I create videos... will there
  be a difference?" became "If you create videos... there will be a
  difference"). Added a guard blocking any invented "you" the input
  never had.
- A subtler version of the same bug survived the first guard: a
  sentence that already had one legitimate "you" could still get a
  *second*, invented "you" planted on an unrelated clause. The guard
  now compares "you" counts rather than just presence.

## [1.1.3] - 2026-07-22

### Fixed

- The About tab showed "Version 1.1.0" regardless of the actual
  installed version — `sumit_speak/__init__.py`'s `__version__`
  constant is separate from the installer's version number and hadn't
  been updated across the 1.1.1 or 1.1.2 releases.

## [1.1.2] - 2026-07-22

### Fixed

- Dictating with no window actually focused (e.g. desktop showing, all
  windows minimized) silently went nowhere instead of showing an error.
  Windows UI Automation reports the last active window's own frame as
  "focused" in that case rather than reporting nothing, and that frame
  was incorrectly being treated as an editable text field.

### Changed

- The no-target error is now a simpler on-screen box only (no spoken
  voice cue), shows for 1.5 seconds instead of 3.5, and lost its "OK"
  button — the whole box (or clicking elsewhere, or Escape) still
  dismisses it early.

## [1.1.1] - 2026-07-22

### Fixed

- A crash (`STATUS_HEAP_CORRUPTION`, confirmed via Windows crash dump)
  that could happen when holding the dictate hotkey over a window with
  nothing editable focused. Windows re-fires the key-press event at the
  OS key-repeat rate for as long as a key is held; since dictation never
  started in that case, every repeat replayed the no-target handler,
  including its spoken voice cue — flooding concurrent COM calls that
  aren't safe to run at once and corrupting the heap. Only the first
  physical key-down of the hotkey is handled now; the voice cue's COM
  calls are also serialized as a second line of defense.

### Changed

- The installer's "Launch Sumit Speak now" option moved from an opt-in
  task checkbox to the setup wizard's standard finish-page checkbox
  (checked by default).

## [1.1.0] - 2026-07-21

### Added

- Custom app icon (a microphone on a steel-blue squircle), replacing
  PyInstaller's default icon everywhere: the EXE, the installer, the
  system tray (all three states), and every app window's title bar.
- Hotkey chords: hold one key, or two keys together, to dictate — not
  just a single key. Settings' hotkey capture UI supports both.
- Output-device dropdown on the Audio tab, alongside the microphone one.
  Tones and the spoken no-focus cue now play through the selected device
  instead of always going to the system default.
- Spoken cue and an on-screen error toast when nothing editable is
  focused, replacing the old blocking popup — hands stay on the keyboard,
  and the message can't be missed the way a suppressed notification can.
- In-app feedback channel (Settings → About → Feedback): send a message
  straight to Sumit; a reply, when there is one, shows up back in the app.
  This is the app's first and only outbound network path, and only ever
  runs when you click Send.
- Recognition of spoken symbol names ("underscore", "dot", "at sign",
  "hyphen", "forward slash", "backslash") — dictating "settings
  underscore window dot py" now types `settings_window.py` instead of the
  words themselves. Fixes filenames, URLs, and emails read aloud.
- A "Writing cleanup" style pass ("Optimize Narration" on the Models tab)
  now rewords genuinely garbled or unclear sentences, not just grammar
  and punctuation — with new guards to catch the model changing what was
  actually said (see Fixed).
- Cosmetic version number shown on the model tile, so it's visible when a
  background update actually changed something.
- Custom-drawn checkbox checkmark, replacing the Windows theme's default
  indicator glyph.

### Changed

- Speech recognition now uses the Fast model only. The Accurate
  (large-v3-turbo) tier was removed as a feature — not just its
  downloaded files — in favor of leaning on the writing-cleanup pass for
  quality. The Models tab's layout adapts to however many tiers exist.
- The "in use" badge/border on the model tile was removed — meaningless
  clutter with only one voice model to distinguish it from.
- Various wording cleanups: clearer model latency text (mentions longer
  sentences taking more time), em dashes replaced with hyphens in the
  Models and Hotkeys tabs, the "press-to-toggle mode planned" line
  removed from the Hotkeys tab.

### Fixed

- A recurring crash (confirmed via Windows crash dumps across two days,
  identical `tcl86t.dll` fault each time) caused by multiple independent
  Tk interpreters running on separate threads at once. Every floating
  window and dialog (the listening pill, the error toast, Settings, the
  first-run box, the update dialog) now shares a single interpreter.
- Hover states in Settings that painted table rows white regardless of
  theme, plus several other unmapped light/dark theme states: the
  combobox dropdown popup, treeview row selection, the progress bar,
  entry-field focus outlines, and disabled-state colors.
- A pronoun-swap failure in the writing-cleanup pass ("I want you to take
  care of this" → "I will take care of this," silently flipping who's
  responsible for something) — found via live testing against the actual
  deployed model, not just designed on paper. A targeted guard now
  rejects that specific failure mode and falls back to the unmodified
  text.
- `model_manager.MODELS` no longer assuming two speech tiers always
  exist, which would have crashed the delete flow the moment the only
  remaining model was deleted.

### Removed

- The Accurate speech model tier, and two stale entries from the
  built-in personal dictionary example set.
