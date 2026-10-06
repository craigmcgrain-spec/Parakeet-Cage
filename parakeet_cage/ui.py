"""Settings dialog via tkinter."""

import logging
import tkinter as tk
from tkinter import ttk
from typing import Callable, Optional

from parakeet_cage.config import Config

logger = logging.getLogger(__name__)


class SettingsWindow:
    """Tkinter-based configuration window."""

    def __init__(self, cfg: Config, on_save: Callable[[Config], None]):
        self.cfg = cfg
        self.on_save = on_save
        self._root: Optional[tk.Tk] = None

    def show(self) -> None:
        """Open settings window (blocking loop or Toplevel)."""
        root = tk.Tk()
        self._root = root
        root.title("Parakeet Cage Settings")
        root.geometry("400x260")
        root.resizable(False, False)

        frame = ttk.Frame(root, padding="16")
        frame.pack(fill=tk.BOTH, expand=True)

        # Record Hotkey
        ttk.Label(frame, text="Record Hotkey:").grid(row=0, column=0, sticky=tk.W, pady=4)
        record_entry = ttk.Entry(frame)
        record_entry.insert(0, self.cfg.record_hotkey)
        record_entry.grid(row=0, column=1, sticky=tk.EW, pady=4)

        # Quit Hotkey
        ttk.Label(frame, text="Quit Hotkey:").grid(row=1, column=0, sticky=tk.W, pady=4)
        quit_entry = ttk.Entry(frame)
        quit_entry.insert(0, self.cfg.quit_hotkey)
        quit_entry.grid(row=1, column=1, sticky=tk.EW, pady=4)

        # Model Path
        ttk.Label(frame, text="Model Path / Repo:").grid(row=2, column=0, sticky=tk.W, pady=4)
        model_entry = ttk.Entry(frame)
        model_entry.insert(0, self.cfg.model_path)
        model_entry.grid(row=2, column=1, sticky=tk.EW, pady=4)

        # Audio Device
        ttk.Label(frame, text="Audio Device:").grid(row=3, column=0, sticky=tk.W, pady=4)
        audio_entry = ttk.Entry(frame)
        audio_entry.insert(0, self.cfg.audio_device)
        audio_entry.grid(row=3, column=1, sticky=tk.EW, pady=4)

        frame.columnconfigure(1, weight=1)

        def save_and_close():
            new_cfg = Config(
                record_hotkey=record_entry.get().strip(),
                quit_hotkey=quit_entry.get().strip(),
                model_path=model_entry.get().strip(),
                audio_device=audio_entry.get().strip(),
            )
            self.cfg = new_cfg
            self.on_save(new_cfg)
            root.destroy()

        btn_frame = ttk.Frame(frame)
        btn_frame.grid(row=4, column=0, columnspan=2, pady=16)

        ttk.Button(btn_frame, text="Save", command=save_and_close).pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_frame, text="Cancel", command=root.destroy).pack(side=tk.LEFT, padx=4)

        root.mainloop()
