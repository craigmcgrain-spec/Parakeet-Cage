"""Tests for parakeet_cage.transcriber"""
import struct

import pytest


def _make_pcm_bytes(duration_s: float = 0.5, sample_rate: int = 16000) -> bytes:
    """Create raw 16-bit mono PCM silence."""
    n_samples = int(sample_rate * duration_s)
    return b"\x00\x00" * n_samples


def test_transcriber_initial_not_ready():
    from parakeet_cage.transcriber import Transcriber
    t = Transcriber()
    assert t.ready is False


def test_transcriber_loads_model():
    from parakeet_cage.transcriber import Transcriber
    t = Transcriber()
    t.load(model_path="moondream/parakeet-redux")
    assert t.ready is True


def test_transcribe_returns_string():
    from parakeet_cage.transcriber import Transcriber
    t = Transcriber()
    t.load(model_path="moondream/parakeet-redux")
    audio = _make_pcm_bytes(0.5)
    result = t.transcribe(audio)
    assert isinstance(result, str)
