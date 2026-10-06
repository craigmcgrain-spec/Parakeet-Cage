"""Main application orchestrator."""

import argparse
import logging
import os
from pathlib import Path
import sys
import threading
import tomllib
from typing import Optional, Sequence

from parakeet_cage import __version__
from parakeet_cage.audio import AudioRecorder
from parakeet_cage.clipboard import paste_text
from parakeet_cage.config import Config, load_config, save_config
from parakeet_cage.hotkey import AppState, HotkeyListener, StateMachine
from parakeet_cage.postprocess import Change, build_pipeline, default_queue_path
from parakeet_cage.transcriber import Transcriber, resolve_local_model_path
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
        self.pipeline = build_pipeline(self.config.text, tokenizer_path=self._tokenizer_path())
        self._last_change: Optional[Change] = None

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
            on_undo=self.undo_last_correction,
            can_undo=self.has_correction_to_undo,
        )

    def _tokenizer_path(self) -> Optional[Path]:
        """The model's tokenizer, used to tell known words from misheard ones."""
        try:
            return resolve_local_model_path(self.config.speech_model) / "tokenizer.json"
        except Exception as e:
            logger.debug("No local model directory for tokenizer lookup: %s", e)
            return None

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
                        paste_text(self._postprocess(text))
            except Exception as e:
                logger.exception("[APP] Error during transcription/paste execution: %s", e)
            finally:
                logger.info("[APP] Transcription complete -> Resetting state to IDLE (Green)")
                self.state_machine.handle_transcribe_finished()
                self.tray.update_state(AppState.IDLE)

        threading.Thread(target=transcribe_job, daemon=True).start()

    def _postprocess(self, text: str) -> str:
        """Spoken punctuation + personal dictionary. Never breaks dictation."""
        try:
            change = self.pipeline.process(text)
        except Exception as e:
            logger.warning("[APP] Text post-processing failed (%s); pasting the raw transcript", e)
            self._last_change = None
            return text

        self._last_change = change
        if change.corrected:
            logger.info("[APP] Corrected transcript: '%s' -> '%s'", change.raw, change.final)
            for applied in change.applied:
                logger.info("[APP]   %r -> %r (%s, '%s')", applied.before, applied.after,
                            applied.method, applied.word)
        for queued in change.queued:
            logger.info("[APP] Dictionary candidate for review: %r might be %r (%s %d)",
                        queued.token, queued.suggestion, queued.method, queued.distance)
        try:
            self.pipeline.record(change)
        except Exception as e:
            logger.warning("[APP] Could not persist dictionary state: %s", e)
        return change.final

    def has_correction_to_undo(self) -> bool:
        """True when the last transcript was changed by the dictionary or punctuation."""
        return bool(self._last_change is not None and self._last_change.corrected)

    def undo_last_correction(self) -> bool:
        """Paste the raw transcript again, as heard, and forget the correction."""
        if not self.has_correction_to_undo():
            return False
        raw = self._last_change.raw
        self._last_change = None
        logger.info("[APP] Undoing last correction; re-pasting the transcript as heard")
        paste_text(raw)
        return True

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


def format_pending(queue_path: Path) -> str:
    """Human-readable listing of dictionary candidates that were blocked by the guard."""
    path = Path(queue_path)
    if not path.exists():
        return "No candidates awaiting review."
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        return f"Could not read {path}: {e}"

    rows = data.get("candidate", [])
    if not rows:
        return "No candidates awaiting review."

    lines = [f"{len(rows)} candidate(s) in {path}", ""]
    for row in rows:
        lines.append(
            f'  heard "{row.get("heard")}" -> "{row.get("suggested")}"'
            f'  ({row.get("method")}, distance {row.get("distance")}, seen {row.get("count", 1)}x)'
        )
    lines.append("")
    lines.append("Looks right? Add it to the lexicon file as `[[word]] word = \"...\" aliases = [\"...\"]`.")
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> None:
    parser = argparse.ArgumentParser(
        prog="parakeet-cage",
        description="Push-to-talk dictation with fully local speech recognition.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument(
        "--pending",
        action="store_true",
        help="list dictionary words that need confirming, then exit",
    )
    args = parser.parse_args(argv)

    if args.pending:
        print(format_pending(default_queue_path()))
        return

    app = Application()
    app.run()


if __name__ == "__main__":
    main()
