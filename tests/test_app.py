"""Tests for parakeet_cage.app."""

import time
from unittest.mock import MagicMock, PropertyMock, patch

import pytest

import parakeet_cage
from parakeet_cage.app import Application, format_pending, main
from parakeet_cage.config import Config, TextConfig


def test_app_initialization(tmp_path):
    cfg = Config(record_hotkey="ctrl+space", text=TextConfig(lexicon_path=str(tmp_path / "lexicon.toml")))
    app = Application(config=cfg, config_path=tmp_path / "config.toml")
    assert app.config.record_hotkey == "ctrl+space"
    assert not app.recorder.is_recording
    assert not app.transcriber.ready


@patch("parakeet_cage.app.paste_text")
def test_audio_pipeline_execution(mock_paste, tmp_path):
    app = Application(
        config=Config(text=TextConfig(lexicon_path=str(tmp_path / "lexicon.toml"))),
        config_path=tmp_path / "config.toml",
    )
    # Mock transcriber ready and transcribe
    with patch.object(type(app.transcriber), "ready", new_callable=PropertyMock) as mock_ready:
        mock_ready.return_value = True
        app.transcriber.transcribe = MagicMock(return_value="hello world")
        app.recorder.stop = MagicMock(return_value=b"\x00\x00" * 16000)
        app._on_stop_record()

        time.sleep(0.2)
        app.transcriber.transcribe.assert_called_once()
        mock_paste.assert_called_once_with("hello world")


# --- transcript post-processing ----------------------------------------------


class _StubTranscriber:
    """Stands in for the ASR engine: instant answers, settable readiness."""

    def __init__(self, transcript: str):
        self.ready = True
        self.transcript = transcript

    def load(self, **_kwargs) -> None:
        self.ready = True

    def transcribe(self, _audio: bytes) -> str:
        return self.transcript


def _ready_app(tmp_path, transcript: str) -> Application:
    """An Application whose transcriber answers instantly with `transcript`."""
    cfg = Config(record_hotkey="f9", text=TextConfig(lexicon_path=str(tmp_path / "lexicon.toml")))
    app = Application(config=cfg, config_path=tmp_path / "config.toml")
    app.transcriber = _StubTranscriber(transcript)
    app.recorder.stop = MagicMock(return_value=b"\x00\x00" * 16000)
    return app


@patch("parakeet_cage.app.paste_text")
def test_transcript_is_post_processed_before_paste(mock_paste, tmp_path):
    (tmp_path / "lexicon.toml").write_text(
        'schema_version = 1\n\n[[word]]\nword = "kestrel"\naliases = ["castrell"]\n',
        encoding="utf-8",
    )
    app = _ready_app(tmp_path, "we use castrell comma right")

    app._on_stop_record()
    time.sleep(0.3)

    mock_paste.assert_called_once_with("we use kestrel, right")


@patch("parakeet_cage.app.paste_text")
def test_raw_transcript_is_pasted_when_post_processing_fails(mock_paste, tmp_path):
    app = _ready_app(tmp_path, "we use castrell")
    app.pipeline = MagicMock()
    app.pipeline.process.side_effect = RuntimeError("boom")

    app._on_stop_record()
    time.sleep(0.3)

    mock_paste.assert_called_once_with("we use castrell")


@patch("parakeet_cage.app.paste_text")
def test_undo_repastes_the_raw_transcript(mock_paste, tmp_path):
    (tmp_path / "lexicon.toml").write_text(
        'schema_version = 1\n\n[[word]]\nword = "kestrel"\naliases = ["castrell"]\n',
        encoding="utf-8",
    )
    app = _ready_app(tmp_path, "we use castrell today")

    app._on_stop_record()
    time.sleep(0.3)
    assert app.has_correction_to_undo() is True

    assert app.undo_last_correction() is True
    assert mock_paste.call_args_list[-1].args == ("we use castrell today",)
    assert app.has_correction_to_undo() is False


@patch("parakeet_cage.app.paste_text")
def test_undo_is_unavailable_when_nothing_was_corrected(mock_paste, tmp_path):
    app = _ready_app(tmp_path, "nothing to correct here")

    app._on_stop_record()
    time.sleep(0.3)

    assert app.has_correction_to_undo() is False
    assert app.undo_last_correction() is False


def test_format_pending_lists_candidates(tmp_path):
    queue = tmp_path / "pending.toml"
    queue.write_text(
        'schema_version = 1\n\n[[candidate]]\nheard = "our"\nsuggested = "OAuth"\n'
        'method = "phonetic"\ndistance = 1\ncount = 3\n',
        encoding="utf-8",
    )
    output = format_pending(queue)

    assert "our" in output and "OAuth" in output and "3" in output


def test_format_pending_handles_missing_file(tmp_path):
    assert "no candidates" in format_pending(tmp_path / "absent.toml").lower()


def test_main_version_flag(capsys):
    with pytest.raises(SystemExit) as exit_info:
        main(["--version"])

    assert exit_info.value.code == 0
    assert parakeet_cage.__version__ in capsys.readouterr().out
