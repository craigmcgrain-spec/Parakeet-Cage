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


def _weights(tmp_path, *, truncate_safetensors_to=None, pointer=False):
    """A weights directory whose files have the pinned sizes, or a broken variant."""
    from parakeet_cage import model_store

    directory = tmp_path / "weights"
    directory.mkdir(parents=True, exist_ok=True)
    for spec in model_store.MODEL_FILES:
        size = spec.size
        if spec.name == "model.safetensors" and truncate_safetensors_to is not None:
            size = truncate_safetensors_to
        with open(directory / spec.name, "wb") as handle:
            handle.truncate(size)
    if pointer:
        (directory / "model.safetensors").write_text(
            "version https://git-lfs.github.com/spec/v1\n"
            "oid sha256:78ec25733ee0d0c1586d1346fc86db9d0c2e436e3a8ab1d32a82d1bb8f848d21\n"
            "size 177774490\n"
        )
    return directory


def test_resolver_accepts_a_verified_directory(tmp_path, monkeypatch):
    from parakeet_cage import transcriber

    monkeypatch.setattr(transcriber, "default_search_paths", lambda: [])
    directory = _weights(tmp_path)
    assert transcriber.resolve_local_model_path(str(directory)) == directory.resolve()


def test_resolver_rejects_a_git_lfs_pointer(tmp_path, monkeypatch):
    from parakeet_cage import transcriber

    monkeypatch.setattr(transcriber, "default_search_paths", lambda: [])
    directory = _weights(tmp_path, pointer=True)
    with pytest.raises(FileNotFoundError) as excinfo:
        transcriber.resolve_local_model_path(str(directory))
    message = str(excinfo.value)
    assert "git-lfs pointer" in message
    assert "git lfs pull" in message
    assert "./install.sh" in message and "parakeet-cage --fetch-model" in message


def test_resolver_rejects_a_truncated_file(tmp_path, monkeypatch):
    from parakeet_cage import transcriber

    monkeypatch.setattr(transcriber, "default_search_paths", lambda: [])
    directory = _weights(tmp_path, truncate_safetensors_to=4096)
    with pytest.raises(FileNotFoundError) as excinfo:
        transcriber.resolve_local_model_path(str(directory))
    message = str(excinfo.value)
    assert "expected 177774490 B" in message


def test_resolver_skips_invalid_earlier_candidates(tmp_path, monkeypatch):
    """A broken clone path must not shadow the usable user-data copy."""
    from parakeet_cage import transcriber

    broken = _weights(tmp_path / "clone", pointer=True)
    good = _weights(tmp_path / "user")
    monkeypatch.setattr(transcriber, "default_search_paths", lambda: [broken, good])
    assert transcriber.resolve_local_model_path() == good.resolve()
