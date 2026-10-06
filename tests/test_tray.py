"""Tests for parakeet_cage.tray"""

from unittest.mock import MagicMock
from PIL import Image

from parakeet_cage.hotkey import AppState
from parakeet_cage.tray import create_tray_icon_image, TrayManager


def test_create_tray_icon_image_returns_pil_image():
    for state in [AppState.IDLE, AppState.RECORDING, AppState.TRANSCRIBING]:
        img = create_tray_icon_image(state)
        assert isinstance(img, Image.Image)
        assert img.size == (64, 64)


def test_tray_manager_initialization():
    on_settings = MagicMock()
    on_quit = MagicMock()
    tray = TrayManager(on_settings=on_settings, on_quit=on_quit)
    assert tray._icon is None
