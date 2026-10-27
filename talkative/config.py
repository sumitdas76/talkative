from pynput import keyboard

# Hold this key (or these two keys together) to dictate, release any of
# them to transcribe + insert (or tap to start/stop, see HOTKEY_MODE).
# Always a tuple of 1-2 pynput Key/KeyCode
# objects, even for a single-key hotkey, so app.py's listener can treat
# every hotkey as a chord uniformly. Right Ctrl is rarely bound to anything
# else system-wide.
HOTKEY = (keyboard.Key.ctrl_r,)

# faster-whisper model. Smaller = faster/less accurate, larger = slower/more accurate.
# ".en" suffixed models are English-only and a bit faster/more accurate for English speech.
# Options roughly by size: tiny.en, base.en, small.en, medium.en, large-v3
MODEL_SIZE = "small.en"
DEVICE = "cpu"
COMPUTE_TYPE = "int8"

SAMPLE_RATE = 16000

# Fed to Whisper as decoder context (initial_prompt) so it continues in the
# same style: punctuated, capitalized sentences. Whisper reliably punctuates
# read-aloud speech but often drops all punctuation on long spontaneous
# dictation; this seed text counteracts that. Deliberately plain, neutral
# wording -- distinctive words in a prompt can leak into transcripts.
PUNCTUATION_PROMPT = (
    "Okay, here is my next note. I dictate in complete sentences, with "
    "commas where needed, and each sentence ends with a period."
)

# Text just before the cursor in the target field, added to the end of the
# speech-to-text prompt so names and terms already on screen are spelled
# the same way (screen_context.py). On in both modes, not a setting
# (2026-10-26, user's choice): in Cloud the text is sent to the speech
# service with the audio (PRIVACY.md). Never in developer English, whose
# prompt sets a literal-symbol style that prose would undo.
CONTEXT_LOCAL = True
CONTEXT_CLOUD = True
CONTEXT_MAX_CHARS = 400

# Pressing the hotkey again within this many seconds of the last paste, in
# the same window, carries on that sentence: its full stop is taken back
# and the new text starts in lowercase (continuation.py). 0 = off.
CONTINUE_SECONDS = 4.0
# After each dictation the microphone stays open CONTINUE_SECONDS, keeping
# only this many seconds in memory; a re-press in that time starts with
# them, so a word said while pressing isn't lost (audio_recorder.py).
# Never sent unless the hotkey is pressed again. 0.0 = off (mic closes
# at once, as before 1.3.17); settings key "preroll_seconds".
PREROLL_SECONDS = 0.75
# Dictating into the middle of a sentence (continuation.fit_to_cursor):
# lowercase start after a mid-sentence word, no full stop when the sentence
# carries on after the cursor. Reads the text around the caret on this PC
# only, in both modes. Settings key "fit_to_cursor".
FIT_TO_CURSOR = True

# Presses shorter than this are treated as accidental taps and discarded.
MIN_RECORDING_SECONDS = 0.3

# "hold": hold the hotkey while speaking, release to insert.
# "toggle": tap the hotkey to start, tap it again to stop and insert, for
# users who find holding a key through a long dictation tiring. Holding
# still works in toggle mode: a press longer than TAP_MAX_SECONDS stops on
# release, exactly like "hold".
HOTKEY_MODE = "hold"

# Toggle mode: a press released within this many seconds is a tap and
# leaves recording on.
TAP_MAX_SECONDS = 0.4

# Toggle mode: a recording left on stops itself (and is inserted) after
# this long, so a forgotten tap can't record indefinitely. Well under
# Groq's 25 MB upload limit (~13 minutes of 16 kHz 16-bit WAV).
TOGGLE_MAX_SECONDS = 300

# How long to wait after simulating Ctrl+V before restoring the user's original clipboard.
CLIPBOARD_RESTORE_DELAY = 0.4

# Turn spoken self-correction detection on/off without touching the trigger list.
ENABLE_SELF_CORRECTION = True

# Convert spoken symbol names ("underscore", "dot", "at sign", ...) into
# the literal character (spoken_symbols.py) -- on by default, applies in
# both cleanup modes since it's a transcription-fidelity fix, not a style
# choice.
ENABLE_SPOKEN_SYMBOLS = True

# Second hotkey for "developer English": a dictation made with it goes
# through dev_mode.py (SQL, terminal commands and code come out as runnable
# text) instead of the normal cleanup. A separate key rather than a mode
# switch, so the choice is made per dictation and never left on by
# accident -- its rules ("star" -> *, no sentence period) are wrong for
# ordinary writing. May contain HOTKEY (the default does): holding the
# normal key and then adding the extra one upgrades that recording to
# developer English. Empty tuple = off.
DEV_HOTKEY = (keyboard.Key.ctrl_r, keyboard.Key.shift_r)

# SELF_CORRECTION_TRIGGERS: phrases that signal the speaker is retracting what
# they just said and the following words should replace it (e.g. "Send it
# tomorrow, no wait, send it Friday." -> "Send it Friday."). Kept deliberately
# short and mostly unambiguous -- phrases like bare "actually" or "I mean" are
# intentionally excluded because they're common ordinary filler/transition
# words that don't signal a retraction (e.g. "I mean, it's fine either way"),
# and "correction"/"ignore that"/"disregard that" are excluded because they
# collide with plausible literal dictated content. Add phrases here if you
# want to opt into a riskier trigger.
SELF_CORRECTION_TRIGGERS = [
    "scratch that",
    "strike that",
    "no wait",
    "wait no",
    "sorry, I mean",
    "sorry I mean",
    "no sorry",
    "sorry no",
    "I meant to say",
    "let me correct that",
    "let me correct myself",
    "let me rephrase",
    "let me say that again",
]

# ---------------------------------------------------------------------------
# Cleanup: "Cleaned up" vs "As spoken"
# ---------------------------------------------------------------------------
# "cleaned_up": fillers, spoken corrections, and near-repeat restatements are
# removed before insertion. "as_spoken": verbatim transcription. The personal
# dictionary applies in both modes.
CLEANUP_MODE = "cleaned_up"

# Filler words stripped in cleaned_up mode, whole words only. "like" and
# "you know" are deliberately excluded -- too often real dictated content.
FILLER_WORDS = ["um", "umm", "uh", "uhh", "uhm", "erm"]
# "you know" is removed only where it's plainly a filler: between commas,
# or opening a sentence with a comma after it (cleanup._remove_you_know).
# "Do you know", "you know what I mean", "as you know" stay.
REMOVE_YOU_KNOW = True

# Grammar engine (invisible stage 2 of cleaned_up mode; see
# grammar_engine.py). Off means rules-only even when the model is
# installed. Missing model silently degrades to rules-only regardless.
ENABLE_GRAMMAR_ENGINE = True
# Folder name under the app models dir holding the engine model. Normally
# "grammar"; the July 2026 A/B audition installs two candidates side by
# side ("grammar-15" = Qwen2.5-1.5B, "grammar-05" = Qwen2.5-0.5B) switched
# via the grammar_model settings key + app restart.
GRAMMAR_MODEL_DIR = "grammar"
# Public Hugging Face repo holding the CTranslate2 int8 conversion, so the
# engine can be downloaded on demand (grammar_engine.download()) instead of
# only ever arriving bundled in the installer. Empty string disables the
# Download button (falls back to "reinstall Talkative" as the only path).
GRAMMAR_HF_REPO = "sumitdas76/talkative-grammar"
# Guard: reject engine output that retains less than this fraction of the
# input's words (words removed as retractions/repeats count as lost, so
# don't set this above ~0.7 or legitimate cleanups get rejected).
# Loosened from 0.7 on 2026-07-20 (see grammar_engine._retention_ok) to
# allow genuine rewording of garbled/unclear sentences, at the user's
# request -- accepts more risk of the model changing what was said in
# exchange for more helpful rewrites.
GRAMMAR_MIN_RETENTION = 0.4
# Guard: every input sentence must keep at least this fraction of its own
# content words (stopwords excluded) in the output. 0.2 (2026-07-20 to
# 2026-09-27) let a whole dropped question through because three of its
# words happened to appear elsewhere in the output ("...company...lot...
# AI"). 0.5 caught that and rejected none of 130+ good local outputs or
# 119 good Cloud outputs in the 2026-09-27 evaluation.
GRAMMAR_MIN_SENTENCE_RETENTION = 0.5
# The local engine's stricter leash (2026-10-13): the July loosening above
# let the 1.5B model change meaning on real speech, so Local counts each
# word occurrence against this instead of GRAMMAR_MIN_RETENTION, and also
# must not add or drop a content word (grammar_engine.validate(strict=True)).
GRAMMAR_LOCAL_MIN_RETENTION = 0.7
# Local grammar on slow hardware: the engine measures its own speed on this
# PC and skips the pass for a dictation it predicts would take longer than
# this, pasting the rules-cleaned text instead of making the user wait
# (an old CPU with DDR4 can be several times slower than the 6-core DDR5
# dev machine, where the longest test dictation took ~6.4s).
GRAMMAR_MAX_SECONDS = 10.0
# Use an NVIDIA GPU for the local models when CTranslate2 can see one;
# anything failing on it falls back to the CPU.
USE_GPU = True
# Local speech recognition beam width (faster-whisper's default is 5).
STT_BEAM_SIZE = 5

# ---------------------------------------------------------------------------
# Processing: "cloud" (default, ships out of the box -- see cloud/ and
# CHANGELOG.md) vs "local" (fully offline, downloaded separately from
# Settings -> General -> Processing). "cloud" skips loading the local
# Whisper and grammar models entirely (no RAM, no download) and instead
# sends audio and text to CLOUD_ENDPOINT_URL (a Cloudflare Worker) for the
# same two steps. Empty CLOUD_ENDPOINT_URL is treated as "not configured"
# and falls back to local processing even if PROCESSING_MODE is "cloud".
# ---------------------------------------------------------------------------
PROCESSING_MODE = "cloud"
CLOUD_ENDPOINT_URL = "https://talkative-cloud.sumitdas76.workers.dev"
# Cloud mode's speech-to-text, shown in Settings as the accent:
# "us_english" -- Groq's Whisper (Talkative Cloud, as always), or
# "indian_english" -- Microsoft Azure Speech en-IN on the maintainer's own
# free Azure resource, called by the Worker (cloud/worker.js
# azureTranscribe; 2026-10-23). Azure busy or its free hours used up: the
# Worker falls back to Groq for that dictation. Developer English always
# uses Groq (its literal-symbol prompt needs Whisper).
SPEECH_SERVICE = "us_english"
# Cloud busy or unreachable: app._cloud_transcribe() uses the Local voice
# model when it's downloaded (kept loaded FALLBACK_IDLE_SECONDS after its
# last use), otherwise retries Cloud after each of these waits (seconds).
CLOUD_RETRY_DELAYS = (2.0, 6.0)
# Seconds an open Cloud connection may sit idle before cloud_client opens a
# new one instead of reusing it (2026-10-13). Cloudflare kept idle
# connections open for 180 s+ (measured), but home routers and mobile
# networks may silently drop them sooner, and a request sent on a dropped
# one hangs until its timeout instead of failing fast -- so stay short.
CLOUD_CONN_MAX_IDLE = 50.0
FALLBACK_IDLE_SECONDS = 300
# The main loop naps 0.2 s; a nap this much longer means the PC slept, and
# app._on_resume() resets the hotkey hook, key state and audio.
RESUME_GAP_SECONDS = 10
# Windows tells app._watch_microphones when a microphone is plugged in,
# unplugged or made the default (no polling); PortAudio then re-reads its
# list, so "System default" follows Windows without a restart. Only if
# Windows refuses the registration does it ask every MIC_CHECK_SECONDS
# instead (0.4 ms of CPU per check, measured). MIC_SETTLE_SECONDS lets a
# burst of notifications (one plug-in sends several) finish first.
MIC_CHECK_SECONDS = 2.0
MIC_SETTLE_SECONDS = 0.5
# Showing what happens to a dictation (2026-10-27, user report: up to 10 s
# and more with nothing on screen, and sometimes nothing typed with no
# reason given). After release the listening line shows "processing"; this
# long without a result, a "still working" notice appears; a dictation
# that won't be typed says why for NOT_TYPED_SECONDS.
SLOW_NOTICE_SECONDS = 6.0
NOT_TYPED_SECONDS = 5.0
# Cloud transcription gives up on a stalled request after this many
# seconds plus a quarter of the recording's length (at most 30).
CLOUD_TIMEOUT_BASE = 10.0
# Problems found while the user is still speaking (2026-10-27, user
# request: better to hear mid-speech than after). Only certain signals:
# the microphone muted in Windows (asked when the hotkey goes down); after
# LIVE_CHECK_SECONDS of recording, no audio at all, or no new audio for
# LIVE_STALL_SECONDS (device gone); and Cloud unreachable when the hotkey
# went down (connecting gives up after CLOUD_WARM_TIMEOUT). Digital
# silence is NOT one of them (see BLANK_PEAK).
LIVE_CHECK_SECONDS = 1.5
LIVE_STALL_SECONDS = 1.0
CLOUD_WARM_TIMEOUT = 5.0
# A recording whose loudest sample is below this is digital silence. That
# is a muted or dead microphone -- or a noise-suppressing headset while
# nobody speaks (Logi H340, unmuted, gives +-1 step: 0.00003), so it is
# never reported as a problem on its own; it only triggers a device
# re-check and, when no words came back, a gentler "nothing was heard".
BLANK_PEAK = 0.0005
# Main-loop checks (0.2 s apart) a hold-mode recording may run with its
# hotkey physically up before app._check_lost_release drops it as a lost
# release (Ctrl+Alt+Del, lock screen). 3 = 0.6 s: well past the hook's own
# release event, which arrives within milliseconds.
LOST_RELEASE_CHECKS = 3
# Sent as the X-Shared-Secret header on every cloud request -- a soft
# deterrent only (it ships inside a public EXE, so treat it as
# extractable), not real auth. The real protection is the Worker's
# per-install daily quota plus Workers AI's own free-tier hard cap -- see
# cloud/worker.js's module docstring.
CLOUD_SHARED_SECRET = "zw5qf1UUIexr2i2NckpwGlsMOCE0SICICiL0dS6qy40"
# One-time notice shown the first time Cloud mode actually activates,
# explaining Local can be downloaded separately (see cloud_notice.py).
CLOUD_NOTICE_DONE = False
# One-time Cloud-vs-Local onboarding screen (see onboarding.py), shown
# before cloud_notice.py's notice and try_it_now.py's tutorial. A brand
# new key as of 2026-09-19 -- absent from every settings.json written
# before this existed, so it defaults False and the screen is shown once
# to existing installs too, not just fresh ones (deliberate; see
# CLAUDE.md's onboarding note).
ONBOARDING_DONE = False
# Local setup downloads the grammar model (Optimize Narration) in the
# background after the speech model, so dictation works minutes sooner.
# True while that download is owed; resumed at the next start if the app
# was closed mid-way. Only set by the app itself, so a model the user
# deleted in Settings is never re-downloaded behind their back.
GRAMMAR_PENDING_DOWNLOAD = False

# ---------------------------------------------------------------------------
# Dictation history: an opt-in, local-only log of the final text from each
# dictation (what was actually pasted), for the user's own reference. MUST
# default False -- same "nothing is saved" privacy stance as DEBUG_LOG,
# except this one is user-facing and user-controlled rather than a dev aid.
# ---------------------------------------------------------------------------
ENABLE_HISTORY = False

# Near-repeat collapsing: when two consecutive sentences in one dictation are
# nearly identical, keep only the second (the speaker restated themselves).
# Deliberately conservative -- both sentences must share their opening word
# and exceed REPEAT_SIMILARITY, and runs of 3+ same-opening sentences (spoken
# lists) are never collapsed, because wrongly merging two intentional
# sentences deletes the user's words (the worst possible failure).
ENABLE_REPEAT_COLLAPSE = True
REPEAT_SIMILARITY = 0.75

# Numbers written as a careful writer would type them: digits for 10+, times,
# money, percentages, dates; words for small counts and sentence openers
# (numbers.py). Cleaned-up mode only, never for developer English.
ENABLE_NUMBER_FORMAT = True

# Spoken points ("first ... second ...", "point one ... point two ...")
# typed as "• " bullet lines under the lead-in sentence (bullets.py).
# Cleaned-up mode only, never for developer English.
ENABLE_BULLETS = True

# ---------------------------------------------------------------------------
# Personal dictionary: spoken -> typed
# ---------------------------------------------------------------------------
# Whole-word/phrase replacements applied after cleanup. Matching is
# case-insensitive; the replacement is capitalized when it starts a sentence.
# The terms are also fed to Whisper as vocabulary hints so they are more
# likely to be *heard* correctly in the first place.
# Empty by default: users add their own entries in Settings > Auto Text.
# (Until 1.3.11 this shipped the developer's personal entries, so every new
# install expanded "AI" to "artificial intelligence".)
DICTIONARY = {}
# Those pre-1.3.11 entries stayed in every settings.json that was saved
# before then. settings.remove_old_examples() deletes them once (only pairs
# still exactly as shipped), then sets this so a user who re-adds one on
# purpose keeps it.
OLD_EXAMPLE_ENTRIES = {
    "asap": "as soon as possible",
    "AI": "artificial intelligence",
    "Captivate": "Adobe Captivate",
    "PPT": "PowerPoint",
    "Sumit": "Sumit Chatterjee",
}
OLD_EXAMPLES_REMOVED = False
# Notice when the user corrects a name or term Talkative typed and offer it
# as an Auto Text entry (fix_learning.py). Suggestions only: nothing is
# added until the user clicks Add in Settings. The pairs are kept here
# (saved in settings.json, this PC only); dismissed ones aren't offered
# again.
LEARN_FIXES = True
FIX_SUGGESTIONS = []
FIX_DISMISSED = []
# Off by default: biasing Whisper toward short name-like terms makes it
# mishear ordinary phrases as those terms (observed live: "Send it Monday"
# transcribed as "Sumit Monday", which the dictionary then expanded to
# "Sumit Das Monday"). Text replacement above is unaffected. Only
# re-enable after testing with the specific dictionary in use.
ENABLE_RECOGNITION_BIAS = False

# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------
# "type": paste into the focused control. "clipboard": copy only, never paste.
INSERT_MODE = "type"
# Trailing space after inserted text so consecutive dictations don't run together.
APPEND_SPACE = True
# Simulate Enter after inserting (useful for chat apps). Off by default.
PRESS_ENTER_AFTER = False

# ---------------------------------------------------------------------------
# Sounds and microphone
# ---------------------------------------------------------------------------
# Settings window appearance: "light", "dark", or "system" (follow the
# Windows app theme).
THEME = "system"
# Color scheme (palette.py): "forest", "coral" or "teal" -- Settings,
# its header band and the listening pill.
COLOR_SCHEME = "forest"

# No sounds: the start/stop/done beeps were removed 2026-10-04 at the
# user's request (the listening pill already shows when Talkative is
# hearing you), and they were what crashed it -- see audio_recorder.PA_LOCK.
# None = system default input device; otherwise a sounddevice input index
# (set via the Audio tab in Settings).
INPUT_DEVICE = None

# ---------------------------------------------------------------------------
# Updates (spec section 7)
# ---------------------------------------------------------------------------
# Public manifest describing the current model versions. Empty string
# disables checking entirely. Fetched when the last successful check is
# UPDATE_CHECK_HOURS old; offline or malformed is logged and retried.
MANIFEST_URL = (
    "https://raw.githubusercontent.com/sumitdas76/talkative-updates/"
    "main/manifest.json"
)
# Latest published app release, checked in the same pass
# as MANIFEST_URL. A newer version than the running one shows a prompt that
# opens the release page -- it never downloads or installs anything itself.
# Empty string disables the check.
RELEASES_API_URL = (
    "https://api.github.com/repos/sumitdas76/talkative/releases/latest"
)
# Opened by Settings > About's "Read the privacy policy" link.
PRIVACY_URL = "https://github.com/sumitdas76/talkative/blob/main/PRIVACY.md"
# The replaced model is kept for undo until this many words have been
# dictated with the new one (usage-based grace, spec section 7.6).
UPDATE_GRACE_WORDS = 1000
# Updates are checked (at startup, and hourly while running) when the last
# successful check is at least this old.
UPDATE_CHECK_HOURS = 12

# ---------------------------------------------------------------------------
# Feedback (spec queue #4) -- the app's only outbound data path, and only
# ever sent when the user clicks Send in the About tab.
# ---------------------------------------------------------------------------
# Random per-install ID, generated once and persisted (see settings.py's
# "install_id" key). Sent along with feedback so a reply can be matched
# back to this install; not tied to any personal info.
INSTALL_ID = ""
# Public JSON where Sumit hand-publishes replies, keyed by install_id --
# same repo/workflow as MANIFEST_URL. Empty string disables reply polling.
FEEDBACK_REPLIES_URL = (
    "https://raw.githubusercontent.com/sumitdas76/talkative-updates/"
    "main/replies.json"
)
# Date of the last daily reply check, and the id/text of the last reply
# already shown -- both persisted so a reply is surfaced exactly once and
# stays visible in Settings across restarts.
FEEDBACK_LAST_CHECK = ""
FEEDBACK_LAST_SEEN = ""
FEEDBACK_LAST_REPLY = ""
# An image the user attaches to a feedback message (screenshot). FormSubmit
# allows 10 MB in total per message; 5 MB keeps a slow upload bearable.
FEEDBACK_IMAGE_MAX_BYTES = 5 * 1024 * 1024
FEEDBACK_IMAGE_TYPES = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".gif": "image/gif", ".bmp": "image/bmp", ".webp": "image/webp",
}

# ---------------------------------------------------------------------------
# Debugging
# ---------------------------------------------------------------------------
# Append every dictation's raw Whisper transcript and each pipeline stage's
# output to %LOCALAPPDATA%\Talkative\debug.log. Development aid for
# diagnosing cleanup behavior -- the raw transcript is the ground truth the
# rules operate on. MUST default False: it stores dictated text on disk,
# which would contradict the About tab's privacy statement. Developers
# opt in per machine via the debug_log settings key.
DEBUG_LOG = False
# With DEBUG_LOG on, also keep the audio of this many most recent
# dictations as WAV files in %LOCALAPPDATA%\Talkative\debug_audio, named
# in debug.log, so a misheard dictation ("Can you" typed as "Can I",
# 2026-10-04 and 2026-10-20) can be replayed and tested. 0 = none.
DEBUG_AUDIO_KEEP = 30
# "Send diagnostic data" (diagnostics.py): each dictation's stages and
# recording go to Talkative's server, kept 30 days for the maintainer.
# MUST default False; the user turns it on in Settings > About and
# confirms what is sent.
SEND_DIAGNOSTICS = False

# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------
# Synced to the per-user Windows Run registry key at every launch.
START_WITH_WINDOWS = False

# Set (persisted) after the first-run "try it now" box has been shown once.
FIRST_RUN_DONE = False
