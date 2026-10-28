Talkative Privacy Policy
========================

Last updated: 2026-10-25

Talkative is a free, open-source Windows dictation app. This page lists
every way it talks to the internet, what is sent, and how to turn it
off. The source code in this repository is the reference: nothing is
sent that isn't described here.

Talkative has no accounts, no ads, no analytics and no tracking. The
only diagnostics are the ones you can choose to send (below).


Your choice: Cloud or Local
---------------------------

The first time Talkative starts, it asks whether to process dictation
in the Cloud or Locally on your PC. Dictation doesn't start until
you've answered, so nothing is sent before you choose. You can change
this at any time in Settings > General > Processing.

### Cloud mode

Each time you dictate, Talkative sends:

- The audio recording of that dictation (while you hold the hotkey;
  recordings with no speech in them are not sent at all), and a
  short hint text built from your personal dictionary words, so names
  and terms you added are recognized.
- Up to 400 characters of the text just before the cursor in the box
  you're dictating into, sent with the audio so names and terms already
  there are spelled the same way, then discarded. Password boxes are
  never read.
- The transcribed text, for grammar and punctuation cleanup.
- An anonymous install ID: a random number created on your PC the first
  time Talkative runs. It isn't tied to your name, email, or device,
  and is used only to enforce a fair daily usage limit per install.

These go to Talkative's server, a Cloudflare Worker run by the
Talkative maintainer (talkative-cloud.sumitdas76.workers.dev), which
forwards the audio and text to:

- Groq, for speech-to-text and grammar cleanup.
  Privacy policy: https://groq.com/privacy-policy/
- Microsoft Azure Speech (Central India), for speech-to-text when you
  choose "Indian English" under Cloud in Settings. Microsoft says audio
  for this kind of recognition is processed in memory and not stored.
  Privacy: https://learn.microsoft.com/azure/ai-foundry/responsible-ai/speech-service/speech-to-text/data-privacy-security
- Cloudflare Workers AI, as a backup for speech-to-text and grammar
  cleanup when Groq is unavailable.
  Privacy policy: https://www.cloudflare.com/privacypolicy/

Talkative's server does not store or log your audio or text, unless you
turn on diagnostic data (see "Diagnostic data" below). It keeps
two counts, both reset every day: how many requests each install ID
made today, and how many came from each network address today. The
address itself is not stored, only a one-way scrambled form of it
(a hash) that the count is filed under. The services above process your data under
their own policies, linked above.

### Local mode

Speech recognition and cleanup run entirely on your PC. After the
one-time download of the voice and grammar models (from Hugging Face),
your audio and text never leave your computer. To spell names and terms
correctly, Talkative reads up to 400 characters of the text before the
cursor when you start dictating (never from password boxes); in Local
mode that text stays on your PC.


Things that happen in both modes
--------------------------------

- To fit a dictation into the middle of a sentence (no capital letter
  or full stop where the sentence carries on), Talkative reads a few
  words on either side of the cursor just before typing. This is done
  on your PC in both modes and is never sent anywhere or saved. Password
  boxes are never read.
- The microphone stays open for 4 seconds after each dictation, so
  that if you press the hotkey again to carry on, a word you started
  saying as you pressed isn't lost. During those seconds Talkative keeps
  only the last three-quarters of a second in memory, replacing it
  continuously. It is never saved, and it is only used (and in Cloud
  mode sent) if you press the hotkey again within the 4 seconds; then it
  becomes the start of that dictation. Otherwise it is discarded when
  the microphone closes. Windows' microphone icon shows this.

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
  Settings > About and click Send, that message, the image you attached
  to it (if any), and your anonymous install ID are emailed to the
  maintainer through FormSubmit
  (https://formsubmit.co), a form-to-email service. Nothing is sent
  unless you click Send.


Diagnostic data (off unless you turn it on)
-------------------------------------------

In Settings > About you can choose "Send diagnostic data to help fix
problems". It is off by default, and turning it on asks you to confirm.
While it's on, every dictation sends Talkative's server, in either mode:

- the recording of that dictation (up to 55 seconds),
- what speech-to-text heard, the text after each cleanup step, and the
  text that was typed,
- whether it was pasted, and if not, why, plus the kind of box it went
  into (for example "a text box in Windows Terminal" -- the type of
  control, never its contents),
- your Talkative version, Windows version, the settings that affect the
  result (Cloud or Local, cleanup style, speech service), and your
  anonymous install ID (Settings > About shows its first 8 characters
  as your diagnostic ID).

The text before the cursor is never included, only how long it was.
Reports are stored on Talkative's server (Cloudflare) for 30 days, then
deleted, and only the maintainer can read them, to find and fix
problems. They are never sold or shared. Turn it off in the same place;
reports already sent are deleted when their 30 days are up, or sooner if
you ask through the Feedback box.


What stays on your PC
---------------------

- Your settings and personal dictionary.
- Suggested Auto Text entries: when you correct a name or term
  Talkative typed, it reads the box again a little later to notice the
  change, and keeps only the word pair (for example "Kuber Netties" ->
  "Kubernetes") to offer in Settings > Auto Text. The text of the box is
  not kept. Turn this off in Settings > Dictation > Accuracy.
- Dictation history, only if you turn it on in the Dictation tab. It is
  never uploaded, in either mode.
- A debug log, off by default, which holds dictated text (and the text
  read before the cursor) and the recordings of the last 30 dictations
  if turned on.
- An error log (errors.log) of program errors, so a problem can be
  diagnosed. It never contains dictated text and is never uploaded.

All of these are in %LOCALAPPDATA%\Talkative. The uninstaller offers to
delete that folder.


Contact
-------

Questions: open an issue at https://github.com/sumitdas76/talkative/issues,
or use the Feedback box in Settings > About.
