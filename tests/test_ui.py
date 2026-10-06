"""Tests for parakeet_cage.ui interactive hotkey capture."""

from unittest.mock import MagicMock
import tkinter as tk

from parakeet_cage.config import Config
from parakeet_cage.ui import SettingsWindow, event_to_hotkey_string


def test_event_to_hotkey_string_single_key():
    event = MagicMock(spec=tk.Event)
    event.keysym = "F9"
    event.state = 0
    assert event_to_hotkey_string(event) == "f9"


def test_event_to_hotkey_string_with_modifiers():
    event = MagicMock(spec=tk.Event)
    event.keysym = "s"
    event.state = 0x0004 | 0x0001  # Ctrl + Shift
    assert event_to_hotkey_string(event) == "ctrl+shift+s"


def test_event_to_hotkey_string_escape_cancels():
    event = MagicMock(spec=tk.Event)
    event.keysym = "Escape"
    event.state = 0
    assert event_to_hotkey_string(event) == "escape"


def test_event_to_hotkey_string_modifier_only_returns_none():
    event = MagicMock(spec=tk.Event)
    event.keysym = "Control_L"
    event.state = 0x0004
    assert event_to_hotkey_string(event) is None
