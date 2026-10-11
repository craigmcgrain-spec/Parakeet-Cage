"""Tests for parakeet_cage.install - the CLI installer's decisions, not its side effects."""
import io
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from parakeet_cage import install, model_store


def _sparse(path: Path, size: int) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as handle:
        handle.truncate(size)
    return path


def _weights_in(directory: Path) -> Path:
    for spec in model_store.MODEL_FILES:
        _sparse(directory / spec.name, spec.size)
    return directory


class Recorder:
    """Fake subprocess.run and fetch, with the calls they received."""

    def __init__(self, returncode: int = 0, writes_weights: bool = True, raises=None):
        self.returncode = returncode
        self.writes_weights = writes_weights
        self.raises = raises
        self.commands = []
        self.fetches = []

    def run(self, command, **kwargs):
        self.commands.append(list(command))
        return SimpleNamespace(returncode=self.returncode, stdout="", stderr="")

    def fetch(self, dest, **kwargs):
        self.fetches.append((str(dest), kwargs.get("on_progress")))
        if self.raises is not None:
            raise self.raises
        if self.writes_weights:
            _weights_in(Path(dest))
        return Path(dest)


def _installer(tmp_path, recorder, *, answers=(), interactive=True, **kwargs):
    answer_iter = iter(answers)
    lines = []
    installer = install.Installer(
        tmp_path,
        interactive=interactive,
        log=lines.append,
        ask_fn=lambda prompt: next(answer_iter, ""),
        run=recorder.run,
        fetch=recorder.fetch,
        requirements=lambda: [],
        **kwargs,
    )
    return installer, lines


def test_non_tty_without_flags_refuses(monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    assert install.main([]) == 2
    assert "--no-model" in capsys.readouterr().err


def test_conflicting_flags_are_rejected():
    with pytest.raises(SystemExit) as excinfo:
        install.main(["--yes", "--no-model"])
    assert excinfo.value.code == 2


def test_download_question_defaults_to_yes(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    recorder = Recorder()
    installer, lines = _installer(tmp_path, recorder, answers=[""])
    assert installer.run_all() == 0
    assert len(recorder.fetches) == 1
    dest = recorder.fetches[0][0]
    assert dest == str(model_store.user_model_dir())
    assert recorder.fetches[0][1] is model_store.print_progress
    assert any("Installed" in line for line in lines)


def test_declining_the_download_leaves_instructions(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    recorder = Recorder()
    installer, lines = _installer(tmp_path, recorder, answers=["n"])
    assert installer.run_all() == 0
    assert recorder.fetches == []
    text = "\n".join(lines)
    assert "parakeet-cage --fetch-model" in text
    assert "git lfs install && git lfs pull" in text


def test_weights_already_in_the_clone_are_not_asked_about(tmp_path):
    _weights_in(tmp_path / "models" / "parakeet-redux")
    recorder = Recorder()
    installer, lines = _installer(tmp_path, recorder)
    assert installer.run_all() == 0
    assert recorder.fetches == []
    assert any("Already installed (clone)" in line for line in lines)


def test_pointer_weights_in_the_clone_are_named(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    directory = _weights_in(tmp_path / "models" / "parakeet-redux")
    (directory / "model.safetensors").write_text("version https://git-lfs.github.com/spec/v1\n")
    recorder = Recorder()
    installer, lines = _installer(tmp_path, recorder, answers=["n"])
    installer.run_all()
    assert any("git-lfs pointer" in line and "git lfs pull" in line for line in lines)


def test_skip_model_never_asks_and_never_fetches(tmp_path):
    recorder = Recorder()
    installer, lines = _installer(tmp_path, recorder, skip_model=True)
    assert installer.run_all() == 0
    assert recorder.fetches == []
    assert any("--fetch-model" in line for line in lines)


def test_skip_app_skips_pip_only(tmp_path):
    recorder = Recorder()
    installer, _ = _installer(tmp_path, recorder, skip_app=True, answers=["n"])
    assert installer.run_all() == 0
    assert recorder.commands == []


def test_pip_failure_aborts_before_the_model(tmp_path):
    recorder = Recorder(returncode=1)
    installer, lines = _installer(tmp_path, recorder, answers=[""])
    assert installer.run_all() == 1
    assert recorder.fetches == []
    assert any("externally-managed-environment" in line for line in lines)


def test_app_install_uses_editable_user_pip(tmp_path):
    recorder = Recorder()
    installer, _ = _installer(tmp_path, recorder, answers=["n"])
    installer.install_app()
    assert recorder.commands == [
        [install.sys.executable, "-m", "pip", "install", "--user", "-e", str(tmp_path)]
    ]


def test_fetch_failure_is_reported_and_not_retried(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    recorder = Recorder(raises=model_store.ModelFetchError("boom: connection reset"))
    installer, lines = _installer(tmp_path, recorder, answers=[""])
    assert installer.run_all() == 3
    assert any("connection reset" in line for line in lines)
    assert any("Re-run ./install.sh" in line for line in lines)


def test_fetch_that_writes_nothing_is_an_error(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    recorder = Recorder(writes_weights=False)
    installer, lines = _installer(tmp_path, recorder, answers=[""])
    assert installer.run_all() == 3
    assert any("error:" in line for line in lines)


def test_preflight_blocks_when_pip_is_absent(tmp_path):
    recorder = Recorder()
    lines = []
    installer = install.Installer(
        tmp_path,
        log=lines.append,
        ask_fn=lambda prompt: "",
        run=recorder.run,
        fetch=recorder.fetch,
        requirements=lambda: [install.Requirement("pip", False, "python3 -m pip")],
    )
    assert installer.run_all() == 1
    assert recorder.commands == [] and recorder.fetches == []
    assert any("Python >= 3.11 with pip is required" in line for line in lines)


def test_assume_yes_answers_the_question(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    recorder = Recorder()
    installer = install.Installer(
        tmp_path,
        assume_yes=True,
        log=lambda line: None,
        ask_fn=lambda prompt: pytest.fail("must not prompt with --yes"),
        run=recorder.run,
        fetch=recorder.fetch,
        requirements=lambda: [],
    )
    assert installer.run_all() == 0
    assert len(recorder.fetches) == 1


def test_installer_requires_a_git_clone(tmp_path, monkeypatch):
    monkeypatch.setattr(install, "__file__", str(tmp_path / "parakeet_cage" / "install.py"))
    output = io.StringIO()
    monkeypatch.setattr("sys.stderr", output)
    assert install.main([]) == 2
    assert "git clone" in output.getvalue()


def test_requirements_report_the_running_system():
    reported = {req.label for req in install.collect_requirements()}
    assert {"Python", "pip", "git", "git-lfs", "PyGObject (GTK 3)"} <= reported


def test_fedora_has_a_package_command(monkeypatch):
    monkeypatch.setattr(install, "distro_id", lambda: "fedora")
    assert install.system_package_command() == install.SYSTEM_PACKAGES["fedora"]


def test_unknown_distro_has_no_command(monkeypatch):
    monkeypatch.setattr(install, "distro_id", lambda: "plan9")
    assert install.system_package_command() is None
