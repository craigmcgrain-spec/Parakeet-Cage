"""Tests for parakeet_cage.ui."""

import gi
gi.require_version("Gdk", "3.0")
gi.require_version("Gtk", "3.0")
from gi.repository import Gdk

from parakeet_cage.ui import event_to_hotkey_string, get_input_devices


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
