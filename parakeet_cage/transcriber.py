"""ASR wrapper around local Parakeet Redux model weights.

Loads weights directly from the project's local 'models/parakeet-redux' directory
or system storage with zero remote network calls, zero HuggingFace snapshot checks,
and zero telemetry.
"""

from dataclasses import dataclass
import io
import logging
import os
from pathlib import Path
import tempfile
import warnings
import wave
from typing import Any, Optional

import torch

# Complete isolation from all remote services
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["MOONDREAM_DISABLE_TELEMETRY"] = "1"

warnings.filterwarnings("ignore")
logging.getLogger("huggingface_hub").setLevel(logging.ERROR)
logging.getLogger("kestrel").setLevel(logging.ERROR)
logging.getLogger("httpx").setLevel(logging.ERROR)

logger = logging.getLogger(__name__)

# Search order for local weights (project folder first, then local user share)
DEFAULT_SEARCH_PATHS = [
    Path(__file__).resolve().parent.parent / "models" / "parakeet-redux",
    Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "parakeet-cage" / "models" / "parakeet-redux",
    Path.home() / ".cache" / "huggingface" / "hub" / "models--moondream--parakeet-redux" / "snapshots" / "2bf128600aac4b16946f7ed8372e56117fe5e23b",
]


@dataclass
class LocalRuntimeConfig:
    """Configures the local Parakeet TDT runtime without any network scaffolding."""
    model: str = "moondream/parakeet-redux"
    device: str = "cpu"
    dtype: torch.dtype = torch.float32
    single_pass_batch_capacity: int = 8
    model_path: Path = Path(".")
    service_name: str = "parakeet-cage"

    def resolved_device(self) -> torch.device:
        return torch.device(self.device)

    def resolved_dtype(self) -> torch.dtype:
        return self.dtype


def resolve_local_model_path(custom_path: Optional[str] = None) -> Path:
    """Find the local directory containing model.safetensors and config.json."""
    candidates = []
    if custom_path:
        candidates.append(Path(custom_path))
    candidates.extend(DEFAULT_SEARCH_PATHS)

    for p in candidates:
        if p.exists() and (p / "model.safetensors").exists() and (p / "config.json").exists():
            return p.resolve()

    raise FileNotFoundError(
        f"Local model weights not found in any standard location: {[str(p) for p in candidates]}"
    )


class Transcriber:
    """Wraps the local Parakeet TDT ASR engine for pure offline inference."""

    def __init__(self):
        self._runtime = None

    def load(self, model_path: Optional[str] = None, device: str = "cpu") -> None:
        """Instantiate the ASR runtime directly from local disk files."""
        weights_dir = resolve_local_model_path(model_path)
        logger.info("Loading Parakeet model directly from local directory: %s", weights_dir)

        import kestrel.models.registry as reg

        spec = reg.get_spec("moondream/parakeet-redux")
        cfg = LocalRuntimeConfig(
            model="moondream/parakeet-redux",
            device=device,
            model_path=weights_dir,
        )
        self._runtime = spec.runtime(cfg)
        logger.info("Parakeet ASR engine initialized offline.")

    def transcribe(self, audio: bytes) -> str:
        """Transcribe raw PCM (16-bit mono 16kHz) to text directly in-memory."""
        if self._runtime is None or not audio:
            return ""

        wav_bytes = self._pcm_to_wav(audio)
        try:
            results = self._runtime.forward("transcribe", [{"audio": wav_bytes}])
            if results and isinstance(results, (tuple, list)):
                first = results[0]
                if isinstance(first, dict):
                    return first.get("text", "").strip()
                if hasattr(first, "text"):
                    return first.text.strip()
            return ""
        except Exception as e:
            logger.error("Inference failed: %s", e)
            return ""

    @property
    def ready(self) -> bool:
        return self._runtime is not None

    def _pcm_to_wav(self, pcm: bytes) -> bytes:
        """Convert raw 16-bit mono PCM to standard RIFF WAV in memory."""
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(16000)
            w.writeframes(pcm)
        return buf.getvalue()
