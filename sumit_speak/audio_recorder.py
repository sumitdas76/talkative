import numpy as np
import sounddevice as sd


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

        self._stream.stop()
        self._stream.close()
        self._stream = None

        if not self._frames:
            return np.array([], dtype="float32")

        return np.concatenate(self._frames, axis=0).flatten()

    def snapshot(self, max_seconds=None):
        """Concatenate whatever has been recorded so far without stopping
        the stream -- for the live-preview loop. `list(self._frames)` takes
        a shallow copy of the list at this instant; the audio callback may
        keep appending to the *original* list afterward, but that doesn't
        mutate our copy, so this is safe to call from another thread
        without a lock (same reasoning as the existing cross-thread read of
        `self.level`). `max_seconds`, if given, trims to the most recent
        window so a long recording doesn't make each preview call slower."""
        frames = list(self._frames)
        if not frames:
            return np.array([], dtype="float32")
        audio = np.concatenate(frames, axis=0).flatten()
        if max_seconds is not None:
            max_samples = int(self.sample_rate * max_seconds)
            if audio.size > max_samples:
                audio = audio[-max_samples:]
        return audio
