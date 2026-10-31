"""What a test dictation says about the microphone (first-run "Try it
now" box and Settings > Audio & Output > Test microphone, 2026-10-31).

The user asked for the app to test each microphone and tune itself,
since users have thousands of different ones. What can't be tuned away
(a mic that wakes slowly, one that is too quiet) has to be found and
explained, so the user can fix it while they are still setting up:

  * nothing heard -- the wrong microphone is selected, or it is muted
  * very quiet -- too far away, or the Windows input volume is low
  * distorting -- input volume too high (clipped samples)
  * noisy -- background noise close to the voice's level
  * first word cut -- the mic sent silence for its first few hundred ms
    (mic_warmup's start-up check; Talkative keeps such a mic ready)

Pure functions on the recorded audio, nothing saved or sent. Thresholds
come from this PC's debug.log: real speech reads level 0.02-0.16.
"""

import numpy as np

from . import config, mic_warmup

QUIET_LEVEL = 0.012  # 90th-percentile 30 ms RMS below this: hard to hear
CLIP_SAMPLE = 0.98
CLIP_SHARE = 0.002  # this share of samples at full scale: distorting
NOISY_RATIO = 0.5  # background (10th percentile) / voice (90th); the webcam
# here reads 0.2-0.37 and transcribes fine


def _frames_rms(audio, sample_rate):
    frame = int(sample_rate * 0.03)
    n = audio.size // frame
    if not n:
        return np.zeros(0)
    return np.sqrt(np.mean(audio[:n * frame].reshape(n, frame) ** 2, axis=1))


def analyse(audio, sample_rate=16000, cold=False):
    """[(kind, message)] for one test dictation, worst first; kind is
    "ok", "nothing", "quiet", "clipping", "noisy" or "cut"."""
    a = np.asarray(audio, dtype="float32").reshape(-1)
    if not a.size or float(np.max(np.abs(a))) < config.BLANK_PEAK:
        return [("nothing", "Nothing was heard. Pick the microphone you're "
                            "speaking into, and check it isn't muted.")]
    rms = _frames_rms(a, sample_rate)
    voice = float(np.percentile(rms, 90)) if rms.size else 0.0
    floor = float(np.percentile(rms, 10)) if rms.size else 0.0
    found = []
    if np.mean(np.abs(a) >= CLIP_SAMPLE) >= CLIP_SHARE:
        found.append(("clipping", "Your voice is distorting. Lower the microphone "
                                  "volume in Windows sound settings."))
    if voice < QUIET_LEVEL:
        found.append(("quiet", "Very quiet. Move closer to the microphone, or raise "
                               "its volume in Windows sound settings."))
    elif floor / voice >= NOISY_RATIO:
        found.append(("noisy", "Your voice is hard to hear over the background noise. "
                               "Speak closer to the microphone, or use a headset."))
    if cold:
        ms = mic_warmup.leading_silence_ms(a, sample_rate)
        if (ms is not None and ms >= config.SLOW_MIC_MS
                and mic_warmup.loud_onset(a, sample_rate)
                and not mic_warmup.silent_later(a, sample_rate)):
            found.append(("cut", f"This microphone took {ms / 1000:.1f} s to start, so "
                                 "your first word may be missing. Talkative now keeps it "
                                 "ready between dictations; start talking when the line "
                                 "at the bottom of the screen lights up."))
    return found or [("ok", "Heard you clearly.")]


def startup_text(device):
    """How fast the mic starts, for the test box's microphone line."""
    if mic_warmup.is_bluetooth(device):
        return "Bluetooth microphone: start-up speed isn't checked."
    slow = mic_warmup.slow_ms(device)
    if slow is None and mic_warmup.kept_by_user(device):
        minutes = round(config.SLOW_MIC_KEEP_SECONDS / 60)
        return (f"Kept ready for {minutes} minutes after each dictation, since "
                "you said the start was cut off.")
    if slow is not None:
        minutes = round(config.SLOW_MIC_KEEP_SECONDS / 60)
        return (f"Takes {slow / 1000:.1f} s to start, so Talkative keeps it ready "
                f"for {minutes} minutes after each dictation.")
    if mic_warmup.measured_ms(device) is not None:
        return "Starts instantly."
    return "Checking how fast it starts..."


# ------------------------------------------------ "Not what I said"

def _words(text):
    import re
    return [w.lower().strip("'") for w in re.findall(r"[A-Za-z0-9']+", text or "")]


def compare(typed, said, cloud=True, accent="us_english"):
    """The user corrected a test dictation ("Not what I said", user request
    2026-10-31: "first few letters get cropped off ... there is no button
    that says the typing is incorrect"). Returns (findings, fixes):
    findings [(kind, message)]; fixes {"keep_ready": bool, "auto_text":
    [(heard, typed)]}. kind: "same", "empty", "start", "end", "names",
    "many"."""
    import difflib

    from . import fix_learning

    fixes = {"keep_ready": False, "auto_text": []}
    t, s = _words(typed), _words(said)
    if not s:
        return [("empty", "Type what you said, then click Check.")], fixes
    if not t:
        return [("empty", "Nothing was typed for that dictation, so the microphone "
                          "gave no usable sound. Check the microphone picked above "
                          "isn't muted, and speak while holding the key.")], fixes
    if t == s:
        return [("same", "That matches what was typed. If only capitals or punctuation "
                         "differ, nothing needs fixing.")], fixes
    found = []
    ops = difflib.SequenceMatcher(None, t, s, autojunk=False).get_opcodes()
    tag, i1, i2, j1, j2 = ops[0]
    # The start lost: whole words missing ("I test" for "Can I test"), or
    # the first word's first letters ("an I" for "Can I").
    if (tag == "insert" and i1 == 0) or (
            tag == "replace" and i2 - i1 == 1 and j2 - j1 <= 2
            and s[j2 - 1] != t[0] and s[j2 - 1].endswith(t[0])):
        fixes["keep_ready"] = True
        found.append(("start", "The start was cut off. Talkative will now keep this "
                               "microphone ready between dictations, so the first word "
                               "is caught even if you start talking as you press the key. "
                               "Try again."))
    tag, i1, i2, j1, j2 = ops[-1]
    if tag == "insert" and i1 == len(t):
        found.append(("end", "The end was cut off. Keep holding the key until you've "
                             "finished the last word."))
    pairs = fix_learning.suggestions(typed, said)
    if pairs:
        fixes["auto_text"] = pairs
        shown = ", ".join(f"\"{h}\" → \"{w}\"" for h, w in pairs)
        found.append(("names", f"Misheard: {shown}. Add to Auto Text to type it "
                               "your way every time."))
    matched = sum(b.size for b in difflib.SequenceMatcher(
        None, t, s, autojunk=False).get_matching_blocks())
    if matched < 0.7 * len(s) and not any(k == "start" for k, _ in found):
        if not cloud:
            tip = ("Local's voice model is smaller; Cloud (Settings > General > "
                   "Processing) recognises speech better.")
        elif accent == "us_english":
            tip = ("If you have an Indian accent, choose Indian English under "
                   "Settings > General > Processing > Cloud.")
        else:
            tip = "Speak a little slower and closer to the microphone, then try again."
        found.append(("many", "Many words were misheard. " + tip))
    if not found:
        found.append(("names", "A few words differ. If one is a name, Talkative learns "
                               "it when you correct it after dictating (Settings > Auto "
                               "Text lists the suggestions)."))
    return found, fixes
