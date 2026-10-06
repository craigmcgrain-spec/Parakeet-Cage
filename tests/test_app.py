"""Tests for parakeet_cage.app / main wiring."""

from unittest.mock import MagicMock, patch
from pathlib import Path

from parakeet_cage.app import Application
from parakeet_cage.config import Config


def test_application_initialization():
    cfg = Config()
    app = Application(config=cfg)
    assert app.config == cfg
    assert app.state_machine is not None
    assert app.recorder is not None
    assert app.transcriber is not None


@patch("parakeet_cage.app.paste_text")
def test_audio_pipeline_execution(mock_paste):
    app = Application(config=Config())
    # Mock transcriber output
    app.transcriber.transcribe = MagicMock(return_value="hello world")
    app.recorder.stop = MagicMock(return_value=b"\x00\x00" * 16000)

    app._on_stop_record()

    app.transcriber.transcribe.assert_called_once()
    mock_paste.assert_called_once_with("hello world")
