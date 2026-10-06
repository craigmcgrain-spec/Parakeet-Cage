"""TOML configuration load/save for Parakeet Cage."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
import tomllib


@dataclass
class Config:
    record_hotkey: str = "f9"
    quit_hotkey: str = "ctrl+shift+q"
    speech_model: str = "models/parakeet-redux"
    audio_device: str = ""
    device: str = "cpu"
    model_path: Optional[str] = None

    def __post_init__(self):
        if self.model_path is not None:
            self.speech_model = self.model_path
        else:
            self.model_path = self.speech_model


def load_config(path: Path) -> Config:
    """Load config from TOML file. Returns defaults if file missing."""
    if not path.exists():
        return Config()
    with open(path, "rb") as f:
        data = tomllib.load(f)
    model_val = data.get("model", {}).get("path", "models/parakeet-redux")
    return Config(
        record_hotkey=data.get("hotkeys", {}).get("record", "f9"),
        quit_hotkey=data.get("hotkeys", {}).get("quit", "ctrl+shift+q"),
        speech_model=model_val,
        model_path=model_val,
        audio_device=data.get("audio", {}).get("device", ""),
        device=data.get("model", {}).get("device", "cpu"),
    )


def save_config(cfg: Config, path: Path) -> None:
    """Save config to TOML file. Creates parent dirs if needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        f.write("[hotkeys]\n")
        f.write(f'record = "{cfg.record_hotkey}"\n')
        f.write(f'quit = "{cfg.quit_hotkey}"\n')
        f.write("\n[model]\n")
        f.write(f'path = "{cfg.speech_model}"\n')
        f.write(f'device = "{cfg.device}"\n')
        f.write("\n[audio]\n")
        f.write(f'device = "{cfg.audio_device}"\n')
