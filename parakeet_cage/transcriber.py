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
from typing import Any, List, Optional

import torch

from parakeet_cage import model_store

# Complete isolation from all remote services
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["MOONDREAM_DISABLE_TELEMETRY"] = "1"

warnings.filterwarnings("ignore")
logging.getLogger("huggingface_hub").setLevel(logging.ERROR)
logging.getLogger("kestrel").setLevel(logging.ERROR)
logging.getLogger("httpx").setLevel(logging.ERROR)

logger = logging.getLogger(__name__)


def default_search_paths() -> List[Path]:
    """Search order for the weights: the clone first, then per-user storage."""
    return [
        Path(__file__).resolve().parent.parent / "models" / "parakeet-redux",
        model_store.user_model_dir(),
        model_store.hf_cache_dir(),
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
    """Find the local directory holding the verified Parakeet Redux weights.

    Existence is not enough: a git-lfs pointer stub or a truncated file is
    rejected, so a broken copy can never shadow a usable directory later in the
    search order. Verification is by size only - hashing runs when downloading.
    """
    candidates: List[Path] = []
    if custom_path:
        candidates.append(Path(custom_path))
    candidates.extend(default_search_paths())

    seen = set()
    rejected = []
    for p in candidates:
        key = str(p)
        if key in seen:
            continue
        seen.add(key)
        check = model_store.check_weights(p)
        if check.ok:
            return p.resolve()
        rejected.append(f"  {check.detail}")

    raise FileNotFoundError(
        "Parakeet Redux weights are not installed.\n"
        + "\n".join(rejected)
        + "\n"
        + model_store.WEIGHTS_HINT
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
