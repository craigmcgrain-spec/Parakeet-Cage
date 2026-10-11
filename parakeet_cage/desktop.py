"""Desktop integration: the shipped .desktop template and the application icon.

Both the CLI installer (per-user menu entry) and `packaging/build_appimage.sh`
(bundled entry) render the same `parakeet-cage.desktop` template and draw the
same icon, so the two launch paths cannot drift apart.

Standard library plus pillow - and pillow is imported lazily so the installer
still runs in a fresh clone before any dependency exists.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional


ICON_NAME = "parakeet-cage"
ICON_SIZE = 256
TEMPLATE_PATH = Path(__file__).with_name("parakeet-cage.desktop")

# A line containing one of these is dropped when its value is empty, so optional
# keys (TryExec, which must be a bare path) simply do not appear.
_OPTIONAL = ("@TRYEXEC@",)
_ICON_FILL = "#2ecc71"
_ICON_OUTLINE = "#27ae60"


def render_entry(exec_path: str, *, tryexec: str = "", icon: str = ICON_NAME) -> str:
    """Fill the template with a launch command; empty optional fields are omitted."""
    values = {"@EXEC@": exec_path, "@TRYEXEC@": tryexec, "@ICON@": icon}
    lines = []
    for line in TEMPLATE_PATH.read_text(encoding="utf-8").splitlines():
        if any(token in line and not values[token] for token in _OPTIONAL):
            continue
        for token, value in values.items():
            line = line.replace(token, value)
        lines.append(line)
    return "\n".join(lines) + "\n"


def write_icon(path, size: int = ICON_SIZE) -> Path:
    """Draw the application icon; raises ImportError when pillow is unavailable."""
    from PIL import Image, ImageDraw  # noqa: PLC0415 - optional at install time

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    margin = round(size / 16)
    image = Image.new("RGBA", (size, size), color=(0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse(
        [margin, margin, size - margin, size - margin],
        fill=_ICON_FILL,
        outline=_ICON_OUTLINE,
        width=round(size / 32),
    )
    image.save(path, format="PNG")
    return path


def icon_dir(data_home: Path, size: int = ICON_SIZE) -> Path:
    """Where the icon must live for `Icon=parakeet-cage` to resolve."""
    return Path(data_home) / "icons" / "hicolor" / f"{size}x{size}" / "apps"


def applications_dir(data_home: Optional[Path] = None) -> Path:
    """The per-user applications directory holding the menu entries."""
    root = Path(data_home) if data_home else Path(
        os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share"
    )
    return root / "applications"
