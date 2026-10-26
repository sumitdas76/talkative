import collections
import threading
import time

import numpy as np
import sounddevice as sd

# PortAudio's API isn't thread-safe: opening, starting, stopping or
# closing streams from two threads at once corrupts its heap. Talkative
# did exactly that -- the start/stop beep opened an output stream on its
# own thread while the hotkey thread started or closed the microphone --
# and crashed in ntdll on the input callback thread (2026-10-03 and
# 2026-10-04, same signature both times). The beeps are gone since, but
# every PortAudio call (recording here, Settings' device list) still
# goes through this lock, so a future sound can't bring the crash back.
PA_LOCK = threading.RLock()


class AudioRecorder:
    """Records mono audio from the default input device into an in-memory
    buffer between start() and stop().

    stop(linger=N) keeps the stream open N more seconds, holding only the
    last `preroll` seconds in memory; a start() in that time begins with
    them. People pressing the hotkey again to carry on a sentence start
    talking as they press, and the first word was lost (1.3.16 live test:
    "move the meeting to Friday" -> "to Friday"). The held audio is all
    from after the last stop, so nothing is ever transcribed twice; if the
    stream isn't reopened in time it is closed and the audio dropped."""

    def __init__(self, sample_rate=16000, channels=1, device=None):
        self.sample_rate = sample_rate
        self.channels = channels
        self.device = device  # None = system default input
        self.preroll = 0.0  # seconds kept for a re-press; app sets it
        self._stream = None
        self._stream_device = None
        self._frames = []
        self._recording = False
        self._held = collections.deque()  # chunks since the last stop()
        self._held_len = 0
        self._lock = threading.Lock()  # _frames/_held vs the audio callback
        self._close_timer = None
        # RMS of the most recent chunk, 0.0-1.0-ish; read by the listening
        # pill's animation loop. Plain float write is atomic enough.
        self.level = 0.0
        # This recording so far, for app._check_live_mic (a dead or muted
        # microphone is reported while the user is still speaking):
        # chunks received, when the last one came, and the loudest sample.
        self.chunks = 0
        self.last_chunk = 0.0
        self.peak = 0.0

    def _callback(self, indata, frames, time_info, status):
        chunk = indata.copy()
        with self._lock:
            if self._recording:
                self._frames.append(chunk)
            else:
                self._held.append(chunk)
                self._held_len += len(chunk)
                keep = int(self.preroll * self.sample_rate)
                while self._held and self._held_len - len(self._held[0]) >= keep:
                    self._held_len -= len(self._held.popleft())
        if self._recording:
            self.level = float(np.sqrt(np.mean(indata ** 2)))
            self.chunks += 1
            self.last_chunk = time.monotonic()
            self.peak = max(self.peak, float(np.max(np.abs(indata))))

    def lingering(self):
        """True while a stream is open between dictations."""
        return self._stream is not None and not self._recording

    def _active(self):
        """Is the open stream still delivering audio? False when the
        device has gone (PortAudio then raises instead of answering)."""
        try:
            return bool(self._stream is not None and self._stream.active)
        except Exception:
            return False

    def start(self):
        self.chunks, self.last_chunk, self.peak = 0, time.monotonic(), 0.0
        with PA_LOCK:
            if self.lingering() and self._stream_device == self.device:
                self._cancel_close()
                with self._lock:
                    self._frames = list(self._held)
                    self._held.clear()
                    self._held_len = 0
                    self._recording = True
                if self._active():
                    return
            self._close_now()
            self._frames = []
            self._recording = True
            self._stream = sd.InputStream(
                samplerate=self.sample_rate,
                channels=self.channels,
                dtype="float32",
                device=self.device,
                callback=self._callback,
            )
            self._stream_device = self.device
            self._stream.start()

    def _cancel_close(self):
        if self._close_timer is not None:
            self._close_timer.cancel()
            self._close_timer = None

    def _close_now(self):
        """Close any open stream; never raises (see stop())."""
        self._cancel_close()
        stream, self._stream = self._stream, None
        with self._lock:
            self._recording = False
            self._held.clear()
            self._held_len = 0
        if stream is None:
            return
        with PA_LOCK:
            try:
                stream.stop()
            except Exception:
                pass
            try:
                stream.close()
            except Exception:
                pass

    def _close_if_lingering(self):
        with PA_LOCK:
            if self.lingering():
                self._close_now()

    def close(self):
        """Close the stream now (quitting, or a lingering one not wanted)."""
        with PA_LOCK:
            self._close_now()

    def reset(self):
        """Restart PortAudio so it re-reads the device list -- after sleep
        the microphone it knew may have disappeared or been renumbered.
        Only when no stream is open; failures are ignored (the next
        start() reports a real problem itself). True if it restarted.
        A chosen microphone (self.device) is found again by name, since
        restarting can renumber the list; if it's gone, self.device
        becomes None (the Windows default)."""
        with PA_LOCK:
            if self.lingering():
                self._close_now()
            if self._stream is not None:
                return False
            chosen = None
            if self.device is not None:
                try:
                    info = sd.query_devices(self.device)
                    chosen = (info["name"], info["hostapi"])
                except Exception:
                    pass
            try:
                sd._terminate()
                sd._initialize()
            except Exception:
                return False
            if chosen is not None:
                self.device = next(
                    (i for i, d in enumerate(sd.query_devices())
                     if (d["name"], d["hostapi"]) == chosen
                     and d.get("max_input_channels", 0) > 0),
                    None,
                )
            return True

    def stop(self, linger=0.0):
        """The recording so far. With `linger` (seconds) and a preroll set,
        the stream stays open that long for a quick re-press."""
        if self._stream is None or not self._recording:
            return np.array([], dtype="float32")

        with self._lock:
            frames, self._frames = self._frames, []
            self._recording = False
        self.level = 0.0

        if linger > 0 and self.preroll > 0 and self._active():
            with PA_LOCK:
                self._cancel_close()
                self._close_timer = threading.Timer(linger, self._close_if_lingering)
                self._close_timer.daemon = True
                self._close_timer.start()
        else:
            # The device can vanish mid-recording (Bluetooth headset
            # dropping, USB mic unplugged) and stop() then raises. That used
            # to escape into the hotkey listener and end dictation until a
            # restart; _close_now() keeps whatever was captured instead.
            self.close()

        if not frames:
            return np.array([], dtype="float32")

        return np.concatenate(frames, axis=0).flatten()
