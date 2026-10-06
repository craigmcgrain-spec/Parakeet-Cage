"""Settings dialog via tkinter with interactive key listener."""

import logging
import tkinter as tk
from tkinter import ttk
from typing import Callable, Optional

from parakeet_cage.config import Config

logger = logging.getLogger(__name__)


def event_to_hotkey_string(event: tk.Event) -> Optional[str]:
    """Convert a Tkinter KeyPress event into a standardized hotkey string."""
    keysym = event.keysym.lower()

    # If user pressed Escape alone, signal cancel/stop listening
    if keysym == "escape":
        return "escape"

    # Modifier keys alone should not complete the hotkey
    if keysym in ("control_l", "control_r", "shift_l", "shift_r", "alt_l", "alt_r", "super_l", "super_r", "meta_l", "meta_r"):
        return None

    modifiers = []
    state = event.state

    # Check modifier bitmasks
    if state & 0x0004:  # Control
        modifiers.append("ctrl")
    if state & 0x0008:  # Alt / Mod1
        modifiers.append("alt")
    if state & 0x0001:  # Shift
        modifiers.append("shift")
    if state & 0x0040:  # Super / Windows key
        modifiers.append("super")

    # Map special keysyms to standard names
    key_map = {
        "return": "enter",
        "prior": "page_up",
        "next": "page_down",
    }
    key_name = key_map.get(keysym, keysym)

    if modifiers:
        return "+".join(modifiers + [key_name])
    return key_name


class HotkeyButton(ttk.Button):
    """Button that listens for a key combination on click and uses Esc to cancel."""

    def __init__(self, parent, initial_value: str, on_changed: Callable[[str], None]):
        self.value = initial_value
        self.on_changed = on_changed
        self._listening = False
        super().__init__(parent, text=self.value or "None", command=self._start_listening)

    def _start_listening(self):
        if self._listening:
            return
        self._listening = True
        self.config(text="Press keys... (Esc to cancel)")
        self.focus_set()
        self.bind("<KeyPress>", self._on_key_press)
        self.bind("<FocusOut>", self._stop_listening)

    def _stop_listening(self, event=None):
        if not self._listening:
            return
        self._listening = False
        self.config(text=self.value or "None")
        self.unbind("<KeyPress>")
        self.unbind("<FocusOut>")

    def _on_key_press(self, event: tk.Event):
        hotkey_str = event_to_hotkey_string(event)
        if hotkey_str is None:
            # Intermediate modifier key pressed, keep waiting
            return "break"

        if hotkey_str == "escape":
            # Cancel listening, revert to existing value
            self._stop_listening()
            return "break"

        # Valid key combo captured
        self.value = hotkey_str
        self.config(text=self.value)
        self.on_changed(self.value)
        self._stop_listening()
        return "break"


class SettingsWindow:
    """Tkinter-based configuration window with hotkey recorder."""

    def __init__(self, cfg: Config, on_save: Callable[[Config], None]):
        self.cfg = cfg
        self.on_save = on_save
        self._root: Optional[tk.Tk] = None
        self._record_hotkey = cfg.record_hotkey
        self._quit_hotkey = cfg.quit_hotkey

    def show(self) -> None:
        """Open settings window."""
        root = tk.Tk()
        self._root = root
        root.title("Parakeet Cage Settings")
        root.geometry("450x280")
        root.resizable(False, False)

        frame = ttk.Frame(root, padding="16")
        frame.pack(fill=tk.BOTH, expand=True)

        # Record Hotkey
        ttk.Label(frame, text="Record Hotkey:").grid(row=0, column=0, sticky=tk.W, pady=6)
        def on_record_change(val):
            self._record_hotkey = val
        rec_btn = HotkeyButton(frame, self._record_hotkey, on_changed=on_record_change)
        rec_btn.grid(row=0, column=1, sticky=tk.EW, pady=6)

        # Quit Hotkey
        ttk.Label(frame, text="Quit Hotkey:").grid(row=1, column=0, sticky=tk.W, pady=6)
        def on_quit_change(val):
            self._quit_hotkey = val
        quit_btn = HotkeyButton(frame, self._quit_hotkey, on_changed=on_quit_change)
        quit_btn.grid(row=1, column=1, sticky=tk.EW, pady=6)

        # Model Path
        ttk.Label(frame, text="Model Path:").grid(row=2, column=0, sticky=tk.W, pady=6)
        model_entry = ttk.Entry(frame)
        model_entry.insert(0, self.cfg.model_path)
        model_entry.grid(row=2, column=1, sticky=tk.EW, pady=6)

        # Audio Device
        ttk.Label(frame, text="Audio Device:").grid(row=3, column=0, sticky=tk.W, pady=6)
        audio_entry = ttk.Entry(frame)
        audio_entry.insert(0, self.cfg.audio_device)
        audio_entry.grid(row=3, column=1, sticky=tk.EW, pady=6)

        frame.columnconfigure(1, weight=1)

        def save_and_close():
            new_cfg = Config(
                record_hotkey=self._record_hotkey.strip(),
                quit_hotkey=self._quit_hotkey.strip(),
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
