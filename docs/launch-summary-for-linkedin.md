# Sumit Speak — launch story (paste this into Claude Chat as source material)

Context: I'm Sumit Chatterjee, a non-programmer. Working with Claude (AI
pair-programmer in Claude Code), I designed and shipped a complete Windows
desktop product. Use the facts below to draft a LinkedIn post.

## The product

**Sumit Speak** — hold-to-talk dictation for Windows that runs entirely
offline. Hold a key, speak, release: your words are typed into whatever
app has focus (Word, chats, browsers). Nothing ever leaves the PC — no
cloud, no account, no telemetry.

What makes it special:
- **Cleaned-up mode**: filler words ("um", "uh"), stutters, repetitions,
  and spoken self-corrections ("send it Monday — no wait, Friday") are
  removed automatically. A small local AI grammar engine (runs on the
  user's own CPU) tidies punctuation and grammar, with strict safety
  guards so it can never change names, numbers, or delete the speaker's
  words.
- **Personal Auto Text**: say "asap", it types "as soon as possible";
  say a colleague's short name, it types the full one.
- Two speech models to choose from: Fast (instant) and Accurate
  (best recognition), switchable from a settings UI, downloaded and
  managed inside the app.
- A floating "listening" indicator with a live voice level, light/dark
  themes, custom hotkeys, sounds — a real, polished product.

## Shipped today (v1.0.1, publicly released)

- Public download: https://github.com/sumitdas76/sumit-speak/releases/latest
  (Windows installer — next-next-finish, no admin rights needed)
- A full auto-update system: I publish a model improvement by editing one
  JSON file on GitHub in my browser; every installed copy politely offers
  the update, installs it safely in the background, and users can undo
  any update with one click.
- Everything hosted for $0: GitHub for downloads and updates, models from
  Hugging Face.

## The story angle (true details worth using)

- Built by a non-programmer + AI pair: I described what I wanted in plain
  language (often by dictating with the app itself!), Claude wrote,
  tested, and shipped the code, and I tested every build live.
- The whole product went from spec to publicly downloadable release —
  engine, settings UI, local AI grammar engine, updater, installer —
  through iterative sessions.
- We even "auditioned" three small AI models against my real dictation
  transcripts to pick the grammar engine — the one that never mangled a
  number won.
- Privacy is the backbone: the app's promise is "your voice never leaves
  this PC," and we kept a development feature (debug logging) out of the
  shipped version because it contradicted that promise.

Tone preferences for the post: authentic, first-person, enthusiastic but
not salesy; mention the human+AI collaboration honestly.
