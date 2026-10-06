"""ASR wrapper around moondream/parakeet-redux."""

import logging
import tempfile
import wave

import numpy as np

logger = logging.getLogger(__name__)


class Transcriber:
    """Wraps the moondream photon ASR model."""

    def __init__(self):
        self._speech = None

    def load(self, model_path: str, device: str = "cpu") -> None:
        """Load the model via moondream.photon()."""
        import moondream as md
        self._speech = md.photon(model_path, device=device)
        # Keep the context manager open for the lifetime of the process.
        self._speech.__enter__()

    def transcribe(self, audio: bytes) -> str:
        """Convert raw PCM (16-bit mono 16kHz) to a temp WAV and transcribe."""
        if self._speech is None:
            return ""
        wav_bytes = self._pcm_to_wav(audio)
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(wav_bytes)
            tmp_path = f.name
        result = self._speech.transcribe(audio=tmp_path)
        return result["text"]

    @property
    def ready(self) -> bool:
        return self._speech is not None

    def _pcm_to_wav(self, pcm: bytes) -> bytes:
        """Convert raw 16-bit mono PCM to a complete WAV file."""
        import io
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(16000)
            w.writeframes(pcm)
        return buf.getvalue()
