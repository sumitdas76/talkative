# Changelog

All notable changes to Talkative (formerly Sumit Speak) are recorded here.

## [1.3.18] - 2026-10-27

### Changed

- The three Accuracy options are now always on and no longer in
  Settings: the text before the cursor helps spell names and terms in
  both Local and Cloud mode (in Cloud it is sent with the audio, see
  PRIVACY.md), and names you correct are offered as Auto Text
  suggestions.

### New

- "Start with Windows" in the tray menu (also still in Settings >
  General).
- Feedback can include an image (a screenshot, up to 5 MB): Settings >
  About > Feedback > Attach image.
- A new look, in three color schemes to choose from under Settings >
  General > Appearance: Forest (cream and deep green, the default), Coral
  (graphite and coral red) and Teal (slate and teal), each in light and
  dark. Settings has a colored header.
- While you dictate, the pill at the bottom of the screen is replaced by
  a single thin line, like a heart monitor's: flat while you're quiet, a
  wave that follows your voice while you speak, in your color scheme.
- You can see what happens to a dictation. After you let go, the line
  shows a sweeping light while your words are processed; if it takes
  more than 6 seconds, a note says Talkative is still working on it. If
  nothing will be typed, a message near the cursor says why, in plain
  words: no words were heard, the microphone couldn't be opened, or
  Talkative Cloud was busy, unreachable or too slow. This replaces the
  blocking error popup.
- Some problems are now shown while you're still speaking, not after:
  the line turns red and a message says what's wrong if your microphone
  is muted in Windows, sends nothing, or stops (unplugged), or if
  Talkative Cloud can't be reached.

### Fixed

- If no text box is selected when your words are ready, they go to the
  clipboard (press Ctrl+V) instead of being lost.
- A stalled Talkative Cloud request is given up on sooner (10 seconds
  plus a quarter of the recording's length, instead of 30 seconds), so
  the fallback starts earlier.
- Radio buttons in dark mode no longer look selected when they aren't.
- Dictating into a terminal (Claude Code, PowerShell, Command Prompt,
  bash) no longer starts with a small letter after extra spaces, and no
  longer drops the full stop when the terminal shows grey hint text: a
  prompt such as "❯" or "C:\>" now counts as the start of fresh input
  (1.3.17's mid-sentence fitting mistook it for a sentence carrying on).
- Switching microphones no longer needs a restart: a microphone you plug
  in, unplug or make the Windows default is used from the next
  dictation. Windows tells Talkative when this happens, so nothing runs
  in the background to watch for it. A recording that comes back
  completely silent also makes Talkative check its microphones again.
- The listening indicator no longer keeps redrawing after a dictation
  (1.3.17's pill did, forever): background CPU between dictations is
  about a third lower.

## [1.3.17] - 2026-10-25

### New

- Dictating into the middle of a sentence fits in: delete a wrong word,
  dictate the right one, and it's typed in lowercase without a full stop
  when the sentence carries on ("I want to meet on Tuesday next week",
  not "on Tuesday. next week"). Names and "I" keep their capitals. Works
  over selected text too.

### Fixed

- Carrying on a sentence no longer loses the first word: when you press
  the hotkey again within 4 seconds, the words you started saying as you
  pressed are kept ("move the meeting to Friday" came out as "to
  Friday"). To do this, the microphone now stays open 4 seconds after
  each dictation, keeping under a second of audio in memory; it's only
  used if you press again (see PRIVACY.md).

## [1.3.16] - 2026-10-25

### Removed

- The "Clean up grammar on this device instead of the server" option
  under Cloud.

### Fixed

- Cloud mode no longer cuts off the end of what you said when your
  microphone is quiet. Talkative trims the silence after you stop
  speaking, and with a quiet microphone it could mistake your last words
  for silence, so only part of the sentence got typed.
- Code dictation: "api dot github dot com" is typed as `api.github.com`,
  not `api .github.com`.
- Spoken corrections replace the word you meant: "Let's meet on Monday.
  Sorry, I mean Tuesday" types "Let's meet on Tuesday." They now also
  work with the Indian English accent, and "umm" / "uhh" count as fillers.

### New

- Names and terms come out spelled the way they already are in what
  you're writing: Talkative looks at the text just before the cursor
  when you start dictating. On by default in Local mode (it stays on
  your PC); in Cloud mode, turn it on in Settings > Dictation >
  Accuracy. In tests, names already on screen were spelled right about
  9 times in 10 instead of 6 in 10.
- When you correct a name Talkative typed ("Kuber Netties" to
  "Kubernetes"), it offers to remember the fix: Settings > Auto Text
  lists it with Add and Dismiss. Nothing is added unless you click Add.
- Cloud mode has a choice of accent under Settings > General > Processing:
  US English (as before) or Indian English, which uses Microsoft Azure's
  Indian English recognizer. In tests it got fewer words wrong on
  Indian-accented speech (13% instead of 19%). When it's busy, US English
  takes over for that dictation.
- Let go of the hotkey mid-sentence and press it again within a few
  seconds: Talkative carries on the same sentence instead of starting a
  new one with a capital letter.
- Lists spoken with letters ("a, never lie; b, always sleep; c, ...")
  are typed as bullet points, like "first, second, third" already were.
- "You know" used as a filler ("it was, you know, fine"; "You know,
  ...") is removed in Cleaned up mode. "Do you know", "as you know" and
  "you know what I mean" stay.
- "Send diagnostic data" (Settings > About, off by default): if you have
  a problem, turn it on so Sumit can see what was heard and typed, and
  hear the recording, for each dictation. Kept 30 days.
- Press Esc while dictating to cancel without typing anything.
- The first-run screen says in plain words how well Local mode suits
  your PC.

## [1.3.15] - 2026-10-15

### Fixed

- A hotkey with Alt in it (such as Ctrl+Alt) no longer opens the menu of
  the app you're typing in. If you let go of Ctrl a moment before Alt,
  Windows treated Alt as pressed on its own, and apps like Notepad
  highlighted their menu bar. The same fix applies to hotkeys with the
  Windows key, which could open the Start menu.

## [1.3.14] - 2026-10-13

### New

- Spoken numbers are typed as digits where that's what you'd write
  ("the meeting is at three thirty" types "3:30", "we need two lakh
  fifty thousand" types "we need 2.5 lakh"), and left as words where
  words read better.
- Spoken lists become bullet points: say "first..., second..., third..."
  or "point one..., point two..." and each item lands on its own line.
- Code dictation: say "new line" to start the next line of code.
- Right-click the tray icon to pick your microphone, or to switch the
  headphones or speakers Windows plays sound through.

### Fixed

- Spoken corrections only replace what you corrected. "Let's meet on
  Monday, sorry, I mean Tuesday" now types "Let's meet on Tuesday."
  instead of just "Tuesday."
- Talkative keeps working after the PC sleeps, locks, or you press
  Ctrl+Alt+Del. Before, the hotkey could stop responding until a restart,
  or keep listening after you let go.
- Your clipboard is left exactly as it was after a dictation, including
  a copied picture or file, and dictations no longer fill up your
  clipboard history (Win+V).
- Local mode no longer rewords what you said. It fixes grammar,
  punctuation and capitals only, so it can't turn "move" into "stay".
- Cleanup no longer swaps a word for its opposite ("prepone" into
  "postpone") or drops a "yes", "please", "thanks" or "I think".
- "point one" is typed as "point 1", not "0.1".
- Old example entries in the personal dictionary (such as "AI" becoming
  "artificial intelligence") are removed if you never changed them.
- Your settings can no longer be lost if the PC crashes or loses power
  while they're being saved.
- In code dictation, "npm and node need an update" is typed as a
  sentence, not as a command.
- The Models tab shows when the grammar model is still downloading in
  the background, instead of offering to download it again.

### Changed

- Cloud dictation is faster, about 0.2 seconds per dictation and more
  on slower connections, by reusing the connection to the server.
- On slower PCs, Local cleanup is skipped less often: Talkative now
  estimates how long cleanup will take much more accurately.
- Settings: clearer layout. Cloud's on-device grammar option sits under
  Cloud, the server address line is gone, the Hotkeys tab says "Regular
  dictation" and "Code dictation", the "How to say code" guide is now an
  easy-to-read table, and hint text is readable in light and dark mode.
- To keep the free Cloud service available for everyone, each network
  address can make up to 600 Cloud requests a day (about 300 dictations).

## [1.3.13] - 2026-10-04

### Fixed

- Fixed a crash that could close Talkative when you pressed the hotkey
  again right after a dictation. It came from the start and stop sounds
  being played while the microphone was starting or stopping.
- When Cloud is busy or your internet drops, your dictation is no longer
  lost. If the Local voice model is downloaded, that dictation is
  transcribed on your PC instead; otherwise Talkative tries Cloud again
  a few seconds later.
- The cleanup step no longer finishes a sentence you didn't finish. If
  you let go of the key mid-sentence ("...and also the"), it used to add
  words you never said ("...as well as the file?"); now your words are
  kept as spoken. It also can't drop a "not" or "never" anymore.
- Talkative now cleans up after itself in your Temp folder. Each time it
  was closed by force (a crash, or End task in Task Manager), it left a
  250 MB copy of itself behind; those are now removed when it next starts.

### Changed

- No more beeps. The listening animation shows when Talkative is ready
  for your words, so the start, stop and "done" sounds are gone, along
  with the sound and output device options in Settings.
- The setup screen now says how much memory Local mode needs: about
  2.3 GB while running, best with 16 GB of RAM, works on 8 GB.

## [1.3.12] - 2026-10-04

Thank you to Aman Sah for the idea behind tap to talk (new in 1.3.11):
tap your key once to start and again to stop, instead of holding it
down. Turn it on in Settings, under Hotkeys.

### Fixed

- After choosing Local, you can now switch back to Cloud. Before, it
  could look as if the switch didn't work, and the setup window couldn't
  be left while Local was downloading. Now you can pick Online at any
  point during that download and start with Cloud right away.
- If you tried Local once and went back to Cloud, Talkative no longer
  loads the Local files again in the background (they take up a lot of
  memory), and removing them no longer stops dictation.
- Downloading Optimize Narration now takes effect straight away, without
  restarting Talkative.
- When you dictate twice in quick succession, whatever you had copied is
  kept, and your words are typed in the order you said them.
- If your microphone disconnects in the middle of a dictation (for
  example a Bluetooth headset), Talkative keeps working instead of
  needing a restart.
- Settings no longer lets you pick a hotkey that would go off while you
  type (such as a letter, Shift or Space), or the same key for normal
  and code dictation.

## [1.3.11] - 2026-10-04

### Added

- Tap to talk (thanks to Aman Sah for the idea). Instead of holding your
  key down the whole time you speak, you can now tap it once to start and
  tap it again when you're done. Turn it on in Settings, under Hotkeys,
  "How the hotkeys work". Holding
  the key still works too. If you forget the second tap, Talkative stops
  listening by itself after 5 minutes and types what you said.

### Changed

- New installs start with an empty personal dictionary. Before, they came
  with a few of the developer's own words (for example, "AI" was typed out
  as "artificial intelligence"). If you already use Talkative, your
  dictionary is not changed.
- The publisher is now shown as Sumit Das.
- If something goes wrong, Talkative now writes a short note about the
  problem to a file on your PC, so it can be found and fixed. It never
  contains anything you said, and it is never sent anywhere.

### Fixed

- The Talkative icon could disappear from the corner of the taskbar while
  the app kept working. It now stays put, and comes back on its own if
  Windows loses it.
- With a key combination that includes the Windows key (for example Ctrl +
  Windows), letting go of the keys opened the Start menu. It no longer
  does.
- With a key combination that includes Alt, some windows could swallow
  your words instead of typing them. Fixed.

## [1.3.10] - 2026-09-27

### Changed

- Cloud mode no longer says "Cloud is busy" when many people dictate at
  once: if the main speech service is at its limit, a second one with the
  same accuracy takes over (a second or so slower). This is on our server,
  so it already works in every version.

### Fixed

- Code dictation: "docker" misheard as "talker" is understood; "let c
  equal to 5 plus 2" is typed as code again (it had become a sentence);
  a negative number after step or return is written -2, not - 2.
- Sentence cleanup keeps numbers exactly as you said them. Before, a
  dictation like "the meeting moved to three thirty" could lose its
  cleanup entirely (Cloud wrote 3:30, the on-device model even wrote
  3:00 PM, and the safety check then threw the result away).

## [1.3.9] - 2026-09-27

### Changed

- Local mode adapts to the PC it runs on: it uses all physical CPU cores,
  uses an NVIDIA graphics card when one is usable (falling back to the
  processor otherwise), and on slower PCs skips sentence cleanup for a
  dictation it predicts would take more than 10 seconds instead of making
  you wait.
- Sentence cleanup is stricter about never dropping a sentence you said.
- Choosing Local on first run now gets you dictating after the 0.5 GB
  voice download instead of the full 2 GB: Optimize Narration finishes
  downloading in the background while you work (and resumes if Talkative
  is closed before it's done).
- Local mode's sentence cleanup is about 40% faster: a short dictation's
  cleanup went from about 3 seconds to under 2 on a typical 6-core PC.
- Code dictation understands much more .NET, JavaScript/TypeScript and
  full-stack speech: dotnet and EF Core commands (package names like
  Microsoft.EntityFrameworkCore, migration names like InitialCreate),
  C# ({ get; set; }, Console.WriteLine, [HttpGet], nameof), React hooks
  (useState), npm/yarn/pnpm/npx, docker, az and more -- and the different
  ways people say symbols: "left paren", "open curly", "semi colon",
  "hyphen u" or "minus u" for -u, "bang" for !, "double question mark"
  for ??, "spread" for ..., "capital x" for X.
- Sentences that merely start like code ("let me know when...", "export
  the report...", "git is complaining about...") now stay sentences when
  said with the code key.

### Fixed

- Versions 1.3.6 to 1.3.8 could fail to start on a new install or after
  updating ("Unhandled exception in script"). If that happened to you,
  download and run this version's installer; your settings are kept.
- On a new install, the "running via Cloud" notice no longer opens on top
  of the first-run Cloud or Local choice.

## [1.3.8] - 2026-09-27

### Changed

- The installer now shows Talkative's privacy policy before installing,
  so you can see exactly what is sent over the internet (and how to
  keep everything on your PC) before you install.

## [1.3.7] - 2026-09-27

### Changed

- On first start, dictation waits until you've picked Cloud or Local in
  the setup window, so nothing is sent anywhere before you choose.
- Added a privacy policy (PRIVACY.md) listing everything the app sends
  over the internet.

### Fixed

- The output device chosen in Settings is now remembered after a
  restart.
- Some tray messages showed garbled characters ("â€”") instead of a
  dash.

## [1.3.6] - 2026-09-26

### Added

- Code dictation. A second key (Right Ctrl + Right Shift by default,
  changeable in Settings -> Hotkeys) turns what you say into text that
  runs: "select star from users where id equals five" types
  SELECT * FROM users WHERE id = 5, and "git commit dash m quote fix
  login bug quote" types git commit -m "fix login bug". Works for SQL,
  terminal and PowerShell commands, and code. Ordinary sentences said
  with this key still come out as normal sentences. "How to say code" on
  the Hotkeys tab lists the words to use.

### Changed

- The Hotkeys tab is now two simple sections, Dictation and Code
  dictation, each with its own key.

### Fixed

- In Cloud mode, pressing the key without saying anything could type
  words you never said, most often "Thank you." Silent presses are now
  ignored and nothing is sent.
- Cloud mode now gets the same punctuation and personal-dictionary hints
  that Local mode always had, so your dictionary words are recognised
  more reliably.
- Quitting from the tray icon could leave Talkative running in the
  background (visible in Task Manager) if Settings had been opened.
  Quit now always closes it completely.

## [1.3.5] - 2026-09-25

### Added

- One-click updates. Once a day at startup Talkative checks for a newer
  version and, if there is one, asks whether to update. Clicking Update
  downloads it in the background (dictation keeps working), checks the
  download is genuine, then closes Talkative, installs the new version,
  and reopens it by itself -- your settings are kept. Nothing is ever
  installed without that click, and "Not now" asks again in a week.
  Versions before this one can't do this, so this is the last update
  you'll need to install by hand.

### Fixed

- Short sentences that started the same way could be mistaken for you
  repeating yourself, and the earlier one was silently deleted -- for
  example "I lost my job. I lost my deposits." came out as only "I lost
  my deposits." Lists of sentences like this are now kept in full, while
  genuine corrections ("Let's meet Monday. Let's meet Tuesday instead.")
  are still tidied up as before.

## [1.3.4] - 2026-09-20

### Changed

- The Cloud endpoint field on the General tab is now shown for reference
  only, not editable. It previously let anyone type in it, and a mistyped
  value there silently broke Cloud dictation with a confusing technical
  error on every attempt, with no hint of how to fix it. The value is
  still visible; it just can't be changed from here anymore.

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
