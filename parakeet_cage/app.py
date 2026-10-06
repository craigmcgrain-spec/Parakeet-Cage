"""Main application orchestrator."""

import logging
import os
from pathlib import Path
import sys
import threading
from typing import Optional

from parakeet_cage.audio import AudioRecorder
from parakeet_cage.clipboard import paste_text
from parakeet_cage.config import Config, load_config, save_config
from parakeet_cage.hotkey import AppState, HotkeyListener, StateMachine
from parakeet_cage.transcriber import Transcriber
from parakeet_cage.tray import TrayManager
from parakeet_cage.ui import SettingsWindow

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = Path(
    os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")
) / "parakeet-cage" / "config.toml"


class Application:
    """Core coordinator tying config, audio, STT, hotkeys, and tray."""

    def __init__(self, config: Optional[Config] = None, config_path: Path = DEFAULT_CONFIG_PATH):
        self.config_path = config_path
        self.config = config or load_config(self.config_path)

        self.recorder = AudioRecorder()
        self.transcriber = Transcriber()

        self.state_machine = StateMachine(
            on_start_record=self._on_start_record,
            on_stop_record=self._on_stop_record,
            on_quit=self.quit,
        )

        self.hotkeys = HotkeyListener(
            record_hotkey=self.config.record_hotkey,
            quit_hotkey=self.config.quit_hotkey,
            state_machine=self.state_machine,
        )

        self.tray = TrayManager(
            on_settings=self._open_settings,
            on_quit=self.quit,
        )

    def _on_start_record(self) -> None:
        logger.info("Recording started...")
        self.tray.update_state(AppState.RECORDING)
        self.recorder.start(device=self.config.audio_device)

    def _on_stop_record(self) -> None:
        logger.info("Recording stopped. Transcribing...")
        self.tray.update_state(AppState.TRANSCRIBING)
        audio_data = self.recorder.stop()

        def transcribe_job():
            try:
                text = self.transcriber.transcribe(audio_data)
                if text:
                    logger.info("Transcribed: %s", text)
                    paste_text(text)
            except Exception as e:
                logger.error("Error during transcribe/paste: %s", e)
            finally:
                self.state_machine.handle_transcribe_finished()
                self.tray.update_state(AppState.IDLE)

        threading.Thread(target=transcribe_job, daemon=True).start()

    def _open_settings(self) -> None:
        def on_save(new_cfg: Config):
            self.config = new_cfg
            save_config(new_cfg, self.config_path)
            self.hotkeys.update_hotkeys(new_cfg.record_hotkey, new_cfg.quit_hotkey)
            logger.info("Saved configuration and updated hotkeys.")

        win = SettingsWindow(self.config, on_save=on_save)
        win.show()

    def run(self) -> None:
        """Initialize models and run background daemon."""
        logger.info("Loading speech model: %s", self.config.model_path or "moondream/parakeet-redux")
        self.transcriber.load(self.config.model_path or "moondream/parakeet-redux")

        self.hotkeys.start()
        logger.info("Parakeet Cage is running. Ready for speech input.")

        # Run the tray icon on the main thread loop
        self.tray.run()

    def quit(self) -> None:
        logger.info("Shutting down Parakeet Cage...")
        self.hotkeys.stop()
        self.tray.stop()
        sys.exit(0)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    app = Application()
    app.run()


if __name__ == "__main__":
    main()
