import numpy as np
from faster_whisper import WhisperModel

from . import config, hardware


class Transcriber:
    """Thin wrapper around faster-whisper for one-shot transcription of a
    single in-memory audio buffer (not streaming).

    Sized to the PC: an NVIDIA GPU when CTranslate2 can see one (with a
    real test transcription at load -- missing CUDA libraries often only
    fail on first use -- and the CPU as fallback), otherwise one thread per
    physical core (hardware.cpu_threads())."""

    def __init__(self, model_size="base.en", device="cpu", compute_type="int8",
                 download_root=None):
        options = [(device, compute_type, {"cpu_threads": hardware.cpu_threads()})]
        if config.USE_GPU and device == "cpu" and hardware.cuda_devices():
            options.insert(0, ("cuda", "int8_float16", {}))
        error = None
        for dev, compute, extra in options:
            try:
                model = WhisperModel(model_size, device=dev, compute_type=compute,
                                     download_root=download_root, **extra)
                # Half a second of silence, VAD off: exercises the whole
                # model on this device without depending on speech.
                list(model.transcribe(np.zeros(8000, dtype=np.float32), language="en",
                                      vad_filter=False, beam_size=1)[0])
            except Exception as exc:
                error = exc
                continue
            self.model, self.device = model, dev
            break
        else:
            raise error
        self._language = "en" if model_size.endswith(".en") else None

    def transcribe(self, audio, sample_rate=16000, initial_prompt=None):
        if audio is None or audio.size == 0:
            return ""

        segments, _ = self.model.transcribe(
            audio,
            language=self._language,
            vad_filter=True,
            initial_prompt=initial_prompt,
            beam_size=config.STT_BEAM_SIZE,
        )
        return "".join(segment.text for segment in segments).strip()
