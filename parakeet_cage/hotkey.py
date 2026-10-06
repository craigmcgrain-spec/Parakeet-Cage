"""Global hotkey handler and application state machine."""

from enum import Enum, auto
import logging
import threading
from typing import Callable, Optional

logger = logging.getLogger(__name__)


class AppState(Enum):
    IDLE = auto()
    RECORDING = auto()
    TRANSCRIBING = auto()


class StateMachine:
    """Coordinates hotkey events and audio/transcription transitions."""

    def __init__(
        self,
        on_start_record: Callable[[], None],
        on_stop_record: Callable[[], None],
        on_quit: Callable[[], None],
    ):
        self._state = AppState.IDLE
        self._lock = threading.Lock()
        self._on_start_record = on_start_record
        self._on_stop_record = on_stop_record
        self._on_quit = on_quit

    @property
    def state(self) -> AppState:
        with self._lock:
            return self._state

    def handle_record_pressed(self) -> None:
        with self._lock:
            if self._state == AppState.IDLE:
                self._state = AppState.RECORDING
                self._on_start_record()

    def handle_record_released(self) -> None:
        with self._lock:
            if self._state == AppState.RECORDING:
                self._state = AppState.TRANSCRIBING
                self._on_stop_record()

    def handle_transcribe_finished(self) -> None:
        with self._lock:
            self._state = AppState.IDLE

    def handle_quit(self) -> None:
        self._on_quit()


class HotkeyListener:
    """Listens for global key combinations."""

    def __init__(
        self,
        record_hotkey: str,
        quit_hotkey: str,
        state_machine: StateMachine,
    ):
        self.record_hotkey = record_hotkey
        self.quit_hotkey = quit_hotkey
        self.state_machine = state_machine
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        self._running = True

    def stop(self) -> None:
        self._running = False
