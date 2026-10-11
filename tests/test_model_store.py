"""Tests for parakeet_cage.model_store"""
import hashlib
from pathlib import Path
import urllib.request

import pytest

from parakeet_cage import model_store


def _sparse(path: Path, size: int) -> Path:
    """A file of exactly `size` bytes that costs no disk space."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as handle:
        handle.truncate(size)
    return path


def _full_weights(directory: Path) -> Path:
    """A directory that passes the size checks of the real pinned manifest."""
    for spec in model_store.MODEL_FILES:
        _sparse(directory / spec.name, spec.size)
    return directory


LFS_POINTER = (
    "version https://git-lfs.github.com/spec/v1\n"
    "oid sha256:78ec25733ee0d0c1586d1346fc86db9d0c2e436e3a8ab1d32a82d1bb8f848d21\n"
    "size 177774490\n"
)

SPECS = (
    model_store.ModelFile("a.bin", 11, hashlib.sha256(b"hello world").hexdigest()),
    model_store.ModelFile("b.bin", 4, hashlib.sha256(b"abcd").hexdigest()),
)


def test_check_weights_ok_on_pinned_sizes(tmp_path):
    check = model_store.check_weights(_full_weights(tmp_path / "w"))
    assert check.ok and check.status == model_store.OK
    assert "2bf1286" in check.detail


def test_check_weights_missing_directory(tmp_path):
    assert model_store.check_weights(tmp_path / "nope").status == model_store.MISSING


def test_check_weights_missing_file(tmp_path):
    directory = _full_weights(tmp_path / "w")
    (directory / "tokenizer.json").unlink()
    check = model_store.check_weights(directory)
    assert check.status == model_store.MISSING
    assert "tokenizer.json" in check.detail


def test_check_weights_detects_lfs_pointer(tmp_path):
    directory = _full_weights(tmp_path / "w")
    (directory / "model.safetensors").write_text(LFS_POINTER)
    check = model_store.check_weights(directory)
    assert check.status == model_store.POINTER
    assert "git-lfs pointer" in check.detail
    assert "git lfs pull" in check.detail


def test_check_weights_detects_truncated_file(tmp_path):
    directory = _full_weights(tmp_path / "w")
    _sparse(directory / "model.safetensors", 4096)
    check = model_store.check_weights(directory)
    assert check.status == model_store.CORRUPT
    assert "expected 177774490 B" in check.detail


def test_is_lfs_pointer_ignores_real_and_unreadable_files(tmp_path):
    real = _sparse(tmp_path / "model.safetensors", 177774490)
    assert model_store.is_lfs_pointer(real) is False
    assert model_store.is_lfs_pointer(tmp_path / "absent") is False


def _source(tmp_path: Path, contents: dict) -> Path:
    root = tmp_path / "source"
    root.mkdir(parents=True, exist_ok=True)
    for name, payload in contents.items():
        (root / name).write_bytes(payload)
    return root


def test_fetch_model_installs_and_verifies(tmp_path):
    source = _source(tmp_path, {"a.bin": b"hello world", "b.bin": b"abcd"})
    dest = tmp_path / "dest"
    progress = []
    model_store.fetch_model(
        dest,
        files=SPECS,
        base_url=f"file://{source}",
        on_progress=lambda name, done, total: progress.append((name, done, total)),
    )
    assert (dest / "a.bin").read_bytes() == b"hello world"
    assert (dest / "b.bin").read_bytes() == b"abcd"
    assert ("a.bin", 11, 11) in progress
    assert not list(dest.glob("*.part"))


def test_fetch_model_skips_files_that_already_match(tmp_path):
    source = _source(tmp_path, {"a.bin": b"hello world", "b.bin": b"abcd"})
    dest = tmp_path / "dest"
    calls = []

    def counting_opener(url, timeout=None):
        calls.append(url)
        return urllib.request.urlopen(url, timeout=timeout)

    model_store.fetch_model(dest, files=SPECS, base_url=f"file://{source}", opener=counting_opener)
    assert len(calls) == 2
    calls.clear()
    model_store.fetch_model(dest, files=SPECS, base_url=f"file://{source}", opener=counting_opener)
    assert calls == []


def test_fetch_model_rejects_hash_mismatch_and_keeps_nothing(tmp_path):
    source = _source(tmp_path, {"a.bin": b"hello world"})
    wrong = (model_store.ModelFile("a.bin", 11, hashlib.sha256(b"different").hexdigest()),)
    dest = tmp_path / "dest"
    with pytest.raises(model_store.ModelFetchError) as excinfo:
        model_store.fetch_model(dest, files=wrong, base_url=f"file://{source}")
    assert "sha256" in str(excinfo.value)
    assert not (dest / "a.bin").exists()
    assert not list(dest.glob("*.part"))


def test_fetch_model_rejects_oversized_body(tmp_path):
    source = _source(tmp_path, {"a.bin": b"hello world plus more"})
    spec = (model_store.ModelFile("a.bin", 11, hashlib.sha256(b"hello world").hexdigest()),)
    dest = tmp_path / "dest"
    with pytest.raises(model_store.ModelFetchError) as excinfo:
        model_store.fetch_model(dest, files=spec, base_url=f"file://{source}")
    assert "more than the expected" in str(excinfo.value)
    assert not (dest / "a.bin").exists()


def test_fetch_model_reports_missing_source(tmp_path):
    dest = tmp_path / "dest"
    with pytest.raises(model_store.ModelFetchError) as excinfo:
        model_store.fetch_model(dest, files=SPECS, base_url=f"file://{tmp_path / 'absent'}")
    assert "a.bin" in str(excinfo.value)


def test_fetch_model_replaces_a_corrupt_existing_file(tmp_path):
    source = _source(tmp_path, {"a.bin": b"hello world"})
    dest = tmp_path / "dest"
    _sparse(dest / "a.bin", 3)
    model_store.fetch_model(dest, files=SPECS[:1], base_url=f"file://{source}")
    assert (dest / "a.bin").read_bytes() == b"hello world"


def test_user_model_dir_follows_xdg_data_home(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    assert model_store.user_model_dir() == tmp_path / "parakeet-cage" / "models" / "parakeet-redux"


def test_hf_cache_dir_uses_the_pinned_revision(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    path = model_store.hf_cache_dir()
    assert "models--moondream--parakeet-redux" in str(path)
    assert path.name == model_store.MODEL_REVISION
