"""Slow-starting microphones: find them, keep them ready.

Some microphones send pure digital silence (exact zeros) for their first
~0.2-0.5 s after being opened. Talkative opens the mic when the hotkey is
pressed, so on those the first word of every dictation was lost (user
report 2026-10-31: a Creative Live! Cam webcam, 225-290 ms of zeros from
cold, every recording that day; their Logi H340 headset: 0 ms).

  * probe(): at startup and after Windows reports a microphone change,
    the mic Talkative will use is opened for PROBE_SECONDS and the
    leading zeros counted. The audio is thrown away -- only the number
    is kept. Bluetooth mics are skipped: opening one switches the headset
    to call mode, and any music playing drops to phone quality.
  * observe(): every dictation that opened the mic from cold is checked
    the same way, so a slow mic is still found if the probe was skipped
    or inconclusive (2 of the last 3 such dictations).
  * is_slow(): app keeps a slow mic open SLOW_MIC_KEEP_SECONDS after each
    dictation (audio_recorder's linger: only the last PREROLL_SECONDS are
    held in memory, nothing is sent unless the hotkey is pressed again).

A mic that sends zeros the whole time (a hardware noise gate in a quiet
room) is "unknown", not slow: the zeros must end in real sound.
"""

import collections
import logging
import threading
import time

import numpy as np

from . import config

log = logging.getLogger(__name__)

# |sample| at or below this counts as digital silence: a waking mic sends
# zeros dithered by one 16-bit step (3e-5), measured on the webcam; real
# room noise from a working mic is ~50x that.
ZERO = 1.5 / 32768
# After the silence, a start-up check needs at least this much sound
# (RMS of the next 50 ms) to call it a slow start: a mic that is merely
# very quiet (noise suppression in a silent room) stays "unknown".
FLOOR_RMS = 4e-4

_lock = threading.Lock()
_slow = {}   # device key -> leading silence in ms, for mics found slow
_measured = {}  # device key -> last start-up silence measured, any verdict
_seen = collections.defaultdict(lambda: collections.deque(maxlen=3))


def _dead_runs(a, sample_rate, min_ms):
    """(starts, ends) sample indexes of digital-silence runs >= min_ms."""
    dead = (np.abs(a) <= ZERO).astype(np.int8)
    edges = np.diff(np.concatenate(([0], dead, [0])))
    starts, ends = np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)
    keep = (ends - starts) >= sample_rate * min_ms / 1000
    return starts[keep], ends[keep]


def leading_silence_ms(audio, sample_rate=16000):
    """Where the mic's start-up silence ends, in ms: the end of a run of
    digital silence (>= 100 ms) that begins in the first 100 ms. 0 when
    there is none; None when the silence lasts to the end (can't tell: no
    sound reached it at all). Starting within 100 ms, not at sample 0:
    the webcam sometimes sends ~40 ms of old buffer first, then ~270 ms
    of silence (2026-10-31: "Can I go now..." -> "I go now...")."""
    a = np.asarray(audio).reshape(-1)
    if not a.size or not np.any(np.abs(a) > ZERO):
        return None
    starts, ends = _dead_runs(a, sample_rate, 100)
    early = np.flatnonzero(starts <= sample_rate * 0.1)
    if not early.size:
        return 0.0
    end = ends[early[0]]
    if end >= a.size:
        return None
    return end * 1000.0 / sample_rate


def loud_onset(audio, sample_rate=16000):
    """Does the sound right after the start-up silence begin at speaking
    level? A mic that was simply quiet ramps up from room noise; one that
    cut the speaker off starts mid-word."""
    a = np.asarray(audio).reshape(-1)
    ms = leading_silence_ms(a, sample_rate)
    if ms is None:
        return False
    start = int(ms * sample_rate / 1000)
    win = a[start:start + int(sample_rate * 0.05)]
    return bool(win.size) and float(np.sqrt(np.mean(win ** 2))) >= config.SLOW_MIC_ONSET_RMS


def silent_later(audio, sample_rate=16000):
    """Digital silence (>= 150 ms) after the start-up silence too? Then
    the mic sends silence whenever nobody speaks (noise-suppressing
    headsets like the Logi H340 do) and a silent start says nothing."""
    a = np.asarray(audio).reshape(-1)
    ms = leading_silence_ms(a, sample_rate) or 0.0
    starts, _ = _dead_runs(a, sample_rate, 150)
    return bool(np.any(starts > ms * sample_rate / 1000))


def device_key(device):
    """A stable key for a sounddevice input (index or None = the Windows
    default): its name, which survives PortAudio renumbering."""
    try:
        import sounddevice as sd
        from .audio_recorder import PA_LOCK
        with PA_LOCK:  # PortAudio isn't thread-safe; see audio_recorder
            if device is None:
                device = sd.default.device[0]
            return sd.query_devices(device)["name"]
    except Exception:
        return None


def is_slow(device):
    key = device_key(device)
    with _lock:
        return key is not None and key in _slow


def slow_ms(device):
    key = device_key(device)
    with _lock:
        return _slow.get(key)


def measured_ms(device):
    """The last start-up silence measured for this mic, or None."""
    key = device_key(device)
    with _lock:
        return _measured.get(key)


def _mark(key, ms, why, clear=True):
    """Record a verdict; returns True when the mic newly became slow.
    clear=False: a fast result doesn't undo an earlier slow one."""
    with _lock:
        was = key in _slow
        if ms is not None:
            _measured[key] = ms
        if ms is not None and ms >= config.SLOW_MIC_MS:
            _slow[key] = ms
        elif clear:
            _slow.pop(key, None)
        now = key in _slow
    if now != was:
        log.info("Microphone %r %s (%s, %s ms of silence at start)",
                 key, "starts slowly" if now else "starts normally", why,
                 "?" if ms is None else round(ms))
    return now and not was


def mark_slow(device, ms, why):
    """A test dictation showed the start cut off: slow now (no need to
    wait for a second one). True when the mic newly became slow."""
    key = device_key(device)
    return key is not None and _mark(key, ms, why, clear=False)


def probe(device, recorder_busy=lambda: False):
    """Open `device` for PROBE_SECONDS, measure its start-up silence and
    record the verdict. Returns the ms measured, or None if skipped or
    inconclusive. Never raises."""
    key = device_key(device)
    if key is None or is_bluetooth(device):
        return None
    if recorder_busy():
        return None  # warm already; the measurement would be meaningless
    try:
        import sounddevice as sd
        from .audio_recorder import PA_LOCK
        chunks = []
        with PA_LOCK:
            stream = sd.InputStream(samplerate=16000, channels=1, dtype="float32",
                                    device=device,
                                    callback=lambda x, f, t, s: chunks.append(x.copy()))
            stream.start()
        time.sleep(config.SLOW_MIC_PROBE_SECONDS)
        with PA_LOCK:
            stream.stop()
            stream.close()
        audio = np.concatenate(chunks).reshape(-1) if chunks else np.zeros(0, "float32")
        ms = leading_silence_ms(audio)
    except Exception:
        log.warning("Microphone start-up check failed", exc_info=True)
        return None
    if ms is None:
        return None  # silence throughout: muted or gated, can't tell
    if ms >= config.SLOW_MIC_MS:
        start = int(ms * 16)
        after = audio[start:start + 800]
        if not after.size or float(np.sqrt(np.mean(after ** 2))) < FLOOR_RMS:
            return None  # only a very quiet mic, not a waking one
    # Another app holding the mic open makes it look fast here, so a fast
    # result never undoes a slow verdict from real dictations.
    _mark(key, ms, "start-up check", clear=False)
    return ms


def observe(device, audio, cold, sample_rate=16000):
    """A dictation finished. Only one that opened the mic from cold says
    anything about start-up. Returns True when this made the mic slow."""
    if not cold:
        return False
    key = device_key(device)
    if key is None:
        return False
    ms = leading_silence_ms(audio, sample_rate)
    if ms is None:
        return False
    if ms >= config.SLOW_MIC_MS:
        if not loud_onset(audio, sample_rate):
            return False  # quiet start: the user may simply not have spoken yet
        if silent_later(audio, sample_rate):
            return False  # a mic that goes silent between words, not a waking one
        verdict = True
    elif ms < config.SLOW_MIC_MS / 3:
        verdict = False
    else:
        return False
    with _lock:
        seen = _seen[key]
        seen.append((verdict, ms))
        slow_votes = [m for v, m in seen if v]
        known = key in _slow
    if not known and len(slow_votes) >= 2:
        return _mark(key, max(slow_votes), "dictations")
    return False


def is_bluetooth(device):
    """Best effort: is this a Bluetooth microphone? (Windows names its
    hands-free endpoints that way; the device's enumerator says BTH...)"""
    key = device_key(device) or ""
    low = key.lower()
    if "hands-free" in low or "bluetooth" in low or "bth" in low:
        return True
    try:
        from . import audio_devices
        return audio_devices.input_is_bluetooth(key)
    except Exception:
        return False


def reset_for_tests():
    with _lock:
        _slow.clear()
        _seen.clear()
        _measured.clear()
