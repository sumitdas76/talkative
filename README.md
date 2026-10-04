# Talkative

Hold-to-talk dictation for Windows, ready the moment you install it.

**Free · Open source · Windows 10/11 · Cloud or fully offline**

![Hold Right Ctrl, speak, let go: your words are typed where your cursor is](assets/demo.gif)

[![Download for Windows](https://img.shields.io/badge/Download_for_Windows-TalkativeSetup.exe-2ea44f?style=for-the-badge&logo=windows&logoColor=white)](https://github.com/sumitdas76/talkative/releases/latest/download/TalkativeSetup.exe)

Free, no account. Windows 10 or 11. The installer isn't code-signed yet, so
Windows may say "Windows protected your PC": click **More info → Run
anyway**. [What's new](https://github.com/sumitdas76/talkative/releases/latest)

Hold a key (or two, held together — configurable in Settings; default:
Right Ctrl), speak, release — your words are typed into whatever
application has focus. Slips of the tongue, filler words, and spoken
corrections are cleaned up on the way.

## Privacy

By default, Talkative processes dictation via Cloud — your audio goes to
a remote server for transcription and cleanup, then is discarded, not
stored. Prefer fully offline? Switch to Local in Settings → General any
time and download the voice and grammar models (~2 GB) — after that,
your audio and text never leave your PC.

Dictation history, if you turn it on in the Dictation tab, is always
stored only on your device, regardless of mode. In either mode the app
checks GitHub once a day for updates (nothing about you is sent), and
the Feedback box in Settings → About sends a message only when you
click Send.

Full details — every network request, what's sent, and to whom — are
in the [privacy policy](PRIVACY.md).

## Download

[Download TalkativeSetup.exe](https://github.com/sumitdas76/talkative/releases/latest/download/TalkativeSetup.exe)
(always the latest version), or see the
[latest release](https://github.com/sumitdas76/talkative/releases/latest) for
what's new and the SHA-256 checksum.

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

## Code signing policy

Free code signing provided by [SignPath.io](https://about.signpath.io),
certificate by [SignPath Foundation](https://signpath.org).

- Committers and reviewers: [@sumitdas76](https://github.com/sumitdas76)
- Approvers: [@sumitdas76](https://github.com/sumitdas76)

Only binaries built by this repository's
[GitHub Actions workflow](.github/workflows/build.yml) from the public
source are signed. Every release is reviewed and published by hand.

Privacy policy: see [PRIVACY.md](PRIVACY.md). Talkative sends audio and
text to a cloud service only in Cloud mode, which the user picks (or
switches off) at first run and in Settings.

## Source

This repo holds both the source (`talkative/`) and the packaged
releases. See `CHANGELOG.md` for what's changed release to release.
