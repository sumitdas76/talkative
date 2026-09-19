# Talkative

Hold-to-talk dictation for Windows, ready the moment you install it.

Hold a key (or two, held together — configurable in Settings; default:
Right Ctrl), speak, release — your words are typed into whatever
application has focus. Slips of the tongue, filler words, and spoken
corrections are cleaned up on the way.

## Privacy

By default, Talkative processes dictation via Cloud — your audio goes to
a remote server for transcription and cleanup, then is discarded, not
stored. Prefer fully offline? Switch to Local in Settings → General any
time and download the voice and grammar models (~2 GB) — after that,
nothing ever leaves your PC.

Dictation history, if you turn it on in the Dictation tab, is always
stored only on your device, regardless of mode. The one other exception
is the Feedback box in Settings → About: if you type a message there and
click Send, that message (and only that message) is sent — never
automatically, only when you choose to.

## Download

Get **TalkativeSetup.exe** from the
[latest release](https://github.com/sumitdas76/talkative/releases/latest).

The installer is not code-signed yet, so Windows SmartScreen may warn you:
click **More info → Run anyway**. No administrator rights are needed.

## Requirements

- Windows 10 or 11, 64-bit
- A microphone
- An internet connection (Cloud mode, the default). Switching to Local
  needs about 2 GB of free disk space and 4 GB of RAM instead.

Talkative works right after installing — nothing to download first. If
you switch to Local mode, that download takes a couple of minutes; after
that it works fully offline.

## Updates

In Local mode, the app checks once a day for improved models and asks
before downloading anything. You can undo any update from Settings →
Models.

## Source

This repo holds both the source (`talkative/`) and the packaged
releases. See `CLAUDE.md` for architecture notes and `CHANGELOG.md` for
what's changed release to release.
