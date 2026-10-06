"""Global hotkey handler and application state machine."""

from enum import Enum, auto
import logging
import threading
import time
from typing import Callable, List, Optional, Set

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

    keysym_name = key_part.upper() if key_part.startswith("f") and key_part[1:].isdigit() else key_part
    keysym = XK.string_to_keysym(keysym_name)
    if keysym == 0:
        keysym = XK.string_to_keysym(key_part)

    keycode = display.keysym_to_keycode(keysym)
    return keycode, modifiers


class _XErrorRecorder:
    """Captures X protocol errors raised while grabbing keys.

    python-xlib only *prints* asynchronous errors such as BadAccess from XGrabKey; sync()
    returns normally. A grab that another client already holds therefore looks like a
    success. Arming the recorder around a grab attempt makes that checkable; while it is
    not armed, errors are passed on unchanged.
    """

    def __init__(self) -> None:
        self._errors: List[object] = []
        self._armed = False
        self._previous: Optional[Callable] = None

    def attach(self, display) -> None:
        self._previous = getattr(display, "error_handler", None)
        display.set_error_handler(self)

    def arm(self) -> None:
        self._errors.clear()
        self._armed = True

    def disarm(self) -> List[object]:
        """Stop capturing and hand back what was captured (one shot)."""
        self._armed = False
        errors, self._errors = self._errors, []
        return errors

    def __call__(self, error, request) -> None:
        if self._armed:
            self._errors.append(error)
            return
        if callable(self._previous):
            self._previous(error, request)
        else:
            logger.debug("Unhandled X protocol error: %s", error)


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
        self._last_press_time: float = 0.0
        self._errors = _XErrorRecorder()
        self.unavailable_hotkeys: Set[str] = set()

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

                self._errors.arm()
                for var in mod_variants:
                    root.grab_key(
                        keycode,
                        base_mod | var,
                        1,
                        X.GrabModeAsync,
                        X.GrabModeAsync,
                    )
                disp.sync()
                refused = self._errors.disarm()
                if refused:
                    self.unavailable_hotkeys.add(hotkey)
                    logger.error(
                        "Could not register the %s hotkey '%s': the X server refused the grab "
                        "(%s: %s). Another application is probably holding it - is Parakeet Cage "
                        "already running? Dictation will not trigger until the key is free.",
                        name, hotkey, type(refused[0]).__name__, refused[0],
                    )
                    continue

                self.unavailable_hotkeys.discard(hotkey)
                logger.info("Registered global %s hotkey: '%s' (keycode=%s)", name, hotkey, keycode)
            except Exception as e:
                self._errors.disarm()
                logger.error("Failed to grab key for '%s': %s", hotkey, e)

    def _run_loop(self) -> None:
        try:
            self._disp = Display()
        except Exception as e:
            logger.error("Could not connect to X/Xwayland display for global hotkeys: %s", e)
            return
        self._errors.attach(self._disp)

        disp = self._disp
        self._grab_keys(disp)

        logger.info("Global hotkey listener loop running.")

        is_key_down = False
        last_key_press_time = 0.0

        while self._running:
            record_code, _ = parse_hotkey(self.record_hotkey, disp) if self.record_hotkey else (0, 0)
            quit_code, _ = parse_hotkey(self.quit_hotkey, disp) if self.quit_hotkey else (0, 0)

            while disp.pending_events() > 0 and self._running:
                event = disp.next_event()

                if event.type == X.KeyPress:
                    if event.detail == record_code and record_code != 0:
                        last_key_press_time = time.monotonic()
                        if not is_key_down:
                            is_key_down = True
                            self.state_machine.handle_record_pressed()
                    elif event.detail == quit_code and quit_code != 0:
                        self.state_machine.handle_quit()

                elif event.type == X.KeyRelease:
                    if event.detail == record_code and record_code != 0:
                        # Auto-repeat check: peek ahead in the event queue
                        disp.sync()
                        has_immediate_press = False
                        while disp.pending_events() > 0:
                            next_ev = disp.next_event()
                            if next_ev.type == X.KeyPress and next_ev.detail == record_code:
                                has_immediate_press = True
                                last_key_press_time = time.monotonic()
                                break
                            else:
                                disp.put_back_event(next_ev)
                                break

                        if not has_immediate_press and is_key_down:
                            is_key_down = False
                            self.state_machine.handle_record_released()

            time.sleep(0.01)
