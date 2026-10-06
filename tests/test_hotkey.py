"""Tests for parakeet_cage.hotkey and state machine."""

import logging
import os
import threading
import time
from unittest.mock import MagicMock

import pytest

from parakeet_cage.hotkey import AppState, HotkeyListener, StateMachine, _XErrorRecorder


def test_initial_state_is_idle():
    sm = StateMachine(
        on_start_record=MagicMock(),
        on_stop_record=MagicMock(),
        on_quit=MagicMock(),
    )
    assert sm.state == AppState.IDLE


def test_trigger_record_transitions_idle_to_recording():
    start_mock = MagicMock()
    sm = StateMachine(
        on_start_record=start_mock,
        on_stop_record=MagicMock(),
        on_quit=MagicMock(),
    )
    sm.handle_record_pressed()
    assert sm.state == AppState.RECORDING
    start_mock.assert_called_once()


def test_trigger_record_release_transitions_to_transcribing():
    stop_mock = MagicMock()
    sm = StateMachine(
        on_start_record=MagicMock(),
        on_stop_record=stop_mock,
        on_quit=MagicMock(),
    )
    sm.handle_record_pressed()
    sm.handle_record_released()
    assert sm.state == AppState.TRANSCRIBING
    stop_mock.assert_called_once()


def test_finish_transcribing_returns_to_idle():
    sm = StateMachine(
        on_start_record=MagicMock(),
        on_stop_record=MagicMock(),
        on_quit=MagicMock(),
    )
    sm.handle_record_pressed()
    sm.handle_record_released()
    sm.handle_transcribe_finished()
    assert sm.state == AppState.IDLE


def test_quit_triggers_quit_callback():
    quit_mock = MagicMock()
    sm = StateMachine(
        on_start_record=MagicMock(),
        on_stop_record=MagicMock(),
        on_quit=quit_mock,
    )
    sm.handle_quit()
    quit_mock.assert_called_once()


# --- global key grabs --------------------------------------------------------


class _FakeDisplay:
    def __init__(self):
        self.error_handler = None

    def set_error_handler(self, handler):
        self.handler = handler


def test_x_error_recorder_captures_errors_only_while_armed():
    recorder = _XErrorRecorder()
    recorder.arm()
    recorder("badaccess-while-grabbing", "grab-request")

    assert recorder.disarm() == ["badaccess-while-grabbing"]
    recorder("later-error", None)
    assert recorder.disarm() == []


def test_x_error_recorder_delegates_errors_when_not_armed():
    delegated = []
    display = _FakeDisplay()
    display.error_handler = lambda error, request: delegated.append(error)

    recorder = _XErrorRecorder()
    recorder.attach(display)
    recorder("unrelated-error", None)

    assert delegated == ["unrelated-error"]


def _state_machine() -> StateMachine:
    return StateMachine(on_start_record=MagicMock(), on_stop_record=MagicMock(), on_quit=MagicMock())


@pytest.mark.skipif(not os.environ.get("DISPLAY"), reason="needs an X display for key grabs")
def test_hotkey_held_by_another_client_is_reported_not_silently_ignored(caplog):
    """XGrabKey failures only *print* in python-xlib: sync() does not raise.

    Without capturing them the listener claimed "Registered global record hotkey" while
    another instance held the key, and dictation silently never triggered.
    """
    from Xlib import X, XK
    from Xlib.display import Display

    holder = Display()
    root = holder.screen().root
    keycode = holder.keysym_to_keycode(XK.string_to_keysym("F8"))
    for mask in (0, X.Mod2Mask, X.LockMask, X.Mod2Mask | X.LockMask):
        root.grab_key(keycode, mask, True, X.GrabModeAsync, X.GrabModeAsync)
    holder.sync()

    listener = HotkeyListener(record_hotkey="F8", quit_hotkey="", state_machine=_state_machine())
    try:
        with caplog.at_level(logging.INFO):
            listener.start()
            deadline = time.time() + 5
            while not listener.unavailable_hotkeys and time.time() < deadline:
                time.sleep(0.05)

        assert "F8" in listener.unavailable_hotkeys
        assert "already" in caplog.text.lower()
        assert "Registered global record hotkey" not in caplog.text
    finally:
        listener.stop()
        root.ungrab_key(keycode, X.AnyModifier)
        holder.sync()
