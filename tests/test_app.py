"""Tests for parakeet_cage.app."""

import time
from unittest.mock import MagicMock, PropertyMock, patch

import pytest

from parakeet_cage.app import Application
from parakeet_cage.config import Config


def test_app_initialization():
    cfg = Config(record_hotkey="ctrl+space")
    app = Application(config=cfg)
    assert app.config.record_hotkey == "ctrl+space"
    assert not app.recorder.is_recording
    assert not app.transcriber.ready


@patch("parakeet_cage.app.paste_text")
def test_audio_pipeline_execution(mock_paste):
    app = Application(config=Config())
    # Mock transcriber ready and transcribe
    with patch.object(type(app.transcriber), "ready", new_callable=PropertyMock) as mock_ready:
        mock_ready.return_value = True
        app.transcriber.transcribe = MagicMock(return_value="hello world")
        app.recorder.stop = MagicMock(return_value=b"\x00\x00" * 16000)
        app._on_stop_record()

        time.sleep(0.2)
        app.transcriber.transcribe.assert_called_once()
        mock_paste.assert_called_once_with("hello world")
