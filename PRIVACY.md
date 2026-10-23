Talkative Privacy Policy
========================

Last updated: 2026-10-23

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
- Only if you turn it on (Settings > Dictation > Accuracy, "Also in
  Cloud mode"; off by default): up to 400 characters of the text just
  before the cursor in the box you're dictating into, sent with the
  audio so names and terms already there are spelled the same way.
  Password boxes are never read.
- The transcribed text, for grammar and punctuation cleanup.
- An anonymous install ID: a random number created on your PC the first
  time Talkative runs. It isn't tied to your name, email, or device,
  and is used only to enforce a fair daily usage limit per install.

These go to Talkative's server, a Cloudflare Worker run by the
Talkative maintainer (talkative-cloud.sumitdas76.workers.dev), which
forwards the audio and text to:

- Groq, for speech-to-text and grammar cleanup.
  Privacy policy: https://groq.com/privacy-policy/
- Cloudflare Workers AI, as a backup for speech-to-text and grammar
  cleanup when Groq is unavailable.
  Privacy policy: https://www.cloudflare.com/privacypolicy/

Talkative's server does not store or log your audio or text. It keeps
two counts, both reset every day: how many requests each install ID
made today, and how many came from each network address today. The
address itself is not stored, only a one-way scrambled form of it
(a hash) that the count is filed under. The services above process your data under
their own policies, linked above.

### Your own Azure Speech key (optional)

In Cloud mode you can choose, in Settings > General > Processing, to
have speech-to-text done by Microsoft Azure with your own Azure Speech
key. Then each dictation's audio goes straight from your PC to
Microsoft (the region you entered), not to Talkative's server, under
your own Azure account and Microsoft's terms
(https://learn.microsoft.com/azure/ai-foundry/responsible-ai/speech-service/speech-to-text/data-privacy-security).
Grammar cleanup still goes to Talkative's server as described above. If
Azure fails, that dictation goes to Talkative's server instead. Your key
is saved on your PC encrypted with Windows' own data protection, so only
your Windows account on that PC can read it.

### Local mode

Speech recognition and cleanup run entirely on your PC. After the
one-time download of the voice and grammar models (from Hugging Face),
your audio and text never leave your computer. To spell names and terms
correctly, Talkative reads up to 400 characters of the text before the
cursor when you start dictating (never from password boxes); in Local
mode that text stays on your PC, and you can turn it off in
Settings > Dictation > Accuracy.


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
