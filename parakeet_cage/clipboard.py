"""Clipboard write + paste keystroke injection with previous clipboard restoration."""

import logging
import os
import shutil
import subprocess
import time
from typing import Optional

logger = logging.getLogger(__name__)


class PasteError(Exception):
    """Raised when clipboard operations fail."""


def get_current_clipboard() -> Optional[str]:
    """Read the current system clipboard content."""
    # 1. KDE Klipper D-Bus
    try:
        import dbus
        bus = dbus.SessionBus()
        klipper = bus.get_object("org.kde.klipper", "/klipper")
        iface = dbus.Interface(klipper, "org.kde.klipper.klipper")
        return str(iface.getClipboardContents())
    except Exception:
        pass

    # 2. wl-paste
    if shutil.which("wl-paste"):
        try:
            res = subprocess.run(["wl-paste", "--no-newline"], capture_output=True, text=True, timeout=1)
            if res.returncode == 0:
                return res.stdout
        except Exception:
            pass

    # 3. xclip
    if shutil.which("xclip"):
        try:
            res = subprocess.run(["xclip", "-selection", "clipboard", "-o"], capture_output=True, text=True, timeout=1)
            if res.returncode == 0:
                return res.stdout
        except Exception:
            pass

    return None


def copy_to_clipboard(text: str) -> None:
    """Copy text to clipboard."""
    # 1. KDE Klipper D-Bus
    try:
        import dbus
        bus = dbus.SessionBus()
        klipper = bus.get_object("org.kde.klipper", "/klipper")
        iface = dbus.Interface(klipper, "org.kde.klipper.klipper")
        iface.setClipboardContents(text)
        return
    except Exception:
        pass

    # 2. wl-copy
    if shutil.which("wl-copy"):
        try:
            p = subprocess.Popen(["wl-copy"], stdin=subprocess.PIPE)
            p.communicate(input=text.encode("utf-8"), timeout=1)
            return
        except Exception:
            pass

    # 3. xclip
    if shutil.which("xclip"):
        try:
            p = subprocess.Popen(["xclip", "-selection", "clipboard"], stdin=subprocess.PIPE)
            p.communicate(input=text.encode("utf-8"), timeout=1)
            return
        except Exception:
            pass


def trigger_paste_keystroke() -> None:
    """Simulate paste keystroke (Ctrl+V or Shift+Insert)."""
    if shutil.which("wtype"):
        try:
            subprocess.run(["wtype", "-M", "ctrl", "-k", "v", "-m", "ctrl"], check=False)
            return
        except Exception:
            pass

    if shutil.which("ydotool"):
        try:
            subprocess.run(["ydotool", "key", "29:1", "47:1", "47:0", "29:0"], check=False)
            return
        except Exception:
            pass

    if shutil.which("xdotool"):
        try:
            subprocess.run(["xdotool", "key", "ctrl+v"], check=False)
            return
        except Exception:
            pass

    # Fallback: pynput controller
    try:
        from pynput.keyboard import Controller, Key
        kb = Controller()
        kb.press(Key.ctrl)
        kb.press('v')
        time.sleep(0.02)
        kb.release('v')
        kb.release(Key.ctrl)
    except Exception as e:
        logger.debug("pynput keystroke failed: %s", e)


def paste_text(text: str) -> None:
    """Inject text into active field and restore original clipboard afterwards."""
    # 1. Backup existing user clipboard
    old_clipboard = get_current_clipboard()

    try:
        # 2. Set transcribed text to clipboard
        copy_to_clipboard(text)
        time.sleep(0.05)

        # 3. Send paste keystroke
        trigger_paste_keystroke()

        # 4. Wait briefly for target app to consume the paste event
        time.sleep(0.2)
    finally:
        # 5. Restore original clipboard so STT doesn't clog clipboard history
        if old_clipboard is not None:
            copy_to_clipboard(old_clipboard)
            logger.info("Restored previous user clipboard contents.")
