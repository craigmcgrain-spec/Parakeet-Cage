"""Clipboard write + paste keystroke injection with previous clipboard restoration."""

import logging
import os
import shutil
import subprocess
import threading
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


# --- keystroke injection ----------------------------------------------------

# Linux evdev keycodes (linux/input-event-codes.h).
KEY_LEFTCTRL = 29
KEY_V = 47

PORTAL_BUS_NAME = "org.freedesktop.portal.Desktop"
PORTAL_OBJECT_PATH = "/org/freedesktop/portal/desktop"
PORTAL_REQUEST_IFACE = "org.freedesktop.portal.Request"
PORTAL_REMOTE_DESKTOP_IFACE = "org.freedesktop.portal.RemoteDesktop"
PORTAL_DEVICE_KEYBOARD = 1

# Start() may block on the portal's consent dialog; later calls must not.
PORTAL_START_TIMEOUT = 30.0
PORTAL_CALL_TIMEOUT = 5.0
# After a failure (user denied, portal restarted) stop retrying for a while so we
# never spam consent dialogs; the remaining backends still get their chance.
PORTAL_RETRY_COOLDOWN = 60.0


class PortalError(RuntimeError):
    """Raised when the xdg-desktop-portal RemoteDesktop session is unusable."""


def _import_dbus():
    """python-dbus attached to the GLib main loop, or None when unavailable."""
    try:
        import dbus
        import dbus.mainloop.glib
    except ImportError as e:
        logger.debug("python-dbus unavailable, cannot use portal injection: %s", e)
        return None
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    return dbus


class PortalKeyboard:
    """Keyboard injection through org.freedesktop.portal.RemoteDesktop.

    This is the sanctioned Wayland path: it reaches native Wayland clients on
    compositors (KWin, Mutter, wlroots) that implement neither
    zwp_virtual_keyboard_v1 nor X11 keyboard grabs, and it needs no root,
    /dev/uinput or helper binary. One keyboard-only session is kept for the
    lifetime of the process; the portal asks the user to confirm it at most once.
    """

    def __init__(self, bus=None, dbus_module=None):
        self._bus = bus
        self._dbus = dbus_module
        self._remote = None
        self._session = None
        self._pressed = set()
        self._token_counter = 0
        self._lock = threading.Lock()

    def key(self, keycode: int, pressed: bool) -> None:
        """Press or release one evdev keycode on the focused client."""
        with self._lock:
            self._ensure_session()
            self._notify(keycode, pressed)
            if pressed:
                self._pressed.add(keycode)
            else:
                self._pressed.discard(keycode)

    def release_all(self) -> None:
        """Best-effort release of keys we still hold; never opens a new session."""
        with self._lock:
            if self._session is None:
                return
            for keycode in sorted(self._pressed):
                try:
                    self._notify(keycode, False)
                except PortalError:
                    break
            self._pressed.clear()

    def reset(self) -> None:
        """Drop the cached session so the next call builds a fresh one."""
        with self._lock:
            self._remote = None
            self._session = None
            self._pressed.clear()

    # -- internals -----------------------------------------------------------

    def _ensure_session(self) -> None:
        if self._session is not None:
            return
        if self._bus is None:
            self._bus = self._connect_bus()
        remote = self._bus.get_object(PORTAL_BUS_NAME, PORTAL_OBJECT_PATH)
        iface = self._dbus.Interface(remote, PORTAL_REMOTE_DESKTOP_IFACE)

        # xdg-desktop-portal dies with "Remote peer disconnected" when
        # session_handle_token is missing, even though the spec calls it optional.
        path = iface.CreateSession(self._options("create", {
            "session_handle_token": self._dbus.String(self._next_token("session")),
        }))
        response, results = self._await_response(path, PORTAL_CALL_TIMEOUT)
        if response != 0:
            raise PortalError(f"CreateSession refused with response {response}")
        session = results.get("session_handle")
        if session is None:
            raise PortalError("CreateSession returned no session handle")

        path = iface.SelectDevices(
            session, self._options("devices", {"types": self._dbus.UInt32(PORTAL_DEVICE_KEYBOARD)})
        )
        response, _ = self._await_response(path, PORTAL_CALL_TIMEOUT)
        if response != 0:
            raise PortalError(f"SelectDevices refused with response {response}")

        path = iface.Start(session, "", self._options("start"))
        response, _ = self._await_response(path, PORTAL_START_TIMEOUT)
        if response != 0:
            raise PortalError(f"Start refused with response {response} (denied or timed out)")

        self._remote = iface
        self._session = session
        logger.debug("RemoteDesktop keyboard session established: %s", session)

    def _connect_bus(self):
        if self._dbus is None:
            self._dbus = _import_dbus()
        if self._dbus is None:
            raise PortalError("python-dbus is not available")
        try:
            # private=True on purpose: dbus.SessionBus() is a process-wide singleton,
            # and the clipboard helpers create it before a main loop exists, which
            # makes it permanently unable to receive the portal's Response signals.
            return self._dbus.SessionBus(private=True)
        except Exception as e:
            raise PortalError(f"cannot connect to the session bus: {e}")

    def _next_token(self, prefix: str) -> str:
        self._token_counter += 1
        return f"pc_{prefix}_{self._token_counter}"

    def _options(self, prefix: str, extra=None):
        options = {"handle_token": self._dbus.String(self._next_token(prefix))}
        if extra:
            options.update(extra)
        return options

    def _await_response(self, request_path, timeout: float):
        """Wait for the portal's Response signal, dispatched by the GLib main loop."""
        done = threading.Event()
        box = {}

        def on_response(response, results):
            box["response"] = int(response)
            box["results"] = results
            done.set()

        self._bus.add_signal_receiver(
            on_response,
            signal_name="Response",
            dbus_interface=PORTAL_REQUEST_IFACE,
            path=str(request_path),
        )
        try:
            if not done.wait(timeout):
                raise PortalError(f"portal did not answer within {timeout:.0f}s")
        finally:
            self._bus.remove_signal_receiver(
                on_response,
                signal_name="Response",
                dbus_interface=PORTAL_REQUEST_IFACE,
                path=str(request_path),
            )
        return box.get("response", 2), box.get("results", {})

    def _notify(self, keycode: int, pressed: bool) -> None:
        try:
            self._remote.NotifyKeyboardKeycode(
                self._session, {}, self._dbus.Int32(keycode), self._dbus.UInt32(1 if pressed else 0)
            )
        except Exception as e:
            # A dead session must not poison every later dictation.
            self._remote = None
            self._session = None
            raise PortalError(f"NotifyKeyboardKeycode failed: {e}")


_portal_keyboard: Optional[PortalKeyboard] = None
_portal_keyboard_lock = threading.Lock()
_portal_retry_after = 0.0


def _portal_ctrl_v() -> bool:
    """Send Ctrl+V through the portal virtual keyboard. False when unusable."""
    global _portal_keyboard, _portal_retry_after
    if time.monotonic() < _portal_retry_after:
        return False

    with _portal_keyboard_lock:
        if _portal_keyboard is None:
            _portal_keyboard = PortalKeyboard()
        keyboard = _portal_keyboard

    try:
        for keycode, pressed in ((KEY_LEFTCTRL, True), (KEY_V, True), (KEY_V, False), (KEY_LEFTCTRL, False)):
            keyboard.key(keycode, pressed)
        return True
    except PortalError as e:
        logger.warning("xdg-desktop-portal keyboard injection failed: %s", e)
        keyboard.release_all()
        _portal_retry_after = time.monotonic() + PORTAL_RETRY_COOLDOWN
        return False


def _pynput_paste() -> bool:
    """X11/XTest fallback. Only reaches X11/Xwayland clients, never native Wayland ones."""
    try:
        from pynput.keyboard import Controller, Key
    except Exception as e:
        logger.debug("pynput unavailable: %s", e)
        return False

    try:
        kb = Controller()
        kb.press(Key.ctrl)
        kb.press("v")
        time.sleep(0.03)
        kb.release("v")
        kb.release(Key.ctrl)
        return True
    except Exception as e:
        logger.debug("pynput keystroke failed: %s", e)
        return False


def trigger_paste_keystroke() -> bool:
    """Inject Ctrl+V into the focused window. Returns True when a backend reported success."""
    # 1. Portal virtual keyboard — the only dependency-free way to reach *native*
    #    Wayland clients (KWin rejects wtype's zwp_virtual_keyboard_v1).
    if os.environ.get("WAYLAND_DISPLAY") and _portal_ctrl_v():
        logger.info("Pasted via xdg-desktop-portal RemoteDesktop")
        return True

    # 2. wtype (only for compositors implementing zwp_virtual_keyboard_v1)
    if shutil.which("wtype"):
        try:
            res = subprocess.run(
                ["wtype", "-M", "ctrl", "-k", "v", "-m", "ctrl"],
                capture_output=True,
                check=False,
                timeout=5,
            )
            if res.returncode == 0:
                logger.info("Pasted via wtype")
                return True
            logger.warning("wtype exited %d: %s", res.returncode,
                           res.stderr.decode(errors="replace").strip())
        except Exception as e:
            logger.warning("wtype injection failed: %s", e)

    # 3. xdotool (X11 / Xwayland windows only)
    if shutil.which("xdotool"):
        try:
            res = subprocess.run(["xdotool", "key", "ctrl+v"], capture_output=True,
                                 check=False, timeout=5)
            if res.returncode == 0:
                logger.info("Pasted via xdotool")
                return True
            logger.warning("xdotool exited %d", res.returncode)
        except Exception as e:
            logger.warning("xdotool injection failed: %s", e)

    # 4. pynput/XTest — only meaningful on X11 sessions.
    if os.environ.get("WAYLAND_DISPLAY"):
        logger.warning("Skipping pynput fallback: XTest cannot reach native Wayland windows.")
    elif _pynput_paste():
        logger.info("Pasted via pynput")
        return True

    logger.error(
        "No working key-injection backend: need xdg-desktop-portal with RemoteDesktop keyboard "
        "support, wtype, or xdotool/pynput on X11. Transcription remains on the clipboard for manual paste."
    )
    return False


def paste_text(text: str) -> bool:
    """Inject text into active field and restore original clipboard afterwards.

    Returns True when the paste keystroke was injected, False when the text could
    not be delivered — in which case it is deliberately left on the clipboard.
    """
    # 1. Backup existing user clipboard
    old_clipboard = get_current_clipboard()

    # 2. Set transcribed text to clipboard
    copy_to_clipboard(text)
    time.sleep(0.05)

    # 3. Send paste keystroke
    injected = trigger_paste_keystroke()

    if not injected:
        logger.error("Could not paste into the focused window; '%s' is on the clipboard, "
                     "paste it manually with Ctrl+V.", text)
        return False

    # 4. Wait for the target app to consume the paste event. Measured on this
    #    session: a target that is busy for ~200ms pastes the *restored* clipboard
    #    instead, so give it room before overwriting the selection again.
    time.sleep(0.5)

    # 5. Restore original clipboard so STT doesn't clog clipboard history
    if old_clipboard is not None:
        copy_to_clipboard(old_clipboard)
        logger.info("Restored previous user clipboard contents.")
    return True
