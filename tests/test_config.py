"""Tests for parakeet_cage.config."""

from pathlib import Path
import tempfile

from parakeet_cage.config import Config, TextConfig, load_config, save_config


def test_load_config_returns_defaults():
    cfg = load_config(Path("/nonexistent/config.toml"))
    assert cfg.record_hotkey == "f9"
    assert cfg.quit_hotkey == "ctrl+shift+q"
    assert cfg.speech_model == "models/parakeet-redux"
    assert cfg.audio_device == ""


def test_save_then_load_roundtrip():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "config.toml"
        cfg = Config(
            record_hotkey="alt+f9",
            quit_hotkey="alt+f10",
            model_path="/tmp/m",
            audio_device="usb",
        )
        save_config(cfg, path)
        loaded = load_config(path)
        assert loaded.record_hotkey == "alt+f9"
        assert loaded.quit_hotkey == "alt+f10"
        assert loaded.speech_model == "/tmp/m"
        assert loaded.audio_device == "usb"


# --- [text] section: spoken punctuation + personal dictionary ----------------


def test_text_processing_defaults_are_on():
    cfg = load_config(Path("/nonexistent/config.toml"))
    assert cfg.text.punctuation is True
    assert cfg.text.lexicon is True
    assert cfg.text.lexicon_max_distance == 2
    assert cfg.text.punctuation_extra == {}


def test_load_config_reads_text_section(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(
        "[text]\n"
        "punctuation = false\n"
        "lexicon = false\n"
        "lexicon_max_distance = 3\n"
        "\n"
        "[text.punctuation_extra]\n"
        '"winky face" = ";-)"\n',
        encoding="utf-8",
    )
    cfg = load_config(path)

    assert cfg.text.punctuation is False
    assert cfg.text.lexicon is False
    assert cfg.text.lexicon_max_distance == 3
    assert cfg.text.punctuation_extra == {"winky face": ";-)"}


def test_save_then_load_roundtrip_keeps_text_settings(tmp_path):
    path = tmp_path / "config.toml"
    cfg = Config(
        text=TextConfig(
            punctuation=False,
            lexicon=True,
            lexicon_max_distance=1,
            lexicon_path="/tmp/lexicon.toml",
            punctuation_extra={"period": "!"},
        )
    )
    save_config(cfg, path)
    loaded = load_config(path)

    assert loaded.text == cfg.text
