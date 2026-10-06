# Credits and third-party notices

## Parakeet Redux (speech recognition model)

**This project exists because of Parakeet Redux.** All speech recognition is performed by it.

- Model: **Moondream Parakeet Redux** — <https://huggingface.co/moondream/parakeet-redux>
- Author: **[Moondream](https://moondream.ai)**
- License: **CC-BY-4.0** (<https://creativecommons.org/licenses/by/4.0/>)
- Based on: **NVIDIA `parakeet-tdt-0.6b-v3`** — <https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3>
  (languages, tokenizer and output conventions come from the original model)
- Release post: <https://moondream.ai/blog/introducing-parakeet-redux-and-ultra>

Parakeet Redux is a 1.58-bit (ternary) build of the Parakeet TDT 0.6B v3 architecture: every encoder
weight is −1, 0 or +1, which brings the weights down to 178 MB while staying within 0.3 WER of the
original on English and beating it on the 25-language FLEURS set and on long-form audio.

Attribution required by CC-BY-4.0: the model name, its author (Moondream), a link to the license
and an indication of changes. Parakeet Cage does not modify the weights; it loads
`model.safetensors` from local disk and runs inference on the CPU. When the AppImage is
redistributed, this section (and `models/parakeet-redux/` alongside it) must travel with it — the
build script copies this file into the bundle for that reason.

## Inference engine

- **kestrel** (0.9.1) and the **Photon** runtime by Moondream — <https://moondream.ai/photon>.
  `parakeet_cage/transcriber.py` builds its Parakeet runtime through `kestrel.models.registry`.
  Distributed as separate PyPI packages; check the license metadata of `kestrel`,
  `kestrel-native`, `kestrel-kernels` and `moondream` for their terms (the `kestrel-kernels`
  distributions declare a proprietary license). These packages are **not** redistributed by this
  repository or by the AppImage built here — they are installed by the user.

## Third-party software used at runtime

Licenses as published by the respective projects at the time of writing; consult each project for
the authoritative text.

| Project | Used for | License |
|---|---|---|
| [sounddevice](https://python-sounddevice.readthedocs.io) | microphone capture (PortAudio) | MIT |
| [numpy](https://numpy.org) | resampling, buffer handling | BSD-3-Clause |
| [torch](https://pytorch.org) | tensor runtime required by kestrel | BSD-3-Clause (PyTorch) |
| [python-xlib](https://github.com/python-xlib/python-xlib) | global hotkey grabs | LGPL-2.1+ |
| [pystray](https://github.com/moses-palmer/pystray) | system tray icon | LGPL-3.0 |
| [Pillow](https://python-pillow.org) | tray icon rendering | MIT-CMU |
| [pynput](https://github.com/moses-palmer/pynput) | X11-only keystroke fallback | LGPL-3.0 |
| [PyGObject](https://pygobject.gnome.org) / GTK 3 | settings dialog, tray main loop | LGPL-2.1+ |
| [dbus-python](https://gitlab.freedesktop.org/dbus/dbus-python) | Klipper clipboard, portal virtual keyboard | MIT (Expat) |
| [huggingface_hub](https://github.com/huggingface/huggingface_hub) | only used by users to fetch weights once | Apache-2.0 |
| [wl-clipboard](https://github.com/bugaevc/wl-clipboard) | clipboard on Wayland | MIT |

## System interfaces

`org.kde.klipper` (KDE clipboard), `org.freedesktop.portal.RemoteDesktop` and
`org.freedesktop.portal.GlobalShortcuts` (XDG desktop portals), X11 `XGrabKey` — documented by the
KDE, freedesktop.org and X.Org projects respectively.
