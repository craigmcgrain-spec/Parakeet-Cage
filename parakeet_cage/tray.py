"""System tray integration via pystray."""

import logging
import threading
from typing import Callable, Optional

from PIL import Image, ImageDraw
import pystray

from parakeet_cage.hotkey import AppState

logger = logging.getLogger(__name__)


def create_tray_icon_image(state: AppState = AppState.IDLE) -> Image.Image:
    """Generate a 64x64 dynamic icon based on current state."""
    img = Image.new("RGBA", (64, 64), color=(0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    if state == AppState.RECORDING:
        # Red circle for recording
        draw.ellipse([8, 8, 56, 56], fill="#e74c3c", outline="#c0392b", width=2)
    elif state == AppState.TRANSCRIBING:
        # Amber circle for transcribing / processing
        draw.ellipse([8, 8, 56, 56], fill="#f39c12", outline="#d68910", width=2)
    else:
        # Teal / blue circle for idle ready state
        draw.ellipse([8, 8, 56, 56], fill="#2ecc71", outline="#27ae60", width=2)

    return img


class TrayManager:
    """Manages system tray lifecycle and menu."""

    def __init__(
        self,
        on_settings: Callable[[], None],
        on_quit: Callable[[], None],
    ):
        self._on_settings = on_settings
        self._on_quit = on_quit
        self._icon: Optional[pystray.Icon] = None
        self._thread: Optional[threading.Thread] = None

    def _build_icon(self) -> pystray.Icon:
        image = create_tray_icon_image(AppState.IDLE)
        menu = pystray.Menu(
            pystray.MenuItem("Settings", self._handle_settings),
            pystray.MenuItem("Quit", self._handle_quit),
        )
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
        """Update the icon image based on application state."""
        if self._icon is not None:
            self._icon.icon = create_tray_icon_image(state)

    def stop(self) -> None:
        """Stop tray icon."""
        if self._icon is not None:
            self._icon.stop()

    def _handle_settings(self, icon, item) -> None:
        self._on_settings()

    def _handle_quit(self, icon, item) -> None:
        self._on_quit()
