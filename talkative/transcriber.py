from faster_whisper import WhisperModel


class Transcriber:
    """Thin wrapper around faster-whisper for one-shot transcription of a
    single in-memory audio buffer (not streaming)."""

    def __init__(self, model_size="base.en", device="cpu", compute_type="int8",
                 download_root=None):
        self.model = WhisperModel(
            model_size, device=device, compute_type=compute_type,
            download_root=download_root,
        )
        self._language = "en" if model_size.endswith(".en") else None

    def transcribe(self, audio, sample_rate=16000, initial_prompt=None):
        if audio is None or audio.size == 0:
            return ""

        segments, _ = self.model.transcribe(
            audio,
            language=self._language,
            vad_filter=True,
            initial_prompt=initial_prompt,
        )
        return "".join(segment.text for segment in segments).strip()
