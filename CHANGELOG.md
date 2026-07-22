# Changelog

All notable changes to Sumit Speak are recorded here.

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
