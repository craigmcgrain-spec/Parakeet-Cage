"""Tests for parakeet_cage.ui."""

import gi
gi.require_version("Gdk", "3.0")
gi.require_version("Gtk", "3.0")
from gi.repository import Gdk

from parakeet_cage.config import Config, TextConfig
from parakeet_cage.ui import build_config, event_to_hotkey_string, get_input_devices


def test_get_input_devices_returns_non_empty_list():
    devices = get_input_devices()
    assert len(devices) >= 1
    # First item is always default
    assert devices[0][1] == ""


def test_event_to_hotkey_string_single_f_key():
    val = Gdk.keyval_from_name("F9")
    assert event_to_hotkey_string(val, 0) == "f9"


def test_event_to_hotkey_string_combination():
    val = Gdk.keyval_from_name("s")
    state = Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.SHIFT_MASK
    assert event_to_hotkey_string(val, state) == "ctrl+shift+s"


def test_event_to_hotkey_string_escape():
    val = Gdk.keyval_from_name("Escape")
    assert event_to_hotkey_string(val, 0) == "escape"


def test_event_to_hotkey_string_modifier_only_ignored():
    val = Gdk.keyval_from_name("Control_L")
    assert event_to_hotkey_string(val, Gdk.ModifierType.CONTROL_MASK) is None


def test_build_config_preserves_unrelated_settings():
    """Saving from the dialog must not wipe the [text] section."""
    base = Config(text=TextConfig(punctuation=False, lexicon_max_distance=3, lexicon_path="/tmp/l.toml"))

    built = build_config(base, record_hotkey="alt+f9", quit_hotkey="alt+f10",
                         model_path="/tmp/m", audio_device="usb")

    assert built.text == base.text
    assert built.record_hotkey == "alt+f9"
    assert built.audio_device == "usb"
