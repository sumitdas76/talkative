# Talkative

Hold-to-talk dictation for Windows that runs **entirely on your PC**.

Hold a key (or two, held together — configurable in Settings; default:
Right Ctrl), speak, release — your words are typed into whatever
application has focus. Slips of the tongue, filler words, and spoken
corrections are cleaned up on the way.

## Privacy

Dictation is fully offline — your voice never leaves your PC. Audio is
transcribed locally and never saved. At startup, Talkative checks for
improved models; nothing about you — no audio, no text — is ever sent.

The one exception: the Feedback box in Settings → About. If you type a
message there and click Send, that message (and only that message) is
sent — never automatically, only when you choose to.

## Download

Get **TalkativeSetup.exe** from the
[latest release](https://github.com/sumitdas76/sumit-speak/releases/latest).

The installer is not code-signed yet, so Windows SmartScreen may warn you:
click **More info → Run anyway**. No administrator rights are needed.

## Requirements

- Windows 10 or 11, 64-bit
- A microphone
- About 1 GB of free disk space (the local speech model plus the
  built-in writing-cleanup pass), 4 GB of RAM

On first run the app downloads its speech model and is ready in a
couple of minutes. Everything after that works offline.

## Updates

The app checks once a day for improved models and asks before downloading
anything. You can undo any update from Settings → Models.

## Source

This repo holds both the source (`sumit_speak/`) and the packaged
releases. See `CLAUDE.md` for architecture notes and `CHANGELOG.md` for
what's changed release to release.
