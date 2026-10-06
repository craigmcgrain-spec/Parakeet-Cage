"""ASR wrapper around moondream/parakeet-redux with local offline caching."""

import logging
import os
from pathlib import Path
import tempfile
import warnings
import wave

# Suppress harmless HuggingFace anonymous rate limit warnings
warnings.filterwarnings("ignore", message=".*unauthenticated requests.*")
logging.getLogger("huggingface_hub").setLevel(logging.ERROR)

logger = logging.getLogger(__name__)

# Dedicated local cache directory for the application
DEFAULT_LOCAL_CACHE = Path(
    os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")
) / "parakeet-cage" / "hf_cache"


def is_model_already_cached(model_identifier: str) -> bool:
    """Check if model snapshot already exists in our dedicated cache."""
    normalized_name = f"models--{model_identifier.replace('/', '--')}"
    model_dir = DEFAULT_LOCAL_CACHE / "hub" / normalized_name / "snapshots"
    if model_dir.exists():
        snapshots = [s for s in model_dir.iterdir() if s.is_dir()]
        if snapshots:
            return True
    return False


def ensure_local_model_cached(model_identifier: str = "moondream/parakeet-redux") -> None:
    """Download model files once if not already present in dedicated cache."""
    if os.path.isdir(model_identifier) or os.path.isfile(model_identifier):
        return

    DEFAULT_LOCAL_CACHE.mkdir(parents=True, exist_ok=True)
    os.environ["HF_HOME"] = str(DEFAULT_LOCAL_CACHE)

    # If already cached locally, do not hit the remote HF Hub at all
    if is_model_already_cached(model_identifier):
        logger.info("Model '%s' is already stored locally. Running offline.", model_identifier)
        return

    try:
        from huggingface_hub import snapshot_download
        logger.info("Downloading model '%s' for offline use into %s...", model_identifier, DEFAULT_LOCAL_CACHE)
        snapshot_download(
            repo_id=model_identifier,
            cache_dir=str(DEFAULT_LOCAL_CACHE),
            local_files_only=False,
        )
    except Exception as e:
        logger.warning("Could not pre-cache model: %s", e)


class Transcriber:
    """Wraps the moondream photon ASR model running strictly locally."""

    def __init__(self):
        self._speech = None

    def load(self, model_path: str = "moondream/parakeet-redux", device: str = "cpu") -> None:
        """Load the model via moondream.photon() using local cache."""
        model_name = model_path or "moondream/parakeet-redux"

        # 1. Download once if not already cached
        ensure_local_model_cached(model_name)

        # 2. Configure Hugging Face to run purely offline from local cache
        os.environ["HF_HOME"] = str(DEFAULT_LOCAL_CACHE)
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"

        logger.info("Loading speech model '%s' offline from local storage...", model_name)
        import moondream as md

        self._speech = md.photon(model_name, device=device)
        self._speech.__enter__()
        logger.info("Speech model '%s' loaded and ready.", model_name)

    def transcribe(self, audio: bytes) -> str:
        """Convert raw PCM (16-bit mono 16kHz) to a temp WAV and transcribe."""
        if self._speech is None:
            return ""
        wav_bytes = self._pcm_to_wav(audio)
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(wav_bytes)
            tmp_path = f.name
        try:
            result = self._speech.transcribe(audio=tmp_path)
            return result.get("text", "") if isinstance(result, dict) else str(result)
        finally:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass

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
