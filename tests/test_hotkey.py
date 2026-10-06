"""Tests for parakeet_cage.hotkey and state machine."""

import threading
import time
from unittest.mock import MagicMock

from parakeet_cage.hotkey import AppState, StateMachine


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
