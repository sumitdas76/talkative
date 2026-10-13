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

Stdlib only, explicit timeouts, and the same graceful-degradation
contract each function's local counterpart already has. Unlike
updater.py/feedback.py, requests reuse open HTTPS connections (see _post).
"""

import base64
import http.client
import io
import json
import threading
import time
import urllib.error
import urllib.parse
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


# Reused HTTPS connections (2026-10-13). urllib opens a new connection --
# TCP + TLS handshake -- for every request, and Cloudflare often serves
# India from Singapore/Tokyo/Hong Kong rather than Mumbai (all evening on
# 2026-10-11, and mornings too), where each handshake costs ~0.2 s or more:
# measured 386 ms per request on a new connection vs 173 ms reused (SIN).
# A dictation makes two requests, and warm() opens one while the user is
# still speaking. Idle connections are pooled (not one shared one) so two
# overlapping dictations never wait on each other.
_pool = []
_pool_lock = threading.Lock()
_POOL_MAX = 2
_RETRYABLE = (http.client.RemoteDisconnected, http.client.BadStatusLine,
              http.client.CannotSendRequest, ConnectionResetError,
              ConnectionAbortedError, BrokenPipeError)


def _target():
    """(host, port, base path) for direct connections, or None to go
    through urllib: a non-HTTPS endpoint, or a system proxy -- urllib
    honours Windows' proxy settings, http.client doesn't."""
    u = urllib.parse.urlsplit(config.CLOUD_ENDPOINT_URL)
    if u.scheme != "https" or not u.hostname:
        return None
    try:
        if urllib.request.getproxies().get("https"):
            return None
    except Exception:
        return None
    return u.hostname, u.port or 443, u.path.rstrip("/")


def _take(host, port, timeout):
    """An idle pooled connection to host:port that hasn't sat longer than
    CLOUD_CONN_MAX_IDLE, or a new (not yet connected) one. Returns
    (conn, reused)."""
    now = time.monotonic()
    with _pool_lock:
        while _pool:
            conn, last = _pool.pop()
            if (conn.host, conn.port) == (host, port) and now - last < config.CLOUD_CONN_MAX_IDLE:
                conn.timeout = timeout
                if conn.sock is not None:
                    conn.sock.settimeout(timeout)
                return conn, conn.sock is not None
            conn.close()
    return http.client.HTTPSConnection(host, port, timeout=timeout), False


def _give_back(conn):
    with _pool_lock:
        if len(_pool) < _POOL_MAX:
            _pool.append((conn, time.monotonic()))
            return
    conn.close()


def warm():
    """Open a connection ahead of the next request (called when the hotkey
    goes down in Cloud mode), so the handshake happens while the user
    speaks. Never raises."""
    try:
        target = _target()
        if target is None:
            return
        host, port, _ = target
        conn, reused = _take(host, port, 10)
        if not reused:
            conn.connect()
        _give_back(conn)
    except Exception:
        pass


def _post(route, body, headers, timeout):
    """POST to the Worker -> (status, response bytes). Raises on network
    failure. A reused connection the server has quietly closed fails on
    first use; that one is retried once on a new connection."""
    target = _target()
    if target is None:
        url = config.CLOUD_ENDPOINT_URL.rstrip("/") + route
        req = urllib.request.Request(url, data=body, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read()
    host, port, base = target
    for attempt in (0, 1):
        conn, reused = _take(host, port, timeout) if attempt == 0 else (
            http.client.HTTPSConnection(host, port, timeout=timeout), False)
        try:
            conn.request("POST", base + route, body=body, headers=headers)
            resp = conn.getresponse()
            data = resp.read()
        except _RETRYABLE:
            conn.close()
            if reused:
                continue
            raise
        except Exception:
            conn.close()
            raise
        if resp.will_close:
            conn.close()
        else:
            _give_back(conn)
        return resp.status, data


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


def _has_speech(audio, sample_rate):
    """False only when Silero VAD finds no speech anywhere in `audio`.

    Groq's Whisper invents text for a press with nothing said ("Thank
    you.", and with a bias prompt whole prompt-flavored sentences like
    "So, I'll show you how to do it." or "dot com"), and its
    verbose_json no_speech_prob is always 0 (measured 2026-09-26), so the
    Worker can't filter it. Local mode never has this problem because
    faster-whisper's vad_filter runs this same Silero model first; run it
    here too and don't send silence at all. Measured: 6/6 silent/noise/
    hum/click clips rejected, 40/40 spoken clips kept (incl. one-word
    "Yes." and speech at 3% volume), ~5 ms per call. Only gates -- speech
    audio is sent unchanged. Any VAD failure sends the audio as before.
    """
    if audio is None or audio.size == 0:
        return False
    try:
        from faster_whisper.vad import get_speech_timestamps
        return bool(get_speech_timestamps(audio, sampling_rate=sample_rate))
    except Exception:
        return True


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
    if not _has_speech(audio, sample_rate):
        return ""
    audio = _trim_trailing_silence(audio, sample_rate)
    body = _wav_bytes(audio, sample_rate)
    headers = _headers("audio/wav")
    if initial_prompt:
        # The bias prompt (sentence style + personal-dictionary vocabulary,
        # or developer mode's literal-symbol style) reaches Groq's `prompt`
        # field via the Worker. Base64 because headers must be ASCII and
        # dictionary words needn't be. Until 2026-09-25 this was accepted
        # and silently dropped, so Cloud mode never got any biasing.
        headers["X-Prompt-B64"] = base64.b64encode(
            initial_prompt[:800].encode("utf-8")).decode("ascii")
    status, data = _post("/transcribe", body, headers, timeout=30)
    if status == 429:
        raise RuntimeError(CLOUD_BUSY_MESSAGE)
    if status != 200:
        raise RuntimeError(f"Cloud transcription failed: HTTP {status}")
    result = json.loads(data.decode("utf-8"))
    return str(result.get("text", "")).strip()


def grammar_apply(text):
    """Same contract as grammar_engine.apply(): on any failure or guard
    rejection, return `text` unchanged -- cleanup must never break
    dictation. The deterministic guards (grammar_engine.validate) run here client-side (the
    Worker's model output is trusted no more than the local model's)."""
    if not text:
        return text
    try:
        body = json.dumps({"text": text}).encode("utf-8")
        status, data = _post("/grammar", body, _headers("application/json"), timeout=20)
        if status != 200:
            return text
        result = json.loads(data.decode("utf-8"))
        out = str(result.get("text", "")).strip()
    except Exception:
        return text
    if not grammar_engine.validate(text, out):
        return text
    return out
