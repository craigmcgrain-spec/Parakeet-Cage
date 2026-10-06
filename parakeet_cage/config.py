"""TOML configuration load/save for Parakeet Cage."""

from dataclasses import dataclass, fields
from pathlib import Path

import tomllib


@dataclass
class Config:
    record_hotkey: str = "ctrl+shift+s"
    quit_hotkey: str = "ctrl+shift+q"
    model_path: str = ""
    audio_device: str = ""


def load_config(path: Path) -> Config:
    """Load config from TOML file. Returns defaults if file missing."""
    if not path.exists():
        return Config()
    with open(path, "rb") as f:
        data = tomllib.load(f)
    return Config(
        record_hotkey=data.get("hotkeys", {}).get("record", "ctrl+shift+s"),
        quit_hotkey=data.get("hotkeys", {}).get("quit", "ctrl+shift+q"),
        model_path=data.get("model", {}).get("path", ""),
        audio_device=data.get("audio", {}).get("device", ""),
    )


def save_config(cfg: Config, path: Path) -> None:
    """Save config to TOML file. Creates parent dirs if needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        f.write("[hotkeys]\n")
        f.write(f'record = "{cfg.record_hotkey}"\n')
        f.write(f'quit = "{cfg.quit_hotkey}"\n')
        f.write("\n[model]\n")
        f.write(f'path = "{cfg.model_path}"\n')
        f.write("\n[audio]\n")
        f.write(f'device = "{cfg.audio_device}"\n')
