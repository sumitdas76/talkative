import threading

import numpy as np
import sounddevice as sd

# PortAudio's API isn't thread-safe: opening, starting, stopping or
# closing streams from two threads at once corrupts its heap. Talkative
# did exactly that -- the start/stop beep opened an output stream on its
# own thread while the hotkey thread started or closed the microphone --
# and crashed in ntdll on the input callback thread (2026-10-03 and
# 2026-10-04, same signature both times; tools/e2e/audio_race_test.py
# reproduces it in seconds). Every PortAudio call goes through this lock.
PA_LOCK = threading.RLock()


def play(samples, sample_rate, device=None):
    """Blocking playback of a mono float32 array on a stream of its own.
    Not sd.play(): that shares one module-global stream between callers,
    so a second beep thread stopped the first one's stream mid-callback."""
    with PA_LOCK:
        stream = sd.OutputStream(samplerate=sample_rate, channels=1,
                                 dtype="float32", device=device)
        stream.start()
    try:
        stream.write(np.ascontiguousarray(samples, dtype="float32").reshape(-1, 1))
    finally:
        with PA_LOCK:
            try:
                stream.stop()
            finally:
                stream.close()


class AudioRecorder:
    """Records mono audio from the default input device into an in-memory
    buffer between start() and stop()."""

    def __init__(self, sample_rate=16000, channels=1, device=None):
        self.sample_rate = sample_rate
        self.channels = channels
        self.device = device  # None = system default input
        self._stream = None
        self._frames = []
        # RMS of the most recent chunk, 0.0-1.0-ish; read by the listening
        # pill's animation loop. Plain float write is atomic enough.
        self.level = 0.0

    def _callback(self, indata, frames, time_info, status):
        self._frames.append(indata.copy())
        self.level = float(np.sqrt(np.mean(indata ** 2)))

    def start(self):
        self._frames = []
        with PA_LOCK:
            self._stream = sd.InputStream(
                samplerate=self.sample_rate,
                channels=self.channels,
                dtype="float32",
                device=self.device,
                callback=self._callback,
            )
            self._stream.start()

    def stop(self):
        if self._stream is None:
            return np.array([], dtype="float32")

        # The device can vanish mid-recording (Bluetooth headset dropping,
        # USB mic unplugged) and stop() then raises. That used to escape
        # into the hotkey listener and end dictation until a restart; keep
        # whatever was captured instead.
        stream, self._stream = self._stream, None
        with PA_LOCK:
            try:
                stream.stop()
            except Exception:
                pass
            try:
                stream.close()
            except Exception:
                pass

        if not self._frames:
            return np.array([], dtype="float32")

        return np.concatenate(self._frames, axis=0).flatten()
