"""TOML configuration load/save for Parakeet Cage."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional
import tomllib


@dataclass
class TextConfig:
    """Transcript post-processing: spoken punctuation and the personal dictionary.

    `punctuation_extra` maps a spoken command to a symbol; an empty string disables a
    built-in command, and any new key adds one.
    """

    punctuation: bool = True
    punctuation_extra: Dict[str, str] = field(default_factory=dict)
    lexicon: bool = True
    lexicon_path: str = ""
    lexicon_max_distance: int = 2
    auto_dictionary: bool = True
    auto_path: str = ""


@dataclass
class Config:
    record_hotkey: str = "f9"
    quit_hotkey: str = "ctrl+shift+q"
    speech_model: str = "models/parakeet-redux"
    audio_device: str = ""
    device: str = "cpu"
    model_path: Optional[str] = None
    text: TextConfig = field(default_factory=TextConfig)

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
    text_data = data.get("text", {}) or {}
    punctuation_extra = text_data.get("punctuation_extra") or {}
    return Config(
        record_hotkey=data.get("hotkeys", {}).get("record", "f9"),
        quit_hotkey=data.get("hotkeys", {}).get("quit", "ctrl+shift+q"),
        speech_model=model_val,
        model_path=model_val,
        audio_device=data.get("audio", {}).get("device", ""),
        device=data.get("model", {}).get("device", "cpu"),
        text=TextConfig(
            punctuation=bool(text_data.get("punctuation", True)),
            punctuation_extra={str(key): str(value) for key, value in punctuation_extra.items()},
            lexicon=bool(text_data.get("lexicon", True)),
            lexicon_path=str(text_data.get("lexicon_path", "")),
            lexicon_max_distance=int(text_data.get("lexicon_max_distance", 2)),
            auto_dictionary=bool(text_data.get("auto_dictionary", True)),
            auto_path=str(text_data.get("auto_path", "")),
        ),
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
        f.write("\n[text]\n")
        f.write(f"punctuation = {'true' if cfg.text.punctuation else 'false'}\n")
        f.write(f"lexicon = {'true' if cfg.text.lexicon else 'false'}\n")
        f.write(f'lexicon_path = "{cfg.text.lexicon_path}"\n')
        f.write(f"lexicon_max_distance = {cfg.text.lexicon_max_distance}\n")
        f.write(f"auto_dictionary = {'true' if cfg.text.auto_dictionary else 'false'}\n")
        f.write(f'auto_path = "{cfg.text.auto_path}"\n')
        f.write("\n[text.punctuation_extra]\n")
        for command, symbol in cfg.text.punctuation_extra.items():
            f.write(f'"{command}" = "{symbol}"\n')
