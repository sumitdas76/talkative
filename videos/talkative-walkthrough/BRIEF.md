---
workflow: general-video
flow: automation
storyboard: yes
message: "Show people how easy Talkative is to install and configure"
destination: LinkedIn
aspect: "16:9"
language: en
length: "~3.5min"
---

## Intent

A cinematic walkthrough of Talkative (Windows hold-to-talk dictation app):
download, install, first-run onboarding, a live dictation demo, and a tour
of all 8 Settings tabs (General, Auto Text, Dictation, Hotkeys, Audio,
Output, Models, About).

## Notes

No desktop-control / computer-use tooling is available in this environment
(browser automation only, verified twice). By explicit user direction
("you create the video end to end"), all native-UI scenes (installer
wizard, onboarding screen, live dictation demo, all 8 Settings tabs) are
built as faithful HTML/CSS recreations of the real Tkinter UI (real copy,
real control types/order, real theme colors pulled from
talkative/settings_window.py's `_apply_theme`), not literal screen
captures. The one scene built from a real capture is the GitHub release
page (scene 2), screenshotted live via Chrome automation.

Voiceover: AI-generated, local Kokoro TTS (`af_heart` voice) — no HeyGen/
ElevenLabs credential available in this environment; not a judgment call
to skip asking, this is a one-shot automated run with no path to ask.

Music bed: skipped for this rough cut — local MusicGen dependencies
(torch) were judged too large/slow to install for a rough-cut pass. Noted
as an open item for the final pass.
