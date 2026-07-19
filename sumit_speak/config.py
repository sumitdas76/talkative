from pynput import keyboard

# Hold this key to dictate, release to transcribe + insert.
# Right Ctrl is rarely bound to anything else system-wide.
HOTKEY = keyboard.Key.ctrl_r

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

# Presses shorter than this are treated as accidental taps and discarded.
MIN_RECORDING_SECONDS = 0.3

# How long to wait after simulating Ctrl+V before restoring the user's original clipboard.
CLIPBOARD_RESTORE_DELAY = 0.4

# Turn spoken self-correction detection on/off without touching the trigger list.
ENABLE_SELF_CORRECTION = True

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
FILLER_WORDS = ["um", "uh", "uhm", "erm"]

# Grammar engine (invisible stage 2 of cleaned_up mode; see
# grammar_engine.py). Off means rules-only even when the model is
# installed. Missing model silently degrades to rules-only regardless.
ENABLE_GRAMMAR_ENGINE = True
# Folder name under the app models dir holding the engine model. Normally
# "grammar"; the July 2026 A/B audition installs two candidates side by
# side ("grammar-15" = Qwen2.5-1.5B, "grammar-05" = Qwen2.5-0.5B) switched
# via the grammar_model settings key + app restart.
GRAMMAR_MODEL_DIR = "grammar"
# Guard: reject engine output that retains less than this fraction of the
# input's words (words removed as retractions/repeats count as lost, so
# don't set this above ~0.7 or legitimate cleanups get rejected).
GRAMMAR_MIN_RETENTION = 0.7

# Near-repeat collapsing: when two consecutive sentences in one dictation are
# nearly identical, keep only the second (the speaker restated themselves).
# Deliberately conservative -- both sentences must share their opening word
# and reach REPEAT_SIMILARITY, because wrongly merging two intentional
# sentences deletes the user's words (the worst possible failure).
ENABLE_REPEAT_COLLAPSE = True
REPEAT_SIMILARITY = 0.75

# ---------------------------------------------------------------------------
# Personal dictionary: spoken -> typed
# ---------------------------------------------------------------------------
# Whole-word/phrase replacements applied after cleanup. Matching is
# case-insensitive; the replacement is capitalized when it starts a sentence.
# The terms are also fed to Whisper as vocabulary hints so they are more
# likely to be *heard* correctly in the first place.
DICTIONARY = {
    "asap": "as soon as possible",
    "AI": "artificial intelligence",
    "Captivate": "Adobe Captivate",
    "PPT": "PowerPoint",
    "Sumit": "Sumit Chatterjee",
}
# Off by default: biasing Whisper toward short name-like terms makes it
# mishear ordinary phrases as those terms (observed live: "Send it Monday"
# transcribed as "Sumit Monday", which the dictionary then expanded to
# "Sumit Chatterjee Monday"). Text replacement above is unaffected. Only
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

# Short tones when recording starts/stops and when text is inserted.
PLAY_SOUNDS = True
# Loudness of those tones, 0.0-1.0. They are generated soft sine waves played
# through the sound mixer -- winsound.Beep was rejected because it plays a
# harsh square wave at full volume with no volume control. (0.2 was still
# too loud for the user; halved July 19.)
SOUND_VOLUME = 0.1
# None = system default input device; otherwise a sounddevice input index
# (set via the Audio tab in Settings).
INPUT_DEVICE = None

# ---------------------------------------------------------------------------
# Updates (spec section 7)
# ---------------------------------------------------------------------------
# Public manifest describing the current model versions. Empty string
# disables checking entirely. Fetched at most once a day at startup;
# offline or malformed is silently ignored.
MANIFEST_URL = ""  # e.g. https://raw.githubusercontent.com/<user>/sumit-speak-updates/main/manifest.json
# The replaced model is kept for undo until this many words have been
# dictated with the new one (usage-based grace, spec section 7.6).
UPDATE_GRACE_WORDS = 1000

# ---------------------------------------------------------------------------
# Debugging
# ---------------------------------------------------------------------------
# Append every dictation's raw Whisper transcript and each pipeline stage's
# output to %LOCALAPPDATA%\SumitSpeak\debug.log. Development aid for
# diagnosing cleanup behavior -- the raw transcript is the ground truth the
# rules operate on. MUST default False: it stores dictated text on disk,
# which would contradict the About tab's privacy statement. Developers
# opt in per machine via the debug_log settings key.
DEBUG_LOG = False

# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------
# Synced to the per-user Windows Run registry key at every launch.
START_WITH_WINDOWS = False
