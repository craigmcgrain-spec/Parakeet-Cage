"""Interactive CLI installer for Parakeet Cage.

Started by `./install.sh` inside a git clone, and afterwards available as the
`parakeet-cage-install` console script. Standard library plus
`parakeet_cage.model_store` only: it must run in a fresh clone, before any
dependency (or this package) has been installed.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import importlib.util
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
from typing import Any, Callable, List, Optional, Sequence, Tuple

from parakeet_cage import model_store


PYTHON_MIN = (3, 11)

# Distro packages for the bits pip cannot provide: GTK/PyGObject and dbus-python
# are compiled against the system interpreter. Keyed by /etc/os-release ID.
SYSTEM_PACKAGES = {
    "fedora": ("sudo", "dnf", "install", "python3-gobject", "gtk3", "dbus-python", "wl-clipboard"),
    "rhel": ("sudo", "dnf", "install", "python3-gobject", "gtk3", "dbus-python", "wl-clipboard"),
    "centos": ("sudo", "dnf", "install", "python3-gobject", "gtk3", "dbus-python", "wl-clipboard"),
    "debian": ("sudo", "apt-get", "install", "python3-gi", "gir1.2-gtk-3.0", "python3-dbus", "wl-clipboard"),
    "ubuntu": ("sudo", "apt-get", "install", "python3-gi", "gir1.2-gtk-3.0", "python3-dbus", "wl-clipboard"),
    "arch": ("sudo", "pacman", "-S", "--needed", "python-gobject", "gtk3", "python-dbus", "wl-clipboard"),
    "manjaro": ("sudo", "pacman", "-S", "--needed", "python-gobject", "gtk3", "python-dbus", "wl-clipboard"),
}


@dataclass
class Requirement:
    """One preflight line."""

    label: str
    ok: bool
    detail: str
    system: bool = False      # comes from a distro package, not pip
    required: bool = True     # False: reported, never a failure


def _module_available(module: str) -> bool:
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False


def distro_id() -> str:
    """`ID` from /etc/os-release, lowercased, or "" when unreadable."""
    try:
        for line in Path("/etc/os-release").read_text(encoding="utf-8").splitlines():
            key, _, value = line.partition("=")
            if key.strip() == "ID":
                return value.strip().strip('"').lower()
    except OSError:
        pass
    return ""


def system_package_command() -> Optional[Tuple[str, ...]]:
    """The distro command that installs the system-level dependencies."""
    return SYSTEM_PACKAGES.get(distro_id())


def _portal_keyboard_available(run: Callable[..., Any]) -> bool:
    if shutil.which("busctl") is None:
        return False
    try:
        completed = run(
            [
                "busctl", "--user", "introspect",
                "org.freedesktop.portal.Desktop", "/org/freedesktop/portal/desktop",
            ],
            capture_output=True, text=True, timeout=20,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return completed.returncode == 0 and "RemoteDesktop" in (completed.stdout or "")


def collect_requirements(run: Callable[..., Any] = subprocess.run) -> List[Requirement]:
    """Preflight checks, without importing anything that needs a display."""
    python_ok = sys.version_info >= PYTHON_MIN
    return [
        Requirement("Python", python_ok, platform.python_version(), required=True),
        Requirement("pip", _module_available("pip"), "python3 -m pip", required=True),
        Requirement("git", shutil.which("git") is not None, "git clone support"),
        Requirement(
            "git-lfs",
            shutil.which("git-lfs") is not None,
            "optional: lets the clone carry the weights itself",
            required=False,
        ),
        Requirement(
            "PyGObject (GTK 3)", _module_available("gi"),
            "python3-gobject - tray icon and settings dialog",
            system=True,
        ),
        Requirement(
            "dbus-python", _module_available("dbus"),
            "dbus-python - Klipper clipboard, portal virtual keyboard",
            system=True,
        ),
        Requirement(
            "sounddevice", _module_available("sounddevice"),
            "pip dependency - microphone capture",
        ),
        Requirement(
            "pynput (X11 fallback)", _module_available("pynput"),
            "optional extra, needs python3-devel + gcc to build: pip install --user -e '.[x11]'",
            required=False,
        ),
        Requirement(
            "wl-clipboard", shutil.which("wl-copy") is not None,
            "wl-clipboard - clipboard on Wayland",
            system=True, required=False,
        ),
        Requirement(
            "xdg-desktop-portal keyboard",
            _portal_keyboard_available(run),
            "portal RemoteDesktop - keystroke injection on Wayland",
            system=True, required=False,
        ),
        Requirement(
            "graphical session",
            bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")),
            "DISPLAY or WAYLAND_DISPLAY",
            required=False,
        ),
    ]


class Installer:
    """The whole installation, with its side effects injected for testing."""

    def __init__(
        self,
        repo_root: Path,
        *,
        assume_yes: bool = False,
        skip_model: bool = False,
        skip_app: bool = False,
        interactive: bool = True,
        log: Callable[[str], None] = print,
        ask_fn: Optional[Callable[[str], str]] = None,
        run: Callable[..., Any] = subprocess.run,
        fetch: Callable[..., Any] = model_store.fetch_model,
        requirements: Optional[Callable[[], List[Requirement]]] = None,
    ):
        self.repo_root = Path(repo_root)
        self.assume_yes = assume_yes
        self.skip_model = skip_model
        self.skip_app = skip_app
        self.interactive = interactive
        self.log = log
        self.ask_fn = ask_fn or input
        self.run = run
        self.fetch = fetch
        self.requirements = requirements or (lambda: collect_requirements(run))

    # -- helpers ------------------------------------------------------------
    def ask(self, question: str, *, default: bool = True) -> bool:
        """Yes/no question; `--yes` answers yes, a blank line takes the default."""
        if self.assume_yes:
            self.log(f"{question} [auto-yes]")
            return True
        answered = self.ask_fn(f"{question} [{'Y/n' if default else 'y/N'}] ").strip().lower()
        if not answered:
            return default
        return answered in ("y", "yes")

    def model_skip_note(self) -> None:
        self.log("  Skipped. Parakeet Cage needs the weights to transcribe; install them later:")
        for line in model_store.WEIGHTS_HINT.splitlines():
            self.log("  " + line.strip())

    # -- stages -------------------------------------------------------------
    def preflight(self) -> int:
        self.log("\nPreflight")
        requirements = self.requirements()
        for req in requirements:
            if req.ok:
                self.log(f"  [ok  ] {req.label}")
            else:
                mark = "warn" if not req.required else "MISS"
                self.log(f"  [{mark}] {req.label}: {req.detail}")

        if any(not r.ok and r.system for r in requirements):
            command = system_package_command()
            if command:
                self.log(f"\n  System packages for '{distro_id()}':")
                self.log("    " + " ".join(command))
                if self.interactive and not self.assume_yes and self.ask("Run that now?", default=False):
                    if self.run(command).returncode == 0:
                        still_missing = [
                            r.label for r in self.requirements()
                            if not r.ok and r.system and r.required
                        ]
                        self.log(
                            "  Installed." if not still_missing
                            else f"  Still missing: {', '.join(still_missing)}"
                        )
                    else:
                        self.log("  ... the command failed; install those packages yourself.")
            else:
                self.log("\n  Install these with your distribution's package manager:")
                self.log("    PyGObject (GTK 3), python3-dbus, wl-clipboard")

        essential = {"Python", "pip"}
        if any(not r.ok and r.label in essential for r in requirements):
            self.log("  Python >= 3.11 with pip is required; install it and re-run.")
            return 1
        return 0

    def install_app(self) -> int:
        if self.skip_app:
            self.log("\nApp install: skipped (--skip-app)")
            return 0
        self.log("\nApp install: pip install --user -e")
        command = [sys.executable, "-m", "pip", "install", "--user", "-e", str(self.repo_root)]
        self.log("  " + " ".join(command))
        if self.run(command).returncode != 0:
            self.log("\n  pip failed. Re-run by hand to see the error:")
            self.log("    " + " ".join(command))
            self.log("  'externally-managed-environment' -> use a virtualenv or pipx instead.")
            self.log("  A dependency that fails to compile -> install python3-devel and gcc.")
            return 1
        bindir = Path.home() / ".local" / "bin"
        if str(bindir) not in os.environ.get("PATH", "").split(os.pathsep):
            self.log(f"\n  Note: {bindir} is not on PATH, so 'parakeet-cage' will not be found:")
            self.log(f'    export PATH="{bindir}:$PATH"')
        return 0

    def install_model(self) -> int:
        self.log("\nModel weights: Parakeet Redux by Moondream (CC-BY-4.0, ~178 MB)")
        in_clone = self.repo_root / "models" / model_store.MODEL_DIR_NAME
        for candidate, where in ((in_clone, "clone"), (model_store.user_model_dir(), "user data")):
            check = model_store.check_weights(candidate)
            if check.ok:
                self.log(f"  Already installed ({where}): {check.detail}")
                return 0

        clone_check = model_store.check_weights(in_clone)
        if clone_check.status == model_store.POINTER:
            self.log(f"  {clone_check.detail}")

        if self.skip_model:
            self.model_skip_note()
            return 0
        if not self.ask(
            "Download the Parakeet Redux weights now"
            " (~178 MB, one time, sha256-verified, from huggingface.co)?"
        ):
            self.model_skip_note()
            return 0

        dest = model_store.user_model_dir()
        self.log(f"  Fetching {model_store.MODEL_REPO}@{model_store.MODEL_REVISION[:7]}")
        self.log(f"  into {dest}")
        try:
            self.fetch(dest, on_progress=model_store.print_progress)
        except model_store.ModelFetchError as exc:
            self.log(f"\n  error: {exc}")
            self.log("  Nothing partial was kept. Re-run ./install.sh to try again.")
            return 3

        check = model_store.check_weights(dest)
        if not check.ok:
            self.log(f"\n  error: {check.detail}")
            return 3
        self.log(f"  Installed {check.detail}")
        return 0

    # -- entry --------------------------------------------------------------
    def run_all(self) -> int:
        self.log(f"Parakeet Cage installer\n  clone: {self.repo_root}")
        if self.preflight():
            return 1
        for stage in (self.install_app, self.install_model):
            code = stage()
            if code:
                return code
        self.log("\nDone. Next steps")
        self.log("  Hold F9 in any text field, speak, release; the text appears at the cursor.")
        self.log("  Tray icon: green idle, red recording, amber transcribing.")
        self.log("  parakeet-cage --dictionary   manage your word list")
        self.log("  The app reads the weights from disk and makes no network calls while running.")
        return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="parakeet-cage-install",
        description="Install Parakeet Cage from a git clone, optionally downloading the model.",
    )
    parser.add_argument("--yes", "-y", action="store_true", help="non-interactive: accept the model download")
    parser.add_argument("--no-model", action="store_true", help="install the app only; never download weights")
    parser.add_argument("--skip-app", action="store_true", help="skip pip; install the weights only")
    args = parser.parse_args(argv)
    if args.yes and args.no_model:
        parser.error("--yes and --no-model contradict each other")

    repo_root = Path(__file__).resolve().parent.parent
    if not (repo_root / "pyproject.toml").is_file():
        print(
            "This installer must run from a Parakeet Cage git clone:\n"
            "  git clone https://github.com/craigmcgrain-spec/Parakeet-Cage.git\n"
            "  cd Parakeet-Cage && ./install.sh",
            file=sys.stderr,
        )
        return 2

    interactive = sys.stdin.isatty()
    if not interactive and not (args.yes or args.no_model):
        print(
            "No terminal to ask the model question on. Pass --yes to download it"
            " or --no-model to skip it.",
            file=sys.stderr,
        )
        return 2

    installer = Installer(
        repo_root,
        assume_yes=args.yes,
        skip_model=args.no_model,
        skip_app=args.skip_app,
        interactive=interactive,
    )
    return installer.run_all()


if __name__ == "__main__":
    sys.exit(main())
