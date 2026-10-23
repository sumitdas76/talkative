"""
Speech-to-text with the user's own Azure Speech key (idea 6, 2026-10-23).

For users who want another recognizer than Talkative Cloud's Groq Whisper,
with no shared quota: they create a free (F0) Azure Speech resource,
paste its key and region into Settings, and Cloud-mode dictations are
transcribed by Azure directly from this PC -- the audio never reaches
Talkative's server. Grammar cleanup still runs as configured.

Azure's free tier (checked 2026-10-23, learn.microsoft.com quotas page):
real-time recognition only, one request at a time, a monthly allowance of
audio hours that doesn't bill past it. Microsoft says real-time audio is
processed in memory and "Microsoft does not retain or store the data".
The REST API for short audio takes at most 60 s per request, so longer
dictations are cut at pauses (Silero VAD) into pieces under
_MAX_PIECE_SECONDS and sent one after another. It has no prompt, so
screen context (screen_context.py) can't help it.

The key is stored in settings.json encrypted with Windows DPAPI (only this
Windows user on this PC can decrypt it) and never logged.
"""

import base64
import json
import logging
import re
import urllib.error
import urllib.parse
import urllib.request

import numpy as np

from . import cloud_client, config, settings

log = logging.getLogger(__name__)

_MAX_PIECE_SECONDS = 55
_TIMEOUT = 30

LANGUAGES = [
    ("English (India)", "en-IN"),
    ("English (United States)", "en-US"),
    ("English (United Kingdom)", "en-GB"),
    ("English (Australia)", "en-AU"),
    ("English (Nigeria)", "en-NG"),
]


class AzureError(RuntimeError):
    """A failure the user should hear about in plain words."""


# ------------------------------------------------------------------ key

def _protect(text):
    import win32crypt
    blob = win32crypt.CryptProtectData(text.encode("utf-8"), "Talkative Azure key",
                                       None, None, None, 0)
    return base64.b64encode(blob).decode("ascii")


def _unprotect(stored):
    import win32crypt
    _, data = win32crypt.CryptUnprotectData(base64.b64decode(stored), None, None, None, 0)
    return data.decode("utf-8")


def key():
    """The saved key, or "" when none is saved or it can't be decrypted
    (settings.json copied from another PC or Windows user)."""
    if not config.AZURE_KEY_PROTECTED:
        return ""
    try:
        return _unprotect(config.AZURE_KEY_PROTECTED)
    except Exception:
        log.warning("Saved Azure key could not be decrypted")
        return ""


def save_key(value):
    """Encrypt and save `value` ("" removes the key)."""
    value = (value or "").strip()
    config.AZURE_KEY_PROTECTED = _protect(value) if value else ""
    settings.save({"azure_key_protected": config.AZURE_KEY_PROTECTED})


def configured():
    return bool(config.AZURE_REGION and key())


def active(cloud):
    """Whether this dictation goes to Azure: Cloud mode, Azure picked as
    the speech service, and a key and region saved."""
    return cloud and config.SPEECH_SERVICE == "azure" and configured()


# ------------------------------------------------------------------ audio

def _pieces(audio, sample_rate):
    """`audio` cut into pieces no longer than _MAX_PIECE_SECONDS, in the
    middle of a pause between words where possible (short pauses count:
    Silero VAD with a 300 ms minimum silence), hard cuts only through a
    stretch of speech with no pause at all."""
    limit = _MAX_PIECE_SECONDS * sample_rate
    if audio.size <= limit:
        return [audio]
    try:
        from faster_whisper.vad import VadOptions, get_speech_timestamps
        segments = get_speech_timestamps(
            audio, VadOptions(min_silence_duration_ms=300, speech_pad_ms=0),
            sampling_rate=sample_rate)
    except Exception:
        segments = []
    cuts, piece_start, prev_end = [], 0, None
    for seg in segments:
        # This segment would overflow the piece, and the piece already has
        # speech in it: cut in the pause before this segment.
        if seg["end"] - piece_start > limit and prev_end is not None and prev_end > piece_start:
            cut = (prev_end + seg["start"]) // 2
            cuts.append(cut)
            piece_start = cut
        prev_end = seg["end"]
    out, prev = [], 0
    for cut in cuts + [audio.size]:
        piece = audio[prev:cut]
        while piece.size > limit:  # one stretch of speech longer than the limit
            out.append(piece[:limit])
            piece = piece[limit:]
        if piece.size:
            out.append(piece)
        prev = cut
    return out


def _recognize(wav, region, language, subscription_key):
    # Goes into the host name: letters and digits only ("centralindia").
    if not re.fullmatch(r"[a-z0-9]{2,40}", region or ""):
        raise AzureError("That Azure region doesn't look right. Use the "
                         "Location shown with your key, like centralindia.")
    url = (f"https://{urllib.parse.quote(region)}.stt.speech.microsoft.com/speech/"
           "recognition/conversation/cognitiveservices/v1?"
           + urllib.parse.urlencode({"language": language, "format": "simple",
                                     "profanity": "raw"}))
    req = urllib.request.Request(url, data=wav, headers={
        "Ocp-Apim-Subscription-Key": subscription_key,
        "Content-Type": "audio/wav; codecs=audio/pcm; samplerate=16000",
        "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
            result = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise AzureError("Azure didn't accept the key. Check the key and "
                             "region in Settings.") from exc
        if exc.code == 429:
            raise AzureError("Azure is busy or this month's free hours are used up.") from exc
        raise AzureError(f"Azure Speech failed (HTTP {exc.code}).") from exc
    except (urllib.error.URLError, OSError) as exc:
        raise AzureError("Couldn't reach Azure Speech. Check the region and "
                         "your internet connection.") from exc
    status = result.get("RecognitionStatus")
    if status == "Success":
        return str(result.get("DisplayText", "")).strip()
    if status in ("NoMatch", "InitialSilenceTimeout", "BabbleTimeout"):
        return ""
    raise AzureError(f"Azure Speech couldn't transcribe that ({status}).")


def transcribe(audio, sample_rate, initial_prompt=None):
    """Same contract as cloud_client.transcribe(): the transcript, "" for
    no speech, raises (AzureError) on failure. `initial_prompt` is
    accepted for the same call shape and unused (no prompt in this API)."""
    if sample_rate != 16000:
        raise AzureError("Azure Speech needs 16 kHz audio.")
    subscription_key = key()
    if not (config.AZURE_REGION and subscription_key):
        raise AzureError("No Azure key saved. Add one in Settings, or switch "
                         "the speech service back to Talkative Cloud.")
    end = cloud_client._speech_end(audio, sample_rate)
    if end == 0:
        return ""
    audio = cloud_client._trim_trailing_silence(audio, sample_rate, speech_end=end)
    texts = []
    for piece in _pieces(np.asarray(audio, dtype=np.float32), sample_rate):
        text = _recognize(cloud_client._wav_bytes(piece, sample_rate),
                          config.AZURE_REGION, config.AZURE_LANGUAGE, subscription_key)
        if text:
            texts.append(text)
    return " ".join(texts)


def test_key(region, subscription_key):
    """Settings' Test button: one second of silence through the real API.
    Returns None when the key and region work, else a plain message."""
    try:
        _recognize(cloud_client._wav_bytes(np.zeros(16000, np.float32), 16000),
                   region.strip().lower().replace(" ", ""), config.AZURE_LANGUAGE,
                   subscription_key.strip())
        return None
    except AzureError as exc:
        return str(exc)
