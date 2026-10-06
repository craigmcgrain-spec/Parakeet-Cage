"""Clipboard write + paste keystroke injection with multi-backend fallbacks."""

import logging
import os
import shutil
import subprocess
import time

logger = logging.getLogger(__name__)


class PasteError(Exception):
    """Raised when clipboard copy fails."""


def copy_to_clipboard(text: str) -> None:
    """Copy text to system clipboard across Wayland and X11."""
    # 1. Try wl-copy (Wayland native)
    if shutil.which("wl-copy"):
        try:
            p = subprocess.Popen(["wl-copy"], stdin=subprocess.PIPE)
            p.communicate(input=text.encode("utf-8"), timeout=2)
            if p.returncode == 0:
                logger.info("Copied '%s' via wl-copy", text)
                return
        except Exception as e:
            logger.debug("wl-copy failed: %s", e)

    # 2. Try xclip (X11 / Xwayland)
    if shutil.which("xclip"):
        try:
            p = subprocess.Popen(["xclip", "-selection", "clipboard"], stdin=subprocess.PIPE)
            p.communicate(input=text.encode("utf-8"), timeout=2)
            if p.returncode == 0:
                logger.info("Copied '%s' via xclip", text)
                return
        except Exception as e:
            logger.debug("xclip failed: %s", e)

    # 3. Try xsel
    if shutil.which("xsel"):
        try:
            p = subprocess.Popen(["xsel", "--clipboard", "--input"], stdin=subprocess.PIPE)
            p.communicate(input=text.encode("utf-8"), timeout=2)
            if p.returncode == 0:
                logger.info("Copied '%s' via xsel", text)
                return
        except Exception as e:
            logger.debug("xsel failed: %s", e)

    # 4. Fallback to GTK Clipboard in memory
    try:
        import gi
        try:
            gi.require_version("Gtk", "3.0")
        except ValueError:
            pass
        from gi.repository import Gtk, Gdk

        clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        clipboard.set_text(text, -1)
        clipboard.store()
        logger.info("Copied '%s' via Gtk.Clipboard", text)
        return
    except Exception as e:
        logger.debug("Gtk clipboard fallback failed: %s", e)

    raise PasteError("No supported clipboard utility found (wl-copy, xclip, xsel, or Gtk).")


def trigger_paste_keystroke() -> None:
    """Simulate Ctrl+V keystroke if tools are installed."""
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


def paste_text(text: str) -> None:
    """Write text to clipboard and attempt keystroke paste."""
    copy_to_clipboard(text)
    # Give the compositor a moment to process the clipboard buffer before triggering paste
    time.sleep(0.05)
    trigger_paste_keystroke()
