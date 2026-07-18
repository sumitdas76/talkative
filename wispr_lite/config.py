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
    "I meant to say",
    "let me correct that",
    "let me correct myself",
]
