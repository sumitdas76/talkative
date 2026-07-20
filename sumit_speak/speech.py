"""Offline spoken feedback via Windows SAPI (pywin32 already shipped).

Used for the no-editable-field cue: a friendlier alternative to a blocking
error popup when the user dictates into nothing.

SAPI is asked to render into an in-memory PCM stream rather than play
directly, then that PCM is handed to sounddevice -- the same playback path
the tones use -- so the spoken cue honors config.OUTPUT_DEVICE instead of
always going to the Windows-wide default output device the way SAPI's own
playback would.

Each call creates its own SAPI voice on a fresh thread (COM apartment-
threaded objects shouldn't be shared across threads) and does the
synthesis + playback synchronously *within that thread* -- callers get
control back immediately, which is the asynchrony that matters here. Voice
feedback is a nicety, never load-bearing: every failure is silent.
"""

import threading

from . import config

_SAFT_16kHz_16BIT_MONO = 18  # SpeechAudioFormatType enum, SAPI automation
_RATE = 16000


def speak(text, volume=1.0):
    """Speak `text` asynchronously (relative to the caller), through
    config.OUTPUT_DEVICE. `volume` is 0.0-1.0, linearly scaled onto SAPI's
    0-100 range. Never raises."""

    def _run():
        try:
            import numpy as np
            import pythoncom
            import sounddevice as sd
            import win32com.client

            pythoncom.CoInitialize()
            try:
                fmt = win32com.client.Dispatch("SAPI.SpAudioFormat")
                fmt.Type = _SAFT_16kHz_16BIT_MONO
                stream = win32com.client.Dispatch("SAPI.SpMemoryStream")
                stream.Format = fmt

                sapi_voice = win32com.client.Dispatch("SAPI.SpVoice")
                for candidate in sapi_voice.GetVoices():
                    if "zira" in candidate.GetDescription().lower():
                        sapi_voice.Voice = candidate
                        break  # else: fall back to the default voice
                sapi_voice.Volume = max(0, min(100, int(volume * 100)))
                sapi_voice.AudioOutputStream = stream
                sapi_voice.Speak(text)

                pcm = np.frombuffer(bytes(stream.GetData()), dtype="<i2")
                samples = pcm.astype("float32") / 32768.0
                sd.play(samples, samplerate=_RATE,
                        device=config.OUTPUT_DEVICE, blocking=True)
            finally:
                pythoncom.CoUninitialize()
        except Exception:
            pass

    threading.Thread(target=_run, daemon=True).start()
