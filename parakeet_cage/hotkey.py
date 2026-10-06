"""Global hotkey handler and application state machine."""

from enum import Enum, auto
import logging
import threading
import time
from typing import Callable, Optional

import Xlib
from Xlib import X, XK
from Xlib.display import Display

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
                logger.info("StateMachine: Transitioning IDLE -> RECORDING")
                self._on_start_record()

    def handle_record_released(self) -> None:
        with self._lock:
            if self._state == AppState.RECORDING:
                self._state = AppState.TRANSCRIBING
                logger.info("StateMachine: Transitioning RECORDING -> TRANSCRIBING")
                self._on_stop_record()

    def handle_transcribe_finished(self) -> None:
        with self._lock:
            self._state = AppState.IDLE
            logger.info("StateMachine: Transitioning -> IDLE")

    def handle_quit(self) -> None:
        self._on_quit()


def parse_hotkey(hotkey_str: str, display: Display):
    """Parse hotkey string into (keycode, modifier_mask)."""
    parts = [p.strip().lower() for p in hotkey_str.split("+")]
    modifiers = 0
    key_part = ""

    for p in parts:
        if p in ("ctrl", "control"):
            modifiers |= X.ControlMask
        elif p in ("alt", "mod1"):
            modifiers |= X.Mod1Mask
        elif p == "shift":
            modifiers |= X.ShiftMask
        elif p in ("super", "mod4"):
            modifiers |= X.Mod4Mask
        else:
            key_part = p

    # Map name to keysym
    keysym_name = key_part.upper() if key_part.startswith("f") and key_part[1:].isdigit() else key_part
    keysym = XK.string_to_keysym(keysym_name)
    if keysym == 0:
        keysym = XK.string_to_keysym(key_part)

    keycode = display.keysym_to_keycode(keysym)
    return keycode, modifiers


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
        self._disp: Optional[Display] = None

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False

    def update_hotkeys(self, record_hotkey: str, quit_hotkey: str) -> None:
        self.record_hotkey = record_hotkey
        self.quit_hotkey = quit_hotkey
        if self._disp:
            self._grab_keys(self._disp)

    def _grab_keys(self, disp: Display):
        root = disp.screen().root
        root.ungrab_key(X.AnyKey, X.AnyModifier)

        mod_variants = [0, X.Mod2Mask, X.LockMask, X.Mod2Mask | X.LockMask]

        for hotkey, name in [(self.record_hotkey, "record"), (self.quit_hotkey, "quit")]:
            if not hotkey:
                continue
            try:
                keycode, base_mod = parse_hotkey(hotkey, disp)
                if keycode == 0:
                    logger.warning("Could not map hotkey '%s'", hotkey)
                    continue

                for var in mod_variants:
                    root.grab_key(
                        keycode,
                        base_mod | var,
                        1,
                        X.GrabModeAsync,
                        X.GrabModeAsync,
                    )
                disp.sync()
                logger.info("Registered global %s hotkey: '%s' (keycode=%s)", name, hotkey, keycode)
            except Exception as e:
                logger.error("Failed to grab key for '%s': %s", hotkey, e)

    def _run_loop(self) -> None:
        try:
            self._disp = Display()
        except Exception as e:
            logger.error("Could not connect to X/Xwayland display for global hotkeys: %s", e)
            return

        disp = self._disp
        self._grab_keys(disp)

        logger.info("Global hotkey listener loop running.")

        while self._running:
            record_code, _ = parse_hotkey(self.record_hotkey, disp) if self.record_hotkey else (0, 0)
            quit_code, _ = parse_hotkey(self.quit_hotkey, disp) if self.quit_hotkey else (0, 0)

            while disp.pending_events() > 0 and self._running:
                event = disp.next_event()

                if event.type == X.KeyPress:
                    if event.detail == record_code and record_code != 0:
                        self.state_machine.handle_record_pressed()
                    elif event.detail == quit_code and quit_code != 0:
                        self.state_machine.handle_quit()

                elif event.type == X.KeyRelease:
                    if event.detail == record_code and record_code != 0:
                        # Debounce auto-repeat
                        if disp.pending_events() > 0:
                            next_ev = disp.next_event()
                            if (
                                next_ev.type == X.KeyPress
                                and next_ev.detail == event.detail
                                and next_ev.time == event.time
                            ):
                                continue
                            else:
                                disp.put_back_event(next_ev)
                        self.state_machine.handle_record_released()

            time.sleep(0.01)
