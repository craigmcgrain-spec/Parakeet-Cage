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
        logger.info("[APP] Record hotkey pressed -> Switching to RECORDING (Red)")
        self.tray.update_state(AppState.RECORDING)
        self.recorder.start(device=self.config.audio_device)

    def _on_stop_record(self) -> None:
        logger.info("[APP] Record hotkey released -> Switching to TRANSCRIBING (Amber)")
        self.tray.update_state(AppState.TRANSCRIBING)
        audio_data = self.recorder.stop()

        def transcribe_job():
            try:
                if not self.transcriber.ready:
                    logger.warning("[APP] Transcriber engine not loaded yet!")
                elif not audio_data:
                    logger.warning("[APP] No audio data was recorded.")
                else:
                    logger.info("[APP] Running local speech inference on %d bytes of audio...", len(audio_data))
                    text = self.transcriber.transcribe(audio_data)
                    logger.info("[APP] Model transcription result: '%s'", text)
                    if text:
                        paste_text(text)
            except Exception as e:
                logger.exception("[APP] Error during transcription/paste execution: %s", e)
            finally:
                logger.info("[APP] Transcription complete -> Resetting state to IDLE (Green)")
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
        """Start all application services."""
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(message)s",
            datefmt="%H:%M:%S",
        )
        logger.info("Starting Parakeet Cage application...")

        # 1. Start hotkey listener
        self.hotkeys.start()

        # 2. Warm up transcriber in background
        def load_model():
            try:
                logger.info("Pre-warming local Parakeet ASR engine...")
                self.transcriber.load(
                    model_path=self.config.speech_model,
                    device=self.config.device,
                )
                logger.info("Parakeet ASR engine is ready.")
            except Exception as e:
                logger.exception("Failed to load Parakeet speech model: %s", e)

        threading.Thread(target=load_model, daemon=True).start()

        # 3. Start tray on main loop
        self.tray.run()

    def quit(self) -> None:
        """Graceful shutdown."""
        logger.info("Shutting down Parakeet Cage...")
        self.hotkeys.stop()
        self.tray.stop()
        sys.exit(0)


def main():
    app = Application()
    app.run()


if __name__ == "__main__":
    main()
