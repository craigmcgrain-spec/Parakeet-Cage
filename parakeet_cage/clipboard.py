"""Clipboard write + paste keystroke injection."""

import logging
import os
import subprocess

logger = logging.getLogger(__name__)


class PasteError(Exception):
    """Raised when clipboard or paste keystroke fails."""


def detect_display() -> str:
    """Read $XDG_SESSION_TYPE. Default 'x11' if unset."""
    session_type = os.environ.get("XDG_SESSION_TYPE", "").lower()
    if session_type == "wayland":
        return "wayland"
    return "x11"


def paste_text(text: str) -> None:
    """Write text to clipboard, then send ctrl+v.

    X11: xclip -i + xdotool key ctrl+v
    Wayland: wl-paste -i + wtype key ctrl v
    Raises PasteError if any step fails.
    """
    display = detect_display()
    try:
        if display == "x11":
            _write_clipboard_x11(text)
            _send_paste_x11()
        else:
            _write_clipboard_wayland(text)
            _send_paste_wayland()
    except Exception as e:
        raise PasteError(f"Clipboard/paste failed: {e}") from e


def _write_clipboard_x11(text: str) -> None:
    subprocess.run(
        ["xclip", "-i"],
        input=text.encode(),
        check=True,
        capture_output=True,
    )


def _send_paste_x11() -> None:
    subprocess.run(
        ["xdotool", "key", "ctrl+v"],
        check=True,
        capture_output=True,
    )


def _write_clipboard_wayland(text: str) -> None:
    subprocess.run(
        ["wl-paste", "-i"],
        input=text.encode(),
        check=True,
        capture_output=True,
    )


def _send_paste_wayland() -> None:
    subprocess.run(
        ["wtype", "key", "ctrl", "v"],
        check=True,
        capture_output=True,
    )
