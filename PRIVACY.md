Talkative Privacy Policy
========================

Last updated: 2026-09-27

Talkative is a free, open-source Windows dictation app. This page lists
every way it talks to the internet, what is sent, and how to turn it
off. The source code in this repository is the reference: nothing is
sent that isn't described here.

Talkative has no accounts, no ads, no analytics and no tracking.


Your choice: Cloud or Local
---------------------------

The first time Talkative starts, it asks whether to process dictation
in the Cloud or Locally on your PC. Dictation doesn't start until
you've answered, so nothing is sent before you choose. You can change
this at any time in Settings > General > Processing.

### Cloud mode

Each time you dictate, Talkative sends:

- The audio recording of that dictation (only while you hold the
  hotkey; recordings with no speech in them are not sent at all), and a
  short hint text built from your personal dictionary words, so names
  and terms you added are recognized.
- The transcribed text, for grammar and punctuation cleanup.
- An anonymous install ID: a random number created on your PC the first
  time Talkative runs. It isn't tied to your name, email, or device,
  and is used only to enforce a fair daily usage limit per install.

These go to Talkative's server, a Cloudflare Worker run by the
Talkative maintainer (talkative-cloud.sumitdas76.workers.dev), which
forwards the audio and text to:

- Groq, for speech-to-text and grammar cleanup.
  Privacy policy: https://groq.com/privacy-policy/
- Cloudflare Workers AI, as a backup for grammar cleanup when Groq is
  unavailable. Privacy policy: https://www.cloudflare.com/privacypolicy/

Talkative's server does not store or log your audio or text. It keeps
one thing: a count of how many requests each install ID made today,
which resets every day. The services above process your data under
their own policies, linked above.

### Local mode

Speech recognition and cleanup run entirely on your PC. After the
one-time download of the voice and grammar models (from Hugging Face),
your audio and text never leave your computer.


Things that happen in both modes
--------------------------------

- Update checks, once a day. Talkative downloads a small public file
  from GitHub to see whether a newer app version or model update
  exists. Nothing about you or your dictation is sent; like any web
  request, GitHub sees your IP address. Updates are only downloaded
  when you click Update.
- Feedback replies, once a day. Talkative downloads a public file from
  GitHub that holds replies to feedback messages, and checks it for
  your install ID. The check happens on your PC, and nothing is sent
  apart from the plain request itself.
- Feedback you choose to send. If you type a message in
  Settings > About and click Send, that message and your anonymous
  install ID are emailed to the maintainer through FormSubmit
  (https://formsubmit.co), a form-to-email service. Nothing is sent
  unless you click Send.


What stays on your PC
---------------------

- Your settings and personal dictionary.
- Dictation history, only if you turn it on in the Dictation tab. It is
  never uploaded, in either mode.
- A debug log, off by default, which holds dictated text if turned on.

All of these are in %LOCALAPPDATA%\Talkative. The uninstaller offers to
delete that folder.


Contact
-------

Questions: open an issue at https://github.com/sumitdas76/talkative/issues,
or use the Feedback box in Settings > About.
