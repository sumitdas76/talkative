"""
"Send diagnostic data" (2026-10-23, at the user's request: a Yes/No
setting like big apps have, so a friend with a problem -- commas missing --
can share what actually happened).

Off by default (config.SEND_DIAGNOSTICS). When on, each dictation sends one
report to Talkative's server (cloud/worker.js /diagnostics): what
speech-to-text heard, each cleanup step, the final text, timings, the
settings that shape the result, and the recording (up to
MAX_AUDIO_SECONDS). The text before the cursor (screen_context.py) is
never included, only its length. The server keeps reports 30 days, for
the maintainer only (PRIVACY.md).

Sent on its own thread after the text is typed, so it never delays a
dictation, and any failure is only logged.
"""

import base64
import json
import logging
import platform
import threading

from . import __version__, config

log = logging.getLogger(__name__)

MAX_AUDIO_SECONDS = 55


def _settings_summary(cloud):
    return {
        "processing": "cloud" if cloud else "local",
        "speech_service": config.SPEECH_SERVICE if cloud else "local " + config.MODEL_SIZE,
        "cleanup_mode": config.CLEANUP_MODE,
        "context": config.CONTEXT_CLOUD if cloud else config.CONTEXT_LOCAL,
    }


def send(audio, cloud, stages):
    """Queue one dictation's report. `stages` is what app.py writes to
    debug.log (audio, raw, fillers, ..., final, timing); `context` is
    replaced by its length. Never raises."""
    if not config.SEND_DIAGNOSTICS:
        return
    try:
        stages = dict(stages)
        if "context" in stages:
            stages["context"] = f"{len(stages['context'] or '')} characters (text not sent)"
        report = {
            "version": __version__,
            "windows": platform.version(),
            "settings": _settings_summary(cloud),
            "stages": {k: str(v)[:4000] for k, v in stages.items()},
        }
        wav = None
        if audio is not None and 0 < audio.size <= MAX_AUDIO_SECONDS * config.SAMPLE_RATE:
            from .cloud_client import _wav_bytes
            wav = _wav_bytes(audio, config.SAMPLE_RATE)
    except Exception:
        log.warning("could not build a diagnostic report", exc_info=True)
        return
    threading.Thread(target=_post, args=(report, wav), daemon=True).start()


def _post(report, wav):
    from .cloud_client import _headers, _post as post

    try:
        body = {"report": report}
        if wav:
            body["audio_b64"] = base64.b64encode(wav).decode("ascii")
        status, _ = post("/diagnostics", json.dumps(body).encode("utf-8"),
                         _headers("application/json"), timeout=30)
        if status != 200:
            log.warning("diagnostic report not accepted (HTTP %s)", status)
    except Exception as exc:
        log.warning("could not send a diagnostic report (%s)", exc)
