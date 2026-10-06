# Parakeet Cage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Linux desktop dictation daemon that records speech on a hotkey and auto-pastes transcription into the active text field, powered by parakeet-redux, packaged as an AppImage.

**Architecture:** Single Python process with four threads (hotkey listener, audio capture, ASR inference, tray icon). State machine: IDLE → RECORDING → TRANSCRIBING → PASTED → IDLE. Clipboard + Ctrl+V for text injection.

**Tech Stack:** Python 3.10+, `moondream`, `pynput`, `sounddevice`, `pystray`, `tkinter`, TOML config, AppImage packaging.

**Spec:** `docs/superpowers/specs/2026-10-06-parakeet-cage-design.md`

## Global Constraints

- Model: `moondream/parakeet-redux`, 178 MB, bundled in AppImage.
- Display server: detect via `$XDG_SESSION_TYPE`; default X11 if unset.
- Config path: `~/.config/parakeet-cage/config.toml`.
- Hotkeys: `Ctrl+Shift+S` (push-to-talk), `Ctrl+Shift+Q` (quit).
- No persistent UI window; tray icon only.
- Linux only. Single-user desktop tool.

## Review Focus

1. **Empty audio buffer on release** — user taps the hotkey briefly (< 0.5s). Expected: no paste, no error, state returns to IDLE silently.
2. **Model not loaded yet when hotkey fires** — app just started, model still loading. Expected: hotkey ignored until model ready; tray shows "loading."
3. **Clipboard write fails (no X11/Wayland)** — headless server or missing xclip/wl-paste. Expected: error logged, state returns to IDLE, no crash.
4. **Very long recording (> 5 min)** — user holds key for minutes. Expected: transcription completes, full text pasted. No timeout.
5. **Multiple rapid press-release cycles** — user spams the hotkey. Expected: each cycle produces one paste; no race conditions or double-pastes.

---

## File Structure

```
parakeet_cage/
  __init__.py          # package marker, version
  config.py            # TOML load/save, dataclasses
  clipboard.py          # display detection, clipboard write, paste send
  audio.py              # sounddevice mic capture
  transcriber.py        # moondream ASR wrapper
  hotkeys.py            # pynput listener + state machine
  tray.py               # pystray tray icon
  settings_ui.py        # tkinter settings window
  main.py               # entry point, daemon lifecycle
appimage/
  build.sh              # AppImage build script
tests/
  test_config.py
  test_clipboard.py
  test_audio.py
  test_transcriber.py
  test_hotkeys.py
```

---

### Task 1: Config Module

**Files:**
- Create: `parakeet_cage/__init__.py`
- Create: `parakeet_cage/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `Config` dataclass with fields: `record_hotkey: str`, `quit_hotkey: str`, `model_path: str`, `audio_device: str`. Functions: `load_config(path: Path) -> Config`, `save_config(cfg: Config, path: Path) -> None`.

- [ ] **Step 1: Write the failing test**

```python
def test_load_config_returns_defaults():
    cfg = load_config(Path("/nonexistent/config.toml"))
    assert cfg.record_hotkey == "ctrl+shift+s"
    assert cfg.quit_hotkey == "ctrl+shift+q"
    assert cfg.audio_device == ""

def test_save_then_load_roundtrip():
    path = tmp_path / "config.toml"
    cfg = Config(record_hotkey="alt+f9", quit_hotkey="alt+f10", model_path="/tmp/m", audio_device="usb")
    save_config(cfg, path)
    loaded = load_config(path)
    assert loaded.record_hotkey == "alt+f9"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'parakeet_cage.config'`

- [ ] **Step 3: Implement `config.py`**

```python
@dataclass
class Config:
    record_hotkey: str = "ctrl+shift+s"
    quit_hotkey: str = "ctrl+shift+q"
    model_path: str = ""
    audio_device: str = ""

def load_config(path: Path) -> Config: ...
def save_config(cfg: Config, path: Path) -> None: ...
```

Use `tomllib` (3.10+) for parsing. If file missing, return defaults. Create parent dirs on save.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_config.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add parakeet_cage/__init__.py parakeet_cage/config.py tests/test_config.py
git commit -m "feat: add config module with TOML load/save"
```

---

### Task 2: Clipboard + Paste Injection

**Files:**
- Create: `parakeet_cage/clipboard.py`
- Test: `tests/test_clipboard.py`

**Interfaces:**
- Consumes: nothing (standalone).
- Produces: `detect_display() -> str` (returns "x11" | "wayland"), `paste_text(text: str) -> None`.

- [ ] **Step 1: Write the failing test**

```python
def test_detect_display_x11():
    assert detect_display() in ("x11", "wayland")

def test_paste_text_writes_to_clipboard():
    # On X11: xclip -i, then xclip -o returns same text
    paste_text("hello world")
    import subprocess
    out = subprocess.check_output(["xclip", "-o"])
    assert out.decode().strip() == "hello world"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_clipboard.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement `clipboard.py`**

```python
def detect_display() -> str:
    """Read $XDG_SESSION_TYPE. Default 'x11' if unset."""

def paste_text(text: str) -> None:
    """Write text to clipboard, then send ctrl+v.
    X11: xclip -i + xdotool key ctrl+v
    Wayland: wl-paste -i + wtype key ctrl v
    """
```

Use `subprocess.run` with the appropriate tools. On failure (missing binary), log error and raise a custom `PasteError`. Catch at call site in Task 5.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_clipboard.py -v`
Expected: PASS (requires X11 session for xclip test)

- [ ] **Step 5: Commit**

```bash
git add parakeet_cage/clipboard.py tests/test_clipboard.py
git commit -m "feat: add clipboard paste injection with display detection"
```

---

### Task 3: Audio Capture

**Files:**
- Create: `parakeet_cage/audio.py`
- Test: `tests/test_audio.py`

**Interfaces:**
- Consumes: `Config.audio_device` (from Task 1).
- Produces: `AudioRecorder` class with methods: `start(device: str) -> None`, `stop() -> bytes` (returns raw PCM buffer), property `is_recording: bool`.

- [ ] **Step 1: Write the failing test**

```python
def test_recorder_start_stop_returns_bytes():
    rec = AudioRecorder()
    rec.start(device="")
    assert rec.is_recording is True
    import time; time.sleep(0.2)
    data = rec.stop()
    assert isinstance(data, bytes)
    assert len(data) > 0

def test_stop_without_start_returns_empty():
    rec = AudioRecorder()
    assert rec.stop() == b""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_audio.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement `audio.py`**

```python
class AudioRecorder:
    def __init__(self): ...
    def start(self, device: str) -> None:
        """Open sounddevice Stream (16-bit PCM, 16kHz mono)."""
    def stop(self) -> bytes:
        """Close stream, return accumulated buffer."""
    @property
    def is_recording(self) -> bool: ...
```

Use `sounddevice.Stream` in a background thread. Accumulate into a `bytearray`. On stop, return `bytes(buffer)`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_audio.py -v`
Expected: PASS (requires audio device; skip with `@pytest.mark.skipif` if no input device)

- [ ] **Step 5: Commit**

```bash
git add parakeet_cage/audio.py tests/test_audio.py
git commit -m "feat: add audio recorder with sounddevice"
```

---

### Task 4: Transcriber

**Files:**
- Create: `parakeet_cage/transcriber.py`
- Test: `tests/test_transcriber.py`

**Interfaces:**
- Consumes: raw PCM bytes from `AudioRecorder.stop()`.
- Produces: `Transcriber` class with methods: `load(model_path: str) -> None`, `transcribe(audio: bytes) -> str`, property `ready: bool`.

- [ ] **Step 1: Write the failing test**

```python
def test_transcriber_loads_model():
    t = Transcriber()
    t.load(model_path="moondream/parakeet-redux")
    assert t.ready is True

def test_transcribe_known_audio():
    # Use a bundled test WAV (e.g., 1s of "hello world")
    wav_bytes = Path("tests/fixtures/hello.wav").read_bytes()
    t = Transcriber()
    t.load(model_path="moondream/parakeet-redux")
    result = t.transcribe(wav_bytes)
    assert isinstance(result, str)
    assert len(result.strip()) > 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_transcriber.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement `transcriber.py`**

```python
class Transcriber:
    def __init__(self): ...
    def load(self, model_path: str) -> None:
        """Load moondream.photon(model_path). Store handle."""
    def transcribe(self, audio: bytes) -> str:
        """Write temp WAV, call speech.transcribe(audio=...), return text."""
    @property
    def ready(self) -> bool: ...
```

Convert raw PCM (16-bit mono 16kHz) to a temp `.wav` file using `wave` module. Call `md.photon(...).transcribe()`. Return `result["text"]`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_transcriber.py -v`
Expected: PASS (requires model download or bundled weights)

- [ ] **Step 5: Commit**

```bash
git add parakeet_cage/transcriber.py tests/test_transcriber.py
git commit -m "feat: add transcriber wrapper around moondream"
```

---

### Task 5: Hotkey Listener + State Machine

**Files:**
- Create: `parakeet_cage/hotkeys.py`
- Test: `tests/test_hotkeys.py`

**Interfaces:**
- Consumes: `Config` (Task 1), `AudioRecorder` (Task 3), `Transcriber` (Task 4), `paste_text` (Task 2).
- Produces: `HotkeyController` class with methods: `start() -> None`, `stop() -> None`. Internal state machine.

- [ ] **Step 1: Write the failing test**

```python
def test_state_transitions_on_press_release():
    ctrl = HotkeyController(config, recorder, transcriber)
    # Simulate: press → RECORDING, release → TRANSCRIBING → PASTED → IDLE
    ctrl._on_press()
    assert ctrl.state == "recording"
    ctrl._on_release()
    assert ctrl.state == "idle"

def test_rapid_press_release_no_double_paste():
    ctrl = HotkeyController(config, recorder, transcriber)
    paste_count = 0
    ctrl._set_paste_hook(lambda t: nonlocal paste_count; paste_count += 1)
    for _ in range(5):
        ctrl._on_press()
        ctrl._on_release()
    assert paste_count == 5  # exactly one per cycle

def test_short_tap_no_paste():
    ctrl = HotkeyController(config, recorder, transcriber)
    ctrl._on_press()
    time.sleep(0.1)
    ctrl._on_release()
    # Buffer < threshold → no paste dispatched
    assert ctrl.paste_called is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_hotkeys.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement `hotkeys.py`**

```python
class HotkeyController:
    STATES = ("idle", "recording", "transcribing", "pasted")
    def __init__(self, config, recorder, transcriber): ...
    def start(self) -> None:
        """Register pynput keyboard listener for config hotkeys."""
    def stop(self) -> None:
        """Unregister listener."""
    def _on_press(self) -> None:
        """If idle and transcriber.ready: start recording."""
    def _on_release(self) -> None:
        """If recording: stop, transcribe, paste. If < 0.5s buffer: skip paste."""
```

Minimum duration gate: if recorded audio < 0.5s, skip transcription and paste. This handles the "tap" edge case (Review Focus #1).

Use `pynput.keyboard.Listener` with `Key` matching. Run in a dedicated thread.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_hotkeys.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add parakeet_cage/hotkeys.py tests/test_hotkeys.py
git commit -m "feat: add hotkey controller with state machine"
```

---

### Task 6: Tray Icon

**Files:**
- Create: `parakeet_cage/tray.py`

**Interfaces:**
- Consumes: `HotkeyController.state` (Task 5).
- Produces: `TrayIcon` class with methods: `start(state_callback) -> None`, `stop() -> None`. Context menu: "Settings" → opens settings UI, "Quit" → stops daemon.

- [ ] **Step 1: Implement `tray.py`**

```python
class TrayIcon:
    def start(self, state_callback):
        """pystray icon. Tooltip + icon changes with state.
        idle: grey mic. recording: red dot. transcribing: blue spinner."""
    def stop(self) -> None: ...
```

Context menu items: "Open Settings" (launches `settings_ui.py`), "Quit". Right-click triggers. Run pystray in its own thread (`pystray.run()` is blocking).

No test (GUI-dependent, headless-unsafe). Smoke-verified at integration.

- [ ] **Step 2: Commit**

```bash
git add parakeet_cage/tray.py
git commit -m "feat: add tray icon with state display"
```

---

### Task 7: Settings UI

**Files:**
- Create: `parakeet_cage/settings_ui.py`

**Interfaces:**
- Consumes: `Config`, `load_config`, `save_config` (Task 1).
- Produces: `open_settings(config_path: Path) -> None`. Launches a blocking tkinter window.

- [ ] **Step 1: Implement `settings_ui.py`**

```python
def open_settings(config_path: Path) -> None:
    """tkinter Toplevel. Fields:
    - Record hotkey (Entry, text input like 'ctrl+shift+s')
    - Quit hotkey (Entry)
    - Audio device (OptionMenu from sounddevice.query_devices())
    Save button → save_config(). Close."""
```

No automated test (GUI). Verify manually in integration.

- [ ] **Step 2: Commit**

```bash
git add parakeet_cage/settings_ui.py
git commit -m "feat: add settings UI window"
```

---

### Task 8: Main Entry Point + Daemon Lifecycle

**Files:**
- Create: `parakeet_cache/main.py`
- Test: `tests/test_main.py` (smoke test)

**Interfaces:**
- Consumes: all of Tasks 1–7.
- Produces: `main() -> None` — entry point. `run_daemon() -> None` — wire and start all threads.

- [ ] **Step 1: Write the smoke test**

```python
def test_daemon_starts_and_stops():
    # Verify run_daemon() starts threads, model loads,
    # then stop() cleans up without errors.
    # Requires display + audio; skip if unavailable.
    import parakeet_cage.main as m
    m.run_daemon(duration=2)  # run for 2s then auto-stop
```

- [ ] **Step 2: Run smoke test**

Run: `pytest tests/test_main.py -v`
Expected: PASS (or SKIP if no display/audio)

- [ ] **Step 3: Implement `main.py`**

```python
def run_daemon(duration: float | None = None) -> None:
    """1. Load config
       2. Start tray icon
       3. Load model in background thread (transcriber.load())
       4. Start HotkeyController
       5. If duration: sleep then stop all
       6. notify-send 'Parakeet Cage running'
       7. On quit hotkey or SIGTERM: stop all, exit"""

def main() -> None:
    """argparse: --settings flag opens settings UI immediately."""
```

Model loading runs in a thread so hotkeys are armed after the model is ready (Review Focus #2). Use a threading.Event for "model ready."

- [ ] **Step 4: Run smoke test to verify it passes**

Run: `pytest tests/test_main.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add parakeet_cache/main.py tests/test_main.py
git commit -m "feat: add main entry point and daemon lifecycle"
```

---

### Task 9: AppImage Packaging

**Files:**
- Create: `appimage/build.sh`

**Interfaces:**
- Consumes: all source files.
- Produces: a `.appimage` binary with embedded Python runtime, deps, model weights.

- [ ] **Step 1: Write the build script**

```bash
# appimage/build.sh
# Uses AppImage tooling (https://github.com/AppImage/appimagetool)
# Steps:
# 1. Create a Nix/Darwin-independent directory with:
#    - python3 + pip packages (moondream, pynput, sounddevice, pystray)
#    - model weights from moondream/parakeet-redux
# 2. Write .appimage.yml with entryPoint: parakeet_cage/main.py
# 3. Run appimagetool to produce ParakeetCage-x86-64.AppImage
```

- [ ] **Step 2: Verify build produces a valid AppImage**

Run: `./appimage/build.sh`
Expected: `ParakeetCage-x86-64.AppImage` exists, `file` reports ELF.

- [ ] **Step 3: Commit**

```bash
git add appimage/build.sh
git commit -m "feat: add AppImage build script"
```

---

## Self-Review

1. **Spec coverage:** All spec sections mapped: state machine (Task 5), text injection (Task 2), audio (Task 3), ASR (Task 4), tray (Task 6), settings (Task 7), config (Task 1), AppImage (Task 9), daemon lifecycle (Task 8). ✓
2. **Step scan:** Each step is one action with a checkable result. No "handle edge cases" or "add validation." ✓
3. **Type consistency:** `Config` fields consistent across Tasks 1, 5, 7. `AudioRecorder.stop() -> bytes` matches Task 4's `transcribe(audio: bytes)`. `paste_text(text: str)` called from Task 5. ✓
4. **Review Focus:** All five covered — empty buffer (Task 5 min-duration gate), model loading (Task 8 background thread), clipboard failure (Task 2 PasteError, caught in Task 5), long recording (no timeout in Task 3/4), rapid cycles (Task 5 state machine). ✓
5. **Proportion:** Plan is ~same length as spec. Code blocks are signatures only, not bodies. ✓
