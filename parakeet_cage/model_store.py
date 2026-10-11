"""Pinned Parakeet Redux weights: verification, location and one-shot download.

The application never fetches anything while running. This module is imported by
the CLI installer (`parakeet_cage.install`) and by `parakeet-cage --fetch-model`;
`transcriber.resolve_local_model_path` reuses the same predicates so a git-lfs
pointer or a truncated file can never be mistaken for usable weights.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Callable, NamedTuple, Optional, Sequence, Tuple
import urllib.error
import urllib.request


MODEL_REPO = "moondream/parakeet-redux"
# Pinned revision: the weights this version of the app was tested against. The
# installer and --fetch-model download exactly this revision, and verify every
# size and sha256 below before the files are moved into place.
MODEL_REVISION = "2bf128600aac4b16946f7ed8372e56117fe5e23b"
MODEL_DIR_NAME = "parakeet-redux"
DEFAULT_BASE_URL = f"https://huggingface.co/{MODEL_REPO}/resolve/{MODEL_REVISION}"

OK, MISSING, POINTER, CORRUPT = "ok", "missing", "pointer", "corrupt"

_LFS_POINTER_PREFIX = b"version https://git-lfs.github.com/spec/v1"
_POINTER_PROBE = 128

# Printed when the weights are absent: every sanctioned way to get them.
WEIGHTS_HINT = (
    "Install the weights once with any of:\n"
    "  ./install.sh                        (from a git clone; it asks first)\n"
    "  git lfs install && git lfs pull     (if git-lfs is installed)\n"
    "  parakeet-cage --fetch-model         (~178 MB download, sha256-verified)"
)


class ModelFile(NamedTuple):
    """One file of the pinned revision: name, exact size in bytes, sha256."""

    name: str
    size: int
    sha256: str


# sha256 of each file at MODEL_REVISION; identical to the copies tracked in git.
MODEL_FILES: Tuple[ModelFile, ...] = (
    ModelFile("config.json", 12988, "503c653b2e3bb788adbcb04f5abdee532d958686564081baeed133ff10143f6e"),
    ModelFile("model.safetensors", 177774490, "78ec25733ee0d0c1586d1346fc86db9d0c2e436e3a8ab1d32a82d1bb8f848d21"),
    ModelFile("ternary.json", 57970, "1221c6d3ce901ffe09c089da758a8db8b76189f80cff41c5afc244fc61e2051d"),
    ModelFile("tokenizer.json", 1159960, "bd321b096832a3f270bd3b2a88823957920f1a5c5ada71114a26ea729d0cbe91"),
)


class ModelFetchError(RuntimeError):
    """A download failed, or the bytes did not match the pinned size and sha256."""


class Check(NamedTuple):
    """Verdict for one candidate weights directory."""

    status: str
    detail: str

    @property
    def ok(self) -> bool:
        return self.status == OK


def user_model_dir() -> Path:
    """Where --fetch-model installs: search path #2, valid for every install mode."""
    root = os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share"
    return Path(root) / "parakeet-cage" / "models" / MODEL_DIR_NAME


def hf_cache_dir() -> Path:
    """A pre-existing HuggingFace snapshot, if the user had one before this app."""
    hub = Path.home() / ".cache" / "huggingface" / "hub"
    return hub / f"models--{MODEL_REPO.replace('/', '--')}" / "snapshots" / MODEL_REVISION


def is_lfs_pointer(path) -> bool:
    """True when `path` holds a git-lfs pointer stub instead of the real file."""
    try:
        with open(path, "rb") as fh:
            return fh.read(_POINTER_PROBE).startswith(_LFS_POINTER_PREFIX)
    except OSError:
        return False


def _size_ok(path: Path, spec: ModelFile) -> bool:
    try:
        return path.is_file() and path.stat().st_size == spec.size
    except OSError:
        return False


def check_weights(directory) -> Check:
    """Classify a weights directory by size only; hashing happens on download."""
    directory = Path(directory)
    if not directory.is_dir():
        return Check(MISSING, f"{directory}: no such directory")
    for spec in MODEL_FILES:
        path = directory / spec.name
        if not path.is_file():
            return Check(MISSING, f"{path}: missing")
        try:
            size = path.stat().st_size
        except OSError as exc:
            return Check(CORRUPT, f"{path}: unreadable ({exc})")
        if size == spec.size:
            continue
        if is_lfs_pointer(path):
            return Check(
                POINTER,
                f"{path}: git-lfs pointer ({size} B), not the weights"
                " - run 'git lfs install && git lfs pull' in the clone",
            )
        return Check(CORRUPT, f"{path}: {size} B, expected {spec.size} B")
    return Check(OK, f"{directory}: {MODEL_REPO}@{MODEL_REVISION[:7]}")


def weights_status(directory) -> str:
    """Just the status of `check_weights(directory)`."""
    return check_weights(directory).status


def print_progress(name: str, written: int, total: int) -> None:
    """Progress callback for `fetch_model`: one rewriting line per file."""
    percent = 100.0 * written / total if total else 100.0
    print(
        f"    {name:<20} {percent:5.1f}%  {written / 1e6:6.1f}/{total / 1e6:.1f} MB",
        end="\n" if written >= total else "\r",
        flush=True,
    )


def fetch_model(
    dest,
    *,
    files: Sequence[ModelFile] = MODEL_FILES,
    base_url: str = DEFAULT_BASE_URL,
    opener: Optional[Callable[..., object]] = None,
    on_progress: Optional[Callable[[str, int, int], None]] = None,
) -> Path:
    """Install the pinned revision into `dest`, verifying size and sha256 per file.

    Files that already match are skipped, so re-running is cheap and an
    interrupted download resumes at file granularity. Nothing is moved into place
    until a file has been fully downloaded and verified.
    """
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    for spec in files:
        target = dest / spec.name
        if _size_ok(target, spec):
            continue
        _download_file(f"{base_url.rstrip('/')}/{spec.name}", target, spec, opener=opener, on_progress=on_progress)
    return dest


def _download_file(url, target: Path, spec: ModelFile, *, opener, on_progress) -> None:
    opener = opener or urllib.request.urlopen
    part = target.with_name(target.name + ".part")
    digest = hashlib.sha256()
    written = 0
    try:
        with opener(url, timeout=60) as response, open(part, "wb") as out:
            while True:
                chunk = response.read(4 << 20)
                if not chunk:
                    break
                out.write(chunk)
                digest.update(chunk)
                written += len(chunk)
                if written > spec.size:
                    raise ModelFetchError(f"{url}: more than the expected {spec.size} B")
                if on_progress is not None:
                    on_progress(spec.name, written, spec.size)
    except (OSError, urllib.error.URLError) as exc:
        part.unlink(missing_ok=True)
        raise ModelFetchError(f"{url}: {exc}") from exc
    except ModelFetchError:
        part.unlink(missing_ok=True)
        raise
    if written != spec.size or digest.hexdigest() != spec.sha256:
        part.unlink(missing_ok=True)
        raise ModelFetchError(
            f"{url}: got {written} B sha256 {digest.hexdigest()[:16]}...;"
            f" expected {spec.size} B sha256 {spec.sha256[:16]}..."
        )
    os.replace(part, target)
