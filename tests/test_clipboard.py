"""Tests for parakeet_cage.clipboard."""

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from parakeet_cage.clipboard import PasteError, copy_to_clipboard, paste_text


def test_copy_to_clipboard_wl_copy():
    with patch("shutil.which") as mock_which, patch("subprocess.Popen") as mock_popen:
        mock_which.side_effect = lambda cmd: "/usr/bin/wl-copy" if cmd == "wl-copy" else None
        proc = MagicMock()
        proc.returncode = 0
        proc.communicate.return_value = (b"", b"")
        mock_popen.return_value = proc

        copy_to_clipboard("hello world")
        mock_popen.assert_called_once()
        args, kwargs = mock_popen.call_args
        assert args[0] == ["wl-copy"]


def test_copy_to_clipboard_xclip_fallback():
    with patch("shutil.which") as mock_which, patch("subprocess.Popen") as mock_popen:
        mock_which.side_effect = lambda cmd: "/usr/bin/xclip" if cmd == "xclip" else None
        proc = MagicMock()
        proc.returncode = 0
        proc.communicate.return_value = (b"", b"")
        mock_popen.return_value = proc

        copy_to_clipboard("hello x11")
        mock_popen.assert_called_once()
        args, kwargs = mock_popen.call_args
        assert args[0] == ["xclip", "-selection", "clipboard"]


def test_paste_text_calls_copy():
    with patch("parakeet_cage.clipboard.copy_to_clipboard") as mock_copy, \
         patch("parakeet_cage.clipboard.trigger_paste_keystroke") as mock_trigger:
        paste_text("test transcription")
        mock_copy.assert_called_once_with("test transcription")
        mock_trigger.assert_called_once()
