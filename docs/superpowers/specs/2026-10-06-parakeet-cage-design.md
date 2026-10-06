# Parakeet Cage — Design Spec

## Purpose

A Linux desktop dictation tool. Hold a hotkey to record speech; release it and the transcription is automatically pasted into whatever text field has focus. Powered by the `moondream/parakeet-redux` 178 MB ternary ASR model, distributed as a self-contained AppImage.

## Architecture

Single Python process with four threads:

| Thread | Role | Library |
|--------|------|---------|
| Main | Hotkey listener, state machine orchestration | `pynput` |
| Audio | Mic capture, buffer management | `sounddevice` |
| ASR | Model inference on release | `moondream` |
| Tray | Status icon (idle / recording / transcribing) | `pystray` |

### State Machine

```
IDLE ──(hotkey press)──► RECORDING ──(hotkey release)──► TRANSCRIBING ──(done)──► PASTED ──► IDLE
```

- **IDLE**: Hotkey armed, mic off.
- **RECORDING**: Mic capturing audio into a buffer.
- **TRANSCRIBING**: Buffer sent to model; waiting for result.
- **PASTED**: Text in clipboard, Ctrl+V dispatched. State returns to IDLE immediately after paste dispatch.

### Hotkeys (configurable)

| Default | Action |
|---------|--------|
| `Ctrl+Shift+S` | Push-to-talk: press starts recording, release stops + transcribes + auto-pastes |
| `Ctrl+Shift+Q` | Quit daemon |

## Text Injection

On transcription complete, automatically:
1. Put text in clipboard (`xclip -i` on X11, `wl-paste -i` on Wayland).
2. Send paste keystroke (`xdotool key ctrl+v` or `wtype key ctrl v`).
3. Text appears in the user's active field with zero user action.

Display server detection: read `$XDG_SESSION_TYPE` at startup. Cache result. Default to X11 if unset.

## Settings UI

- Double-click → extracts to temp dir → launches daemon → `notify-send` toast "Parakeet Cage running."

```toml
[hotkeys]
record = "ctrl+shift+s"
quit = "ctrl+shift+q"

[model]
path = "/usr/share/parakeet-cage/models/parakeet-redux"

[audio]
device = ""  # empty = system default input
```

Fields: hotkey rebind, audio device selector. No language picker (model auto-detects).

## AppImage Packaging

- Bundles: Python runtime, all pip deps (`moondream`, `pynput`, `sounddevice`, `pystray`), model weights (178 MB).
- Total size: ~200 MB.
- Double-click → extracts to temp dir → launches daemon → brief toast "Parakeet Cage running."
- Model pre-bundled; no download on first run.

## Repository

`https://github.com/craigmcgrain-spec/Parakeet-Cage` — empty at start. All code lives here.

## Constraints & Non-Goals

- No language selection UI (model handles 25 languages automatically).
- No persistent window; tray icon only.
- No network/API mode; fully local inference.
- No Windows/macOS support.
- Single-user desktop tool, not a server.
