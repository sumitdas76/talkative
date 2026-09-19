"""Cloud processing mode (see config.PROCESSING_MODE).

Sends the two model-backed pipeline stages -- speech-to-text and grammar
cleanup -- to a Cloudflare Worker (cloud/worker.js) instead of running them
on-device, so the local app never loads faster-whisper or the grammar
engine. Every request carries this install's anonymous id (X-Install-Id,
see feedback.install_id()) so the Worker can enforce a per-install daily
quota -- the shared secret alone is not real protection once it ships
inside a public EXE (see worker.js's module docstring for the full
reasoning); the quota plus Workers AI's own free-tier daily cap are what
actually bound cost/abuse.

Same house networking style as updater.py/feedback.py: stdlib
urllib.request only, explicit timeouts, and the same graceful-degradation
contract each function's local counterpart already has.
"""

import io
import json
import urllib.error
import urllib.request
import wave

import numpy as np

from . import config, feedback, grammar_engine

CLOUD_BUSY_MESSAGE = "Cloud is busy right now -- please try again in a bit."


def _headers(content_type):
    return {
        "Content-Type": content_type,
        # Cloudflare's default edge bot rules 403 Python's stock urllib
        # User-Agent before the request ever reaches the Worker -- same
        # issue already worked around in feedback.py for FormSubmit.
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/124.0.0.0 Safari/537.36"),
        "X-Shared-Secret": config.CLOUD_SHARED_SECRET,
        "X-Install-Id": feedback.install_id(),
    }


def _trim_trailing_silence(audio, sample_rate, threshold=0.01,
                            frame_ms=30, pad_ms=300, min_keep_secs=0.3):
    """Drop trailing near-silence from `audio` before sending it to Cloud.

    Groq's hosted whisper-large-v3-turbo (like Whisper-family models
    generally) reliably hallucinates a stock closing phrase -- "Thank
    you." was the one observed live, 2026-09-19, 5-for-5 reproducible --
    when fed trailing silence, a known artifact of training on captioned
    video data. faster-whisper's own vad_filter already prevents this in
    Local mode; Cloud had no equivalent, so it's done here instead,
    client-side, before the audio ever leaves this device.

    Deliberately conservative: a coarse energy check, not real VAD, and it
    leaves `audio` completely unchanged whenever the signal is ambiguous
    (barely any audio, no clear loud region, or trimming would leave next
    to nothing) rather than risk cutting real trailing speech -- e.g. a
    dictation that genuinely ends "...thank you." must not be shortened.
    """
    if audio is None or audio.size == 0:
        return audio
    frame = max(1, int(sample_rate * frame_ms / 1000))
    n_frames = audio.size // frame
    if n_frames < 2:
        return audio

    last_loud = -1
    for i in range(n_frames):
        chunk = audio[i * frame:(i + 1) * frame]
        rms = float(np.sqrt(np.mean(chunk.astype(np.float64) ** 2)))
        if rms >= threshold:
            last_loud = i

    if last_loud == -1 or last_loud >= n_frames - 1:
        # All silence, or already ends on a loud frame -- nothing to trim.
        return audio

    pad = int(sample_rate * pad_ms / 1000)
    cutoff = min(audio.size, (last_loud + 1) * frame + pad)
    if cutoff < sample_rate * min_keep_secs:
        return audio
    return audio[:cutoff]


def _wav_bytes(audio, sample_rate):
    """float32 numpy array in [-1, 1] -> 16-bit PCM WAV bytes, via the
    stdlib wave module (no new dependency needed)."""
    pcm = np.clip(audio, -1.0, 1.0)
    pcm = (pcm * 32767.0).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm.tobytes())
    return buf.getvalue()


def transcribe(audio, sample_rate, initial_prompt=None):
    """Same contract as Transcriber.transcribe(): returns the transcript
    string, raises on failure (the app.py call site already handles that
    the same way it handles a local transcription failure)."""
    audio = _trim_trailing_silence(audio, sample_rate)
    body = _wav_bytes(audio, sample_rate)
    url = config.CLOUD_ENDPOINT_URL.rstrip("/") + "/transcribe"
    req = urllib.request.Request(url, data=body, headers=_headers("audio/wav"))
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            result = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            raise RuntimeError(CLOUD_BUSY_MESSAGE) from None
        raise
    return str(result.get("text", "")).strip()


def grammar_apply(text):
    """Same contract as grammar_engine.apply(): on any failure or guard
    rejection, return `text` unchanged -- cleanup must never break
    dictation. The six deterministic guards run here client-side (the
    Worker's model output is trusted no more than the local model's)."""
    if not text:
        return text
    try:
        url = config.CLOUD_ENDPOINT_URL.rstrip("/") + "/grammar"
        body = json.dumps({"text": text}).encode("utf-8")
        req = urllib.request.Request(url, data=body, headers=_headers("application/json"))
        with urllib.request.urlopen(req, timeout=20) as r:
            result = json.loads(r.read().decode("utf-8"))
        out = str(result.get("text", "")).strip()
    except Exception:
        return text
    if not grammar_engine.validate(text, out):
        return text
    return out
