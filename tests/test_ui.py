"""Tests for parakeet_cage.ui"""

from unittest.mock import MagicMock
import pytest

from parakeet_cage.config import Config
from parakeet_cage.ui import SettingsWindow


def test_settings_window_data_binding():
    cfg = Config(
        record_hotkey="ctrl+alt+r",
        quit_hotkey="ctrl+alt+q",
        model_path="test/model",
        audio_device="default",
    )
    on_save = MagicMock()
    # In headless env without DISPLAY, we check structural contract
    win = SettingsWindow(cfg=cfg, on_save=on_save)
    assert win.cfg.record_hotkey == "ctrl+alt+r"
    assert win.cfg.quit_hotkey == "ctrl+alt+q"
    assert win.cfg.model_path == "test/model"
    assert win.cfg.audio_device == "default"
