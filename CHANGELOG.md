# Changelog

All notable changes to Parakeet Cage. This project adheres to
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.3.0] — 2026-10-06

The auto dictionary: what the app proposes now lives in its own store, so a machine-suggested word
can never mix with one you typed.

### Added

- **Auto dictionary** (`parakeet_cage/auto_dictionary.py`, `~/.local/share/parakeet-cage/learning/auto.toml`):
  `[[candidate]]` blocks are near-misses the app observed but never applied, `[[word]]` blocks are
  the ones you accepted from them. Accepting a candidate no longer writes into your `lexicon.toml`.
- The dictionary window shows both stores, under **Your dictionary** and **Auto**, with *Add as
  alias*, *Ignore*, *→ mine* (promote a proposal into your own list) and *Clear auto*.
- `[text] auto_dictionary` and `[text] auto_path`; `parakeet-cage --pending` reads the auto file, and
  candidates from an older standalone `pending.toml` are imported on first use.

### Changed

- `Lexicon` no longer owns a candidate queue: the auto dictionary is the single owner of proposals,
  and `Lexicon.record` only maintains hit counters.
- Appending several entries in one save separates them with a blank line, as the rest of the file
  does.

### Decisions

- **No desktop notifications.** Corrections stay visible through the log, the change log and the
  tray's *Undo last correction*, and never interrupt dictation.

## [1.2.0] — 2026-10-06

Spoken punctuation and a personal dictionary you manage in the app, both applied between the
model's output and the clipboard.

### Added

- **Dictionary window** (`parakeet_cage/dictionary_ui.py`), reachable from the tray menu
  (*Dictionary…*) or `parakeet-cage --dictionary`: lists your words with their aliases, an on/off
  switch and a hit count, and the candidates the guard refused to apply, each with *Add as alias*
  and *Ignore*. Saving writes both files in place — comments and formatting in a hand-edited
  `lexicon.toml` survive — and the decision logic lives in a widget-free `DictionaryModel` that is
  unit-tested.
- **Live reload**: the dictionary is re-read whenever the file changes on disk, so hand edits and
  window saves apply to the *next* dictation instead of requiring a restart.
- **Spoken punctuation** (`parakeet_cage/textnorm.py`). Command words become symbols:
  `question mark` → `?`, `period`/`full stop`, `comma`, `exclamation mark`/`point`, `colon`,
  `semicolon`, `ellipsis`, `dash`, `hyphen`, `dot`, `at sign`, `underscore`, `slash`, brackets,
  quotes, `new line`, `new paragraph` and friends. The table is extensible and a command can be
  disabled from `[text.punctuation_extra]`; the word `literal` in front of a command suppresses it.
  Because the model punctuates as it sees fit, mapping the words is not enough — measured real
  outputs drove three repair rules that ship with the command table:
  - punctuation the model attached to the command is absorbed (`question mark?` → not `??`)
  - separators stranded in front of a terminal are removed, duplicates collapsed
    (`the file period did you get it, question mark.` → `the file. Did you get it?`)
  - the clause after terminal punctuation is re-capitalised
  - commands are matched case-insensitively, because the model reads rare words as proper nouns
    (`question Mark?` → `?`)
- **Personal dictionary** (`parakeet_cage/lexicon.py`), a hand-editable TOML at
  `~/.config/parakeet-cage/lexicon.toml` (created as a documented template on first run) with
  `word`, `aliases`, `enabled` and a hit counter. Matching is tiered:
  exact/alias matches always apply; edit-distance matches and phonetic matches (consonant skeleton
  *exactly* equal) apply only when the heard token is a word the model does *not* know well,
  measured with the model's own tokenizer — ordinary words cost 1-2 subword pieces (`our` 1,
  `socket` 2) while misheard rare words are spelled out (`castrell` 4, `parakita` 3). Looser
  phonetic near-misses are queued rather than applied: end-to-end testing caught `castle` being
  rewritten to `kestrel` (one skeleton edit apart), which is now a review candidate only. Anything
  fuzzy that hits a well-known word is written to
  `~/.local/share/parakeet-cage/learning/pending.toml` instead of touching the text, so
  `our → OAuth` can never corrupt an ordinary sentence.
- **`parakeet-cage --pending`** lists the queued candidates, and **`parakeet-cage --version`** now
  works — `main()` previously ignored its arguments entirely.
- The tray menu gains **Undo last correction**, enabled after a transcript was changed; it
  re-pastes the transcript exactly as the model heard it.
- `[text]` config section: `punctuation`, `punctuation_extra`, `lexicon`, `lexicon_path`,
  `lexicon_max_distance`.
- Post-processing can never break dictation: a failing stage is logged, skipped, and the raw
  transcript is pasted.

### Changed

- `Config` gained a `TextConfig` section, and the settings dialog now uses
  `ui.build_config()` (dataclass `replace`) so saving hotkeys no longer resets the `[text]`
  section to defaults.
- Test suite grew from 38 to 117 tests, including fixtures taken from real measured model output.

### Fixed

- Updating hit counters no longer reformats the dictionary: only the `hits = N` values are
  rewritten in place, so comments, ordering and formatting in a hand-edited `lexicon.toml`
  survive. When an utterance changed nothing, the file is not written at all.
- A refused global-hotkey grab is reported instead of being claimed as a success. python-xlib
  only *prints* asynchronous errors such as `BadAccess` from `XGrabKey` and `sync()` returns
  normally, so the listener logged `Registered global record hotkey: 'F9'` while another
  application (typically a second Parakeet Cage instance) held the key — dictation then silently
  never triggered. Grabs now run with an armed X error recorder; a refusal logs an actionable
  error naming the key, and `HotkeyListener.unavailable_hotkeys` records it.

### Notes

- A dictionary **cannot** influence recognition on this model: the runtime answers
  `"Parakeet TDT does not support an initial prompt"` and rejects unknown options such as
  `hotwords`, so a word list can only rewrite the transcribed text. On synthetic (espeak) speech,
  7 of 12 rare/technical words were recoverable this way — 2 already correct, 2 by edit distance,
  3 by phonetics only; the rest came back as unrelated real words and need review, not matching.

## [1.0.0] — 2026-10-06

First public release. Push-to-talk dictation for Linux with fully local inference, powered by
Moondream's [Parakeet Redux](https://huggingface.co/moondream/parakeet-redux) model (CC-BY-4.0).

### Added

- Global push-to-talk hotkey (`F9` by default) with auto-repeat debounce; configurable quit hotkey.
- Microphone capture via `sounddevice`, auto-negotiating the device's native sample rate and
  resampling to 16 kHz mono for the model.
- Offline Parakeet Redux inference: weights loaded strictly from local disk, with HuggingFace
  snapshot checks, telemetry and remote probes disabled in-process.
- Tray icon with idle/recording/transcribing states (green/red/amber).
- GTK 3 settings dialog: interactive hotkey capture (`Esc` cancels), input device selector, model
  path; writes `~/.config/parakeet-cage/config.toml`.
- Clipboard integration with previous-clipboard restoration, and transcription retained on the
  clipboard when injection fails (with an actionable error instead of a silent no-op).
- AppImage packaging that bundles the application, the model weights and the attribution files.

### Changed

- **Text injection is now Wayland-native.** `xdg-desktop-portal`'s RemoteDesktop virtual keyboard
  replaces the previous `ydotool`/`ydotoold` backend, so no root, `/dev/uinput` or helper daemon is
  required, and keystrokes reach native Wayland clients. `wtype`, `xdotool` and `pynput` remain as
  ordered fallbacks; `pynput` is skipped on Wayland because XTest can never reach a native Wayland
  window.
- Injection backends now report success/failure; the portal session is created once per run and
  cached, with a retry cooldown so a denied or restarting portal cannot spam consent dialogs.
- Post-paste clipboard restore waits 0.5 s (was 0.2 s) so a temporarily busy target application does
  not paste the restored clipboard instead of the transcription.
- Versioning starts at 1.0.0; packaging metadata, README, credits and license added.

### Fixed

- Transcribed text never appeared at the cursor when no injection backend was usable: failures were
  logged at `DEBUG` (or swallowed) and the clipboard was restored on top of the transcription.
- `xdg-desktop-portal` (1.x) is crashed by a `CreateSession` request without `session_handle_token`
  — the option is documented as optional but the portal dies with `Remote peer disconnected`. The
  client now always sends it.
- A `dbus.SessionBus()` connection created before a GLib main loop exists (the clipboard helpers do
  this) can never receive signals; the portal client now owns a private, loop-attached connection.
- Recorded audio is resampled from the negotiated hardware rate instead of assuming 16 kHz, and the
  recorder no longer aborts on the first unsupported sample rate.
- Tray icon updates are marshalled onto the GLib main loop; the Tk settings window was replaced by
  GTK 3 to stop a `Tcl_Panic` crash alongside pystray.

### Known limitations

- The AppImage is a **thin** bundle: it ships the application code, the model weights and the
  attribution, but relies on the host for Python 3, PyGObject, dbus-python and the pip
  dependencies. GTK/PyGObject extensions are compiled against the host interpreter, so the design
  spec's "bundle every pip dependency" goal is only partially met. A preflight in `AppRun` names
  anything missing and how to install it.
- Global hotkeys use X11 key grabs on `$DISPLAY` (Xwayland). Compositors that do not forward X11
  grabs to focused native Wayland windows need a compositor-side binding; portal GlobalShortcuts
  registration is not implemented.
- X11 (non-Wayland) sessions fall back to `xdotool`/`pynput`, which reach X11 clients only.

[1.3.0]: https://github.com/craigmcgrain-spec/Parakeet-Cage/releases/tag/v1.3
[1.2.0]: https://github.com/craigmcgrain-spec/Parakeet-Cage/releases/tag/v1.2
[1.0.0]: https://github.com/craigmcgrain-spec/Parakeet-Cage/releases/tag/v1.0
