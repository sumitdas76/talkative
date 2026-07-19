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
# Short tones when recording starts and stops.
PLAY_SOUNDS = True
# Loudness of those tones, 0.0-1.0. They are generated soft sine waves played
# through the sound mixer -- winsound.Beep was rejected because it plays a
# harsh square wave at full volume with no volume control.
SOUND_VOLUME = 0.2
# None = system default input device; otherwise a sounddevice input index
# (set via the Audio tab in Settings).
INPUT_DEVICE = None

# ---------------------------------------------------------------------------
# Debugging
# ---------------------------------------------------------------------------
# Append every dictation's raw Whisper transcript and each pipeline stage's
# output to %LOCALAPPDATA%\SumitSpeak\debug.log. Development aid for
# diagnosing cleanup behavior -- the raw transcript is the ground truth the
# rules operate on. Will become a hidden setting in Phase 2.
DEBUG_LOG = True

# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------
# Synced to the per-user Windows Run registry key at every launch.
START_WITH_WINDOWS = False
