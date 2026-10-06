"""Tests for parakeet_cage.config."""

from pathlib import Path
import tempfile

from parakeet_cage.config import Config, load_config, save_config


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
