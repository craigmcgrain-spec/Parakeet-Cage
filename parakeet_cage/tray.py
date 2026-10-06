"""System tray integration via pystray with thread-safe icon updates."""

import logging
import threading
from typing import Callable, Optional

import gi
try:
    gi.require_version("Gdk", "3.0")
    gi.require_version("Gtk", "3.0")
except ValueError:
    pass
from gi.repository import GLib

from PIL import Image, ImageDraw
import pystray

from parakeet_cage.hotkey import AppState

logger = logging.getLogger(__name__)


def create_tray_icon_image(state: AppState = AppState.IDLE) -> Image.Image:
    """Generate a 64x64 dynamic icon based on current state."""
    img = Image.new("RGBA", (64, 64), color=(0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    if state == AppState.RECORDING:
        # Bright Red circle for recording
        draw.ellipse([6, 6, 58, 58], fill="#e74c3c", outline="#c0392b", width=3)
    elif state == AppState.TRANSCRIBING:
        # Bright Amber circle for transcribing / processing
        draw.ellipse([6, 6, 58, 58], fill="#f39c12", outline="#d68910", width=3)
    else:
        # Bright Green circle for idle ready state
        draw.ellipse([6, 6, 58, 58], fill="#2ecc71", outline="#27ae60", width=3)

    return img


class TrayManager:
    """Manages system tray lifecycle and menu."""

    def __init__(
        self,
        on_settings: Callable[[], None],
        on_quit: Callable[[], None],
        on_undo: Optional[Callable[[], bool]] = None,
        can_undo: Optional[Callable[[], bool]] = None,
        on_dictionary: Optional[Callable[[], None]] = None,
    ):
        self._on_settings = on_settings
        self._on_quit = on_quit
        self._on_undo = on_undo
        self._can_undo = can_undo or (lambda: False)
        self._on_dictionary = on_dictionary
        self._icon: Optional[pystray.Icon] = None
        self._thread: Optional[threading.Thread] = None

    def _build_icon(self) -> pystray.Icon:
        image = create_tray_icon_image(AppState.IDLE)
        items = []
        if self._on_undo is not None:
            items.append(
                pystray.MenuItem(
                    "Undo last correction",
                    self._handle_undo,
                    enabled=lambda item: bool(self._can_undo()),
                )
            )
        items.append(pystray.MenuItem("Settings", self._handle_settings))
        if self._on_dictionary is not None:
            items.append(pystray.MenuItem("Dictionary…", self._handle_dictionary))
        items.append(pystray.MenuItem("Quit", self._handle_quit))
        menu = pystray.Menu(*items)
        self._icon = pystray.Icon("parakeet-cage", image, "Parakeet Cage", menu)
        return self._icon

    def run(self) -> None:
        """Run system tray on main loop (blocking)."""
        icon = self._build_icon()
        icon.run()

    def start(self) -> None:
        """Run system tray in background thread."""
        icon = self._build_icon()
        self._thread = threading.Thread(target=icon.run, daemon=True)
        self._thread.start()

    def update_state(self, state: AppState) -> None:
        """Thread-safe update of the icon image based on application state."""
        if self._icon is not None:
            def _update():
                try:
                    self._icon.icon = create_tray_icon_image(state)
                except Exception as e:
                    logger.debug("Tray icon update exception: %s", e)
                return False

            GLib.idle_add(_update)

    def stop(self) -> None:
        """Stop tray icon."""
        if self._icon is not None:
            self._icon.stop()

    def _handle_settings(self, icon, item) -> None:
        self._on_settings()

    def _handle_undo(self, icon, item) -> None:
        if self._on_undo is not None:
            self._on_undo()

    def _handle_dictionary(self, icon, item) -> None:
        if self._on_dictionary is not None:
            self._on_dictionary()

    def _handle_quit(self, icon, item) -> None:
        self._on_quit()
