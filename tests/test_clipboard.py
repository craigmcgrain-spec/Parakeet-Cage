"""Tests for parakeet_cage.clipboard."""

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from parakeet_cage import clipboard
from parakeet_cage.clipboard import PasteError, copy_to_clipboard, paste_text, trigger_paste_keystroke


def test_copy_to_clipboard_wl_copy():
    with patch("dbus.SessionBus", side_effect=Exception("no dbus")), \
         patch("shutil.which") as mock_which, \
         patch("subprocess.Popen") as mock_popen:
        mock_which.side_effect = lambda cmd: "/usr/bin/wl-copy" if cmd == "wl-copy" else None
        proc = MagicMock()
        proc.returncode = 0
        proc.communicate.return_value = (b"", b"")
        mock_popen.return_value = proc

        copy_to_clipboard("hello world")
        mock_popen.assert_called_once()
        args, kwargs = mock_popen.call_args
        assert args[0] == ["wl-copy"]


def test_copy_to_clipboard_xclip_fallback():
    with patch("dbus.SessionBus", side_effect=Exception("no dbus")), \
         patch("shutil.which") as mock_which, \
         patch("subprocess.Popen") as mock_popen:
        mock_which.side_effect = lambda cmd: "/usr/bin/xclip" if cmd == "xclip" else None
        proc = MagicMock()
        proc.returncode = 0
        proc.communicate.return_value = (b"", b"")
        mock_popen.return_value = proc

        copy_to_clipboard("hello x11")
        mock_popen.assert_called_once()
        args, kwargs = mock_popen.call_args
        assert args[0] == ["xclip", "-selection", "clipboard"]


def test_paste_text_calls_copy_and_restores():
    with patch("parakeet_cage.clipboard.get_current_clipboard", return_value="original text"), \
         patch("parakeet_cage.clipboard.copy_to_clipboard") as mock_copy, \
         patch("parakeet_cage.clipboard.trigger_paste_keystroke", return_value=True) as mock_trigger:
        paste_text("test transcription")
        assert mock_copy.call_count == 2
        mock_copy.assert_any_call("test transcription")
        mock_copy.assert_any_call("original text")
        mock_trigger.assert_called_once()


# --- keystroke injection backends -------------------------------------------


class _FakeDbusModule:
    """Stand-in for the dbus module: only the wrappers PortalKeyboard uses."""

    String = staticmethod(lambda value: value)
    Int32 = staticmethod(lambda value: value)
    UInt32 = staticmethod(lambda value: value)
    Interface = staticmethod(lambda obj, name: obj.interface)


class _FakeRemoteDesktop:
    """Fake org.freedesktop.portal.RemoteDesktop interface."""

    def __init__(self, notify_error=None):
        self.interface = self
        self.notify_error = notify_error
        self.calls = []
        self.sessions = 0
        self.keys = []

    def CreateSession(self, options):
        self.sessions += 1
        self.calls.append(("CreateSession", options))
        return "/request/create"

    def SelectDevices(self, session, options):
        self.calls.append(("SelectDevices", options))
        return "/request/devices"

    def Start(self, session, parent_window, options):
        self.calls.append(("Start", options))
        return "/request/start"

    def NotifyKeyboardKeycode(self, session, options, keycode, state):
        if self.notify_error:
            raise self.notify_error
        self.keys.append((int(keycode), int(state)))


class _FakeBus:
    """Session bus stub that answers each portal request as soon as it is awaited."""

    RESPONSES = {
        "/request/create": (0, {"session_handle": "/session/fake"}),
        "/request/devices": (0, {}),
        "/request/start": (0, {}),
    }

    def __init__(self, remote, overrides=None, silent=False):
        self.remote = remote
        self.overrides = overrides or {}
        self.silent = silent
        self.removed = 0

    def get_object(self, name, path):
        return self.remote

    def add_signal_receiver(self, handler, **kwargs):
        if self.silent:
            return
        options = self.overrides.get(kwargs.get("path"), self.RESPONSES.get(kwargs.get("path"), (2, {})))
        handler(*options)

    def remove_signal_receiver(self, handler, **kwargs):
        self.removed += 1


class _RecordingDbusModule(_FakeDbusModule):
    """Records how the session bus was requested."""

    def __init__(self):
        self.session_bus_kwargs = None

    def SessionBus(self, **kwargs):
        self.session_bus_kwargs = kwargs
        return _FakeBus(_FakeRemoteDesktop())


def _portal_keyboard(**kwargs):
    return clipboard.PortalKeyboard(dbus_module=_FakeDbusModule(), **kwargs)


def test_portal_keyboard_owns_a_private_mainloop_attached_bus():
    """The shared SessionBus singleton is created before the GLib loop exists, so it
    can never receive the portal's Response signals; the client must own a connection."""
    recorder = _RecordingDbusModule()
    kb = clipboard.PortalKeyboard(dbus_module=recorder)

    kb.key(clipboard.KEY_V, True)

    assert recorder.session_bus_kwargs == {"private": True}


def test_portal_keyboard_reuses_one_keyboard_session():
    remote = _FakeRemoteDesktop()
    kb = _portal_keyboard(bus=_FakeBus(remote))

    kb.key(clipboard.KEY_LEFTCTRL, True)
    kb.key(clipboard.KEY_V, True)
    kb.key(clipboard.KEY_V, False)
    kb.key(clipboard.KEY_LEFTCTRL, False)

    assert remote.sessions == 1
    assert [call[0] for call in remote.calls] == ["CreateSession", "SelectDevices", "Start"]
    assert remote.calls[1][1]["types"] == clipboard.PORTAL_DEVICE_KEYBOARD
    assert remote.keys == [(29, 1), (47, 1), (47, 0), (29, 0)]


def test_portal_keyboard_sends_session_handle_token():
    """Missing session_handle_token makes xdg-desktop-portal die (Remote peer disconnected)."""
    remote = _FakeRemoteDesktop()
    kb = _portal_keyboard(bus=_FakeBus(remote, overrides={"/request/start": (1, {})}))

    with pytest.raises(clipboard.PortalError):
        kb.key(clipboard.KEY_V, True)

    create_options = remote.calls[0][1]
    assert create_options["session_handle_token"].startswith("pc_session_")
    assert create_options["handle_token"].startswith("pc_create_")


def test_portal_keyboard_reports_denied_start_and_retries_later():
    remote = _FakeRemoteDesktop()
    bus = _FakeBus(remote, overrides={"/request/start": (1, {})})
    kb = _portal_keyboard(bus=bus)

    with pytest.raises(clipboard.PortalError, match="Start refused"):
        kb.key(clipboard.KEY_V, True)

    # a later attempt must build a fresh session instead of staying broken
    bus.overrides = {}
    kb.key(clipboard.KEY_V, True)
    assert remote.sessions == 2
    assert remote.keys == [(47, 1)]


def test_portal_keyboard_drops_dead_session_after_notify_failure():
    remote = _FakeRemoteDesktop(notify_error=RuntimeError("session gone"))
    kb = _portal_keyboard(bus=_FakeBus(remote))

    with pytest.raises(clipboard.PortalError, match="NotifyKeyboardKeycode failed"):
        kb.key(clipboard.KEY_V, True)

    remote.notify_error = None
    kb.key(clipboard.KEY_V, True)
    assert remote.sessions == 2


def test_portal_keyboard_times_out_when_portal_never_answers(monkeypatch):
    monkeypatch.setattr(clipboard, "PORTAL_CALL_TIMEOUT", 0.05)
    kb = _portal_keyboard(bus=_FakeBus(_FakeRemoteDesktop(), silent=True))

    with pytest.raises(clipboard.PortalError, match="did not answer"):
        kb.key(clipboard.KEY_V, True)


def test_portal_keyboard_releases_held_modifiers():
    remote = _FakeRemoteDesktop()
    kb = _portal_keyboard(bus=_FakeBus(remote))

    kb.key(clipboard.KEY_LEFTCTRL, True)
    kb.release_all()

    assert remote.keys == [(29, 1), (29, 0)]


def test_trigger_paste_prefers_portal_on_wayland(monkeypatch):
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")

    with patch("parakeet_cage.clipboard._portal_ctrl_v", return_value=True) as mock_portal, \
         patch("parakeet_cage.clipboard.subprocess.run") as mock_run, \
         patch("parakeet_cage.clipboard.shutil.which", return_value="/usr/bin/wtype"):
        assert trigger_paste_keystroke() is True

    mock_portal.assert_called_once()
    mock_run.assert_not_called()


def test_trigger_paste_falls_back_to_wtype_when_portal_fails(monkeypatch):
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")

    with patch("parakeet_cage.clipboard._portal_ctrl_v", return_value=False), \
         patch("parakeet_cage.clipboard.shutil.which",
               side_effect=lambda cmd: "/usr/bin/wtype" if cmd == "wtype" else None), \
         patch("parakeet_cage.clipboard.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stderr=b"")

        assert trigger_paste_keystroke() is True

    assert mock_run.call_args[0][0] == ["wtype", "-M", "ctrl", "-k", "v", "-m", "ctrl"]


def test_trigger_paste_skips_portal_on_x11(monkeypatch):
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)

    with patch("parakeet_cage.clipboard._portal_ctrl_v") as mock_portal, \
         patch("parakeet_cage.clipboard._pynput_paste", return_value=False), \
         patch("parakeet_cage.clipboard.shutil.which", return_value=None):
        assert trigger_paste_keystroke() is False

    mock_portal.assert_not_called()


def test_trigger_paste_reports_failure_when_no_backend(monkeypatch):
    """A silent no-op is the bug: injection must report failure."""
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")

    with patch("parakeet_cage.clipboard._portal_ctrl_v", return_value=False), \
         patch("parakeet_cage.clipboard.shutil.which", return_value=None):
        assert trigger_paste_keystroke() is False


def test_pynput_fallback_skipped_on_wayland(monkeypatch):
    """XTEST/pynput can never reach native Wayland windows; don't pretend it worked."""
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")

    with patch("parakeet_cage.clipboard._portal_ctrl_v", return_value=False), \
         patch("parakeet_cage.clipboard.shutil.which", return_value=None), \
         patch("parakeet_cage.clipboard._pynput_paste") as mock_pynput:
        assert trigger_paste_keystroke() is False
        mock_pynput.assert_not_called()


def test_pynput_fallback_used_on_x11(monkeypatch):
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)

    with patch("parakeet_cage.clipboard.shutil.which", return_value=None), \
         patch("parakeet_cage.clipboard._pynput_paste", return_value=True) as mock_pynput:
        assert trigger_paste_keystroke() is True
        mock_pynput.assert_called_once()


def test_paste_text_keeps_transcription_on_clipboard_when_injection_fails():
    """If the keystroke never lands, the text must stay pasteable by hand."""
    with patch("parakeet_cage.clipboard.get_current_clipboard", return_value="original text"), \
         patch("parakeet_cage.clipboard.copy_to_clipboard") as mock_copy, \
         patch("parakeet_cage.clipboard.trigger_paste_keystroke", return_value=False):
        assert paste_text("test transcription") is False

    mock_copy.assert_called_once_with("test transcription")
