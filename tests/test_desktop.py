"""Tests for parakeet_cage.desktop - the shipped menu entry and icon."""
from pathlib import Path

import pytest

from parakeet_cage import desktop


def _fields(text: str) -> dict:
    return dict(
        line.split("=", 1)
        for line in text.splitlines()
        if "=" in line and not line.startswith("#")
    )


def test_render_entry_fills_every_placeholder():
    entry = desktop.render_entry("/home/u/.local/bin/parakeet-cage", tryexec="/home/u/.local/bin/parakeet-cage")
    assert "@" not in entry
    fields = _fields(entry)
    assert fields["Type"] == "Application"
    assert fields["Name"] == "Parakeet Cage"
    assert fields["Exec"] == "/home/u/.local/bin/parakeet-cage"
    assert fields["TryExec"] == "/home/u/.local/bin/parakeet-cage"
    assert fields["Icon"] == desktop.ICON_NAME
    assert fields["Terminal"] == "false"
    assert "Utility" in fields["Categories"]
    assert "dictation" in fields["Keywords"]


def test_render_entry_omits_tryexec_when_it_would_be_a_command_line():
    """TryExec must be a bare path, so it is dropped for `python3 -m ...`."""
    entry = desktop.render_entry("/usr/bin/python3 -m parakeet_cage.app")
    assert "TryExec" not in entry
    assert _fields(entry)["Exec"] == "/usr/bin/python3 -m parakeet_cage.app"


def test_render_entry_accepts_a_custom_icon_name():
    entry = desktop.render_entry("/usr/bin/parakeet-cage", icon="other")
    assert _fields(entry)["Icon"] == "other"


def test_icon_dir_matches_the_icon_name_lookup(tmp_path):
    assert desktop.icon_dir(tmp_path) == tmp_path / "icons" / "hicolor" / "256x256" / "apps"
    assert desktop.ICON_NAME == "parakeet-cage"


def test_applications_dir_follows_xdg_data_home(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    assert desktop.applications_dir() == tmp_path / "applications"
    assert desktop.applications_dir(tmp_path) == tmp_path / "applications"


def test_write_icon_writes_a_png(tmp_path):
    pytest.importorskip("PIL")
    path = desktop.write_icon(tmp_path / "deep" / "parakeet-cage.png")
    assert path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")


def test_write_icon_scales_with_the_requested_size(tmp_path):
    pillow = pytest.importorskip("PIL.Image")
    path = desktop.write_icon(tmp_path / "icon.png", size=64)
    with pillow.open(path) as image:
        assert image.size == (64, 64)


def test_template_is_inside_the_package():
    assert Path(desktop.TEMPLATE_PATH).parent == Path(desktop.__file__).parent
    assert desktop.TEMPLATE_PATH.is_file()
