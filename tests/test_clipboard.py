"""Tests for parakeet_cage.clipboard"""
import subprocess

import pytest

from parakeet_cage.clipboard import PasteError, detect_display, paste_text


def test_detect_display_returns_valid_value():
    assert detect_display() in ("x11", "wayland")


@pytest.mark.skipif(
    not subprocess.run(["which", "xclip"]).returncode == 0,
    reason="xclip not available (no X11 session)",
)
def test_paste_text_writes_to_clipboard():
    """On X11: xclip -i then xclip -o returns same text."""
    paste_text("hello world")
    out = subprocess.check_output(["xclip", "-o"])
    assert out.decode().strip() == "hello world"


def test_paste_text_signature():
    """Verify paste_text has the correct signature."""
    import inspect
    sig = inspect.signature(paste_text)
    assert "text" in sig.parameters
