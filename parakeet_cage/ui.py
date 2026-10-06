"""Settings dialog via GTK 3 with audio device dropdown."""

import logging
from typing import Callable, List, Optional, Tuple

import gi
try:
    gi.require_version("Gdk", "3.0")
    gi.require_version("Gtk", "3.0")
except ValueError:
    pass
from gi.repository import Gdk, GLib, Gtk
import sounddevice

from parakeet_cage.config import Config

logger = logging.getLogger(__name__)


def get_input_devices() -> List[Tuple[str, str]]:
    """Return list of (display_label, device_name_or_id) for audio input devices."""
    devices = [("Default System Microphone", "")]
    seen_names = set()
    try:
        device_list = sounddevice.query_devices()
        for d in device_list:
            if d.get("max_input_channels", 0) > 0:
                name = d.get("name", "")
                if name and name not in seen_names:
                    seen_names.add(name)
                    devices.append((name, name))
    except Exception as e:
        logger.warning("Could not query sound devices: %s", e)
    return devices


def event_to_hotkey_string(keyval: int, state: int) -> Optional[str]:
    """Convert GTK key event into standardized hotkey string."""
    keyname = Gdk.keyval_name(keyval)
    if not keyname:
        return None
    keyname = keyname.lower()

    if keyname == "escape":
        return "escape"

    # Ignore bare modifier presses
    if keyname in ("control_l", "control_r", "shift_l", "shift_r", "alt_l", "alt_r", "super_l", "super_r", "meta_l", "meta_r"):
        return None

    modifiers = []
    if state & Gdk.ModifierType.CONTROL_MASK:
        modifiers.append("ctrl")
    if state & Gdk.ModifierType.MOD1_MASK:
        modifiers.append("alt")
    if state & Gdk.ModifierType.SHIFT_MASK:
        modifiers.append("shift")
    if state & Gdk.ModifierType.SUPER_MASK or state & Gdk.ModifierType.MOD4_MASK:
        modifiers.append("super")

    key_map = {
        "return": "enter",
        "page_up": "page_up",
        "page_down": "page_down",
    }
    final_key = key_map.get(keyname, keyname)

    if modifiers:
        return "+".join(modifiers + [final_key])
    return final_key


class SettingsWindow:
    """GTK 3 Settings dialog with interactive key capturing and device selector."""

    def __init__(self, cfg: Config, on_save: Callable[[Config], None]):
        self.cfg = cfg
        self.on_save = on_save
        self._record_hotkey = cfg.record_hotkey
        self._quit_hotkey = cfg.quit_hotkey
        self._listening_btn: Optional[Gtk.Button] = None
        self._listening_target: Optional[str] = None

    def show(self) -> None:
        """Schedule GTK window on the GLib main loop."""
        GLib.idle_add(self._create_and_show)

    def _create_and_show(self) -> bool:
        dialog = Gtk.Window(title="Parakeet Cage Settings")
        dialog.set_default_size(500, 280)
        dialog.set_position(Gtk.WindowPosition.CENTER)
        dialog.set_border_width(16)

        grid = Gtk.Grid(column_spacing=12, row_spacing=12)
        dialog.add(grid)

        # Record Hotkey
        rec_label = Gtk.Label(label="Record Hotkey:", xalign=0)
        grid.attach(rec_label, 0, 0, 1, 1)

        rec_btn = Gtk.Button(label=self._record_hotkey or "None")
        rec_btn.connect("clicked", lambda b: self._start_listening(b, "record"))
        grid.attach(rec_btn, 1, 0, 1, 1)

        # Quit Hotkey
        quit_label = Gtk.Label(label="Quit Hotkey:", xalign=0)
        grid.attach(quit_label, 0, 1, 1, 1)

        quit_btn = Gtk.Button(label=self._quit_hotkey or "None")
        quit_btn.connect("clicked", lambda b: self._start_listening(b, "quit"))
        grid.attach(quit_btn, 1, 1, 1, 1)

        # Audio Device Dropdown
        audio_label = Gtk.Label(label="Audio Input Device:", xalign=0)
        grid.attach(audio_label, 0, 2, 1, 1)

        device_combo = Gtk.ComboBoxText()
        devices = get_input_devices()
        active_idx = 0

        for idx, (label, val) in enumerate(devices):
            device_combo.append(val, label)
            if val == self.cfg.audio_device or (not self.cfg.audio_device and val == ""):
                active_idx = idx

        device_combo.set_active(active_idx)
        grid.attach(device_combo, 1, 2, 1, 1)

        # Model Path
        model_label = Gtk.Label(label="Speech Model:", xalign=0)
        grid.attach(model_label, 0, 3, 1, 1)

        model_entry = Gtk.Entry()
        model_entry.set_text(self.cfg.model_path or "moondream/parakeet-redux")
        grid.attach(model_entry, 1, 3, 1, 1)

        model_hint = Gtk.Label(
            label="<small><i>HuggingFace repo ID or local checkpoint path</i></small>",
            use_markup=True,
            xalign=0,
        )
        grid.attach(model_hint, 1, 4, 1, 1)

        # Buttons
        bbox = Gtk.ButtonBox(orientation=Gtk.Orientation.HORIZONTAL)
        bbox.set_layout(Gtk.ButtonBoxStyle.END)
        bbox.set_spacing(8)

        save_btn = Gtk.Button(label="Save")
        cancel_btn = Gtk.Button(label="Cancel")

        def on_save_clicked(_):
            selected_device_id = device_combo.get_active_id() or ""
            new_cfg = Config(
                record_hotkey=self._record_hotkey.strip(),
                quit_hotkey=self._quit_hotkey.strip(),
                model_path=model_entry.get_text().strip(),
                audio_device=selected_device_id,
            )
            self.cfg = new_cfg
            self.on_save(new_cfg)
            dialog.destroy()

        save_btn.connect("clicked", on_save_clicked)
        cancel_btn.connect("clicked", lambda _: dialog.destroy())

        bbox.pack_start(cancel_btn, False, False, 0)
        bbox.pack_start(save_btn, False, False, 0)
        grid.attach(bbox, 0, 5, 2, 1)

        dialog.connect("key-press-event", self._on_key_press)
        dialog.show_all()
        return False

    def _start_listening(self, button: Gtk.Button, target: str) -> None:
        button.set_label("Press keys... (Esc to cancel)")
        self._listening_target = target
        self._listening_btn = button

    def _on_key_press(self, widget, event) -> bool:
        if not self._listening_btn:
            return False

        hotkey_str = event_to_hotkey_string(event.keyval, event.state)
        if hotkey_str is None:
            return True

        if hotkey_str == "escape":
            if self._listening_target == "record":
                self._listening_btn.set_label(self._record_hotkey or "None")
            else:
                self._listening_btn.set_label(self._quit_hotkey or "None")
            self._listening_btn = None
            self._listening_target = None
            return True

        if self._listening_target == "record":
            self._record_hotkey = hotkey_str
            self._listening_btn.set_label(hotkey_str)
        else:
            self._quit_hotkey = hotkey_str
            self._listening_btn.set_label(hotkey_str)

        self._listening_btn = None
        self._listening_target = None
        return True
