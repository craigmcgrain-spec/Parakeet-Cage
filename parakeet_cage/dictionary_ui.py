"""Dictionary window: two stores, managed without editing TOML by hand.

* **Your dictionary** (`lexicon.toml`) — only you add to it, exactly as before.
* **Auto** (`auto.toml`) — what the app proposed: candidates it observed but never applied,
  and the ones you accepted. Accepting one keeps it here, so machine-proposed words stay
  distinguishable from your own.

The GTK layer is deliberately thin. Everything that decides what happens to the files —
which store a candidate belongs to, what gets written, what is dropped — lives in
`DictionaryModel`, which has no widgets in it and is tested without a display.
"""

from __future__ import annotations

from dataclasses import replace
import logging
from pathlib import Path
from typing import List, Optional, Sequence

import gi

try:
    gi.require_version("Gdk", "3.0")
    gi.require_version("Gtk", "3.0")
except ValueError:
    pass
from gi.repository import Gtk, GLib

from parakeet_cage.auto_dictionary import accept
from parakeet_cage.config import Config
from parakeet_cage.lexicon import Entry, Queued
from parakeet_cage.postprocess import TextPipeline

logger = logging.getLogger(__name__)


class DictionaryModel:
    """Two stores and the rules for changing them.

    `entries()` is your dictionary — only you add to it. `auto_entries()` and `candidates()`
    are the auto dictionary: what the app proposed and what you accepted from it. Edits stay
    in memory until `save()`, so a window can be abandoned without touching either file.
    """

    def __init__(self, pipeline: TextPipeline) -> None:
        self._pipeline = pipeline
        self._entries: List[Entry] = []
        self._auto_entries: List[Entry] = []
        self._candidates: List[Queued] = []
        self.reload()

    # -- state ---------------------------------------------------------------

    def reload(self) -> None:
        """Read both files, picking up hand edits made outside the window."""
        lexicon = self._pipeline.lexicon
        if lexicon is not None:
            lexicon.reload_if_changed()
        self._entries = [replace(entry) for entry in (lexicon.entries if lexicon else [])]

        auto = self._pipeline.auto
        if auto is not None:
            auto.reload_if_changed()
        self._auto_entries = [replace(entry) for entry in (auto.entries() if auto else [])]
        self._candidates = auto.candidates() if auto else []

    def entries(self) -> List[Entry]:
        return list(self._entries)

    def auto_entries(self) -> List[Entry]:
        return list(self._auto_entries)

    def candidates(self) -> List[Queued]:
        return list(self._candidates)

    def set_entries(self, entries: Sequence[Entry]) -> None:
        """Replace your words: while the window is open, its rows are the truth."""
        self._entries = list(entries)

    def set_auto_entries(self, entries: Sequence[Entry]) -> None:
        self._auto_entries = list(entries)

    def lexicon_path(self) -> Optional[Path]:
        lexicon = self._pipeline.lexicon
        return lexicon.source_path if lexicon is not None else None

    def auto_path(self) -> Optional[Path]:
        auto = self._pipeline.auto
        return auto.path if auto is not None else None

    # -- your dictionary -----------------------------------------------------

    def add_entry(self, word: str, aliases: Sequence[str] = ()) -> bool:
        """Add a word. Returns False when it is empty or already present."""
        word = word.strip()
        if not word or any(entry.word.casefold() == word.casefold() for entry in self._entries):
            return False
        self._entries.append(Entry(word=word, aliases=_clean_aliases(aliases)))
        return True

    def update_entry(
        self,
        index: int,
        word: Optional[str] = None,
        aliases: Optional[Sequence[str]] = None,
        enabled: Optional[bool] = None,
    ) -> None:
        entry = self._entries[index]
        self._entries[index] = replace(
            entry,
            word=word.strip() if word and word.strip() else entry.word,
            aliases=_clean_aliases(aliases) if aliases is not None else entry.aliases,
            enabled=entry.enabled if enabled is None else bool(enabled),
        )

    def remove_entry(self, index: int) -> None:
        del self._entries[index]

    # -- the auto dictionary -------------------------------------------------

    def accept_candidate(self, index: int) -> None:
        accept(self._auto_entries, self._candidates, index)

    def ignore_candidate(self, index: int) -> None:
        del self._candidates[index]

    def promote_entry(self, index: int) -> Entry:
        """Move an accepted auto entry into your own dictionary."""
        entry = self._auto_entries.pop(index)
        self._entries.append(entry)
        return entry

    def clear_auto(self) -> None:
        self._auto_entries = []
        self._candidates = []

    # -- persistence ---------------------------------------------------------

    def save(self) -> None:
        self._pipeline.save_entries(self._entries)
        auto = self._pipeline.auto
        if auto is not None:
            auto.set_entries(self._auto_entries)
            auto.set_candidates(self._candidates)
            auto.save()


def _clean_aliases(aliases: Optional[Sequence[str]]) -> tuple:
    return tuple(dict.fromkeys(alias.strip() for alias in (aliases or ()) if alias.strip()))


class DictionaryWindow:
    """GTK 3 window with your dictionary on top and the auto dictionary below it."""

    def __init__(self, pipeline: TextPipeline, quit_on_close: bool = False) -> None:
        self._model = DictionaryModel(pipeline)
        self._quit_on_close = quit_on_close
        self._rows: List[tuple] = []
        self._auto_rows: List[tuple] = []
        self._hits: dict = {}
        self._auto_hits: dict = {}
        self._window: Optional[Gtk.Window] = None
        self._status: Optional[Gtk.Label] = None

    def show(self) -> None:
        """Build and present the window on the GLib main loop."""
        GLib.idle_add(self._create_and_show)

    # -- construction --------------------------------------------------------

    def _create_and_show(self) -> bool:
        for entry in self._model.entries():
            self._hits[entry.word.casefold()] = entry.hits
        for entry in self._model.auto_entries():
            self._auto_hits[entry.word.casefold()] = entry.hits

        window = Gtk.Window(title="Parakeet Cage — Dictionary")
        window.set_default_size(860, 620)
        window.set_position(Gtk.WindowPosition.CENTER)
        window.set_border_width(12)
        window.connect("key-press-event", self._on_key_press)
        if self._quit_on_close:
            window.connect("destroy", Gtk.main_quit)

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        window.add(outer)

        outer.pack_start(
            self._heading("Your dictionary", self._model.lexicon_path(),
                          "words you added; the app never writes entries here"),
            False, False, 0,
        )
        self._rows_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        outer.pack_start(self._scrolled(self._rows_box), True, True, 0)

        row_buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        add_button = Gtk.Button(label="Add word")
        add_button.connect("clicked", self._on_add)
        save_button = Gtk.Button(label="Save")
        save_button.connect("clicked", self._on_save_clicked)
        self._status = Gtk.Label(xalign=0, use_markup=True)
        row_buttons.pack_start(add_button, False, False, 0)
        row_buttons.pack_start(save_button, False, False, 0)
        row_buttons.pack_start(self._status, True, True, 0)
        outer.pack_start(row_buttons, False, False, 0)

        outer.pack_start(
            self._heading("Auto", self._model.auto_path(),
                          "proposed by the app: candidates it did not apply, and the ones you accepted"),
            False, False, 0,
        )
        self._auto_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        outer.pack_start(self._scrolled(self._auto_box), True, True, 0)

        auto_buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        clear_button = Gtk.Button(label="Clear auto")
        clear_button.connect("clicked", self._on_clear_auto)
        auto_buttons.pack_start(clear_button, False, False, 0)
        outer.pack_start(auto_buttons, False, False, 0)

        self._window = window
        self._render()
        window.show_all()
        return False

    @staticmethod
    def _heading(title: str, path: Optional[Path], note: str) -> Gtk.Label:
        label = Gtk.Label(xalign=0, use_markup=True)
        label.set_markup(
            f"<b>{title}</b>  <small><i>{path or 'no file'}</i></small>\n"
            f"<small>{note}</small>"
        )
        return label

    @staticmethod
    def _scrolled(child: Gtk.Widget) -> Gtk.ScrolledWindow:
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.add(child)
        return scroller

    # -- rendering -----------------------------------------------------------

    def _render(self) -> None:
        self._render_rows(self._model.entries())
        self._render_auto(self._model.auto_entries(), self._model.candidates())

    def _render_rows(self, entries: Sequence[Entry]) -> None:
        for child in self._rows_box.get_children():
            self._rows_box.remove(child)
        self._rows = []

        for entry in entries:
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            word = Gtk.Entry(text=entry.word)
            word.set_width_chars(22)
            aliases = Gtk.Entry(text=", ".join(entry.aliases))
            aliases.set_width_chars(34)
            aliases.set_placeholder_text("misspellings it produces, comma separated")
            enabled = Gtk.CheckButton(label="on")
            enabled.set_active(entry.enabled)
            hits = Gtk.Label(label=f"{entry.hits} hit(s)")
            delete = Gtk.Button(label="✕")
            delete.connect("clicked", lambda _button, widget=word: self._on_delete_row(widget))

            for widget in (word, aliases, enabled):
                row.pack_start(widget, False, False, 0)
            row.pack_start(hits, False, False, 0)
            row.pack_start(delete, False, False, 0)
            self._rows_box.pack_start(row, False, False, 0)
            self._rows.append((word, aliases, enabled, entry.word))
        self._rows_box.show_all()

    def _render_auto(self, entries: Sequence[Entry], candidates: Sequence[Queued]) -> None:
        for child in self._auto_box.get_children():
            self._auto_box.remove(child)
        self._auto_rows = []

        if not entries and not candidates:
            self._auto_box.pack_start(
                Gtk.Label(xalign=0, label="Nothing here yet."), False, False, 0
            )

        for entry in entries:
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            word = Gtk.Entry(text=entry.word)
            word.set_width_chars(18)
            aliases = Gtk.Entry(text=", ".join(entry.aliases))
            aliases.set_width_chars(26)
            enabled = Gtk.CheckButton(label="on")
            enabled.set_active(entry.enabled)
            hits = Gtk.Label(label=f"{entry.hits} hit(s)")
            promote = Gtk.Button(label="→ mine")
            promote.connect("clicked", lambda _button, widget=word: self._on_promote_row(widget))
            delete = Gtk.Button(label="✕")
            delete.connect("clicked", lambda _button, widget=word: self._on_auto_delete_row(widget))

            for widget in (word, aliases, enabled):
                row.pack_start(widget, False, False, 0)
            row.pack_start(hits, False, False, 0)
            row.pack_start(promote, False, False, 0)
            row.pack_start(delete, False, False, 0)
            self._auto_box.pack_start(row, False, False, 0)
            self._auto_rows.append((word, aliases, enabled, entry.word))

        for index, candidate in enumerate(candidates):
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            label = Gtk.Label(
                xalign=0,
                label=f'heard "{candidate.token}" → "{candidate.suggestion}"'
                      f"  ({candidate.method}, distance {candidate.distance}, seen {candidate.count}×)",
            )
            accept_button = Gtk.Button(label="Add as alias")
            accept_button.connect("clicked", lambda _button, position=index: self._on_confirm(position))
            ignore = Gtk.Button(label="Ignore")
            ignore.connect("clicked", lambda _button, position=index: self._on_ignore(position))
            row.pack_start(label, True, True, 0)
            row.pack_start(accept_button, False, False, 0)
            row.pack_start(ignore, False, False, 0)
            self._auto_box.pack_start(row, False, False, 0)
        self._auto_box.show_all()

    def _set_status(self, message: str) -> None:
        if self._status is not None:
            self._status.set_markup(f"<small>{message}</small>")

    # -- collecting rows -----------------------------------------------------

    def _rows_to_entries(self, rows: Sequence[tuple], hits: dict) -> List[Entry]:
        """Rows with an empty word cannot be saved, so they drop."""
        entries: List[Entry] = []
        for word_widget, aliases_widget, enabled_widget, original in rows:
            word = word_widget.get_text().strip()
            if not word:
                continue
            entries.append(
                Entry(
                    word=word,
                    aliases=_clean_aliases(aliases_widget.get_text().split(",")),
                    enabled=enabled_widget.get_active(),
                    hits=hits.get(original.casefold(), 0),
                )
            )
        return entries

    def _current_entries(self, rows: Optional[Sequence[tuple]] = None) -> List[Entry]:
        return self._rows_to_entries(self._rows if rows is None else rows, self._hits)

    def _current_auto_entries(self, rows: Optional[Sequence[tuple]] = None) -> List[Entry]:
        return self._rows_to_entries(self._auto_rows if rows is None else rows, self._auto_hits)

    def _collect(self) -> None:
        self._model.set_entries(self._current_entries())
        self._model.set_auto_entries(self._current_auto_entries())

    # -- actions -------------------------------------------------------------

    def _on_add(self, _button) -> None:
        entries = self._current_entries()
        entries.append(Entry(word=""))
        self._render_rows(entries)
        for word_widget, _aliases, _enabled, _original in reversed(self._rows):
            if not word_widget.get_text().strip():
                word_widget.grab_focus()
                break
        self._set_status("Type the word, then press Save")

    def _on_delete_row(self, word_widget) -> None:
        remaining = [row for row in self._rows if row[0] is not word_widget]
        self._render_rows(self._current_entries(remaining))
        self._set_status("Removed — press Save to write it")

    def _on_auto_delete_row(self, word_widget) -> None:
        remaining = [row for row in self._auto_rows if row[0] is not word_widget]
        self._render_auto(self._current_auto_entries(remaining), self._model.candidates())
        self._set_status("Removed from Auto — press Save to write it")

    def _on_promote_row(self, word_widget) -> None:
        """Move an accepted auto word into your dictionary."""
        promoted = [row for row in self._auto_rows if row[0] is word_widget]
        if not promoted:
            return
        entry = self._rows_to_entries(promoted, self._auto_hits)[0]
        remaining = [row for row in self._auto_rows if row[0] is not word_widget]
        self._render_rows([*self._current_entries(), entry])
        self._render_auto(self._current_auto_entries(remaining), self._model.candidates())
        self._set_status(f"Moved '{entry.word}' into your dictionary — press Save")

    def _on_confirm(self, index: int) -> None:
        self._collect()
        self._model.accept_candidate(index)
        self._render()
        self._set_status("Accepted into Auto — press Save to write it")

    def _on_ignore(self, index: int) -> None:
        self._collect()
        self._model.ignore_candidate(index)
        self._render()
        self._set_status("Ignored — press Save to write it")

    def _on_clear_auto(self, _button) -> None:
        self._collect()
        self._model.clear_auto()
        self._render()
        self._set_status("Auto cleared — press Save to write it")

    def _on_save_clicked(self, _button) -> None:
        self._collect()
        try:
            self._model.save()
        except Exception as e:
            logger.warning("Could not save the dictionary: %s", e)
            self._set_status(f"Could not save: {e}")
            return
        self._model.reload()
        self._hits = {entry.word.casefold(): entry.hits for entry in self._model.entries()}
        self._auto_hits = {entry.word.casefold(): entry.hits for entry in self._model.auto_entries()}
        self._render()
        self._set_status("Saved — applies to your next dictation")

    def _on_key_press(self, _widget, event) -> bool:
        if event.keyval == 0xFF1B and self._window is not None:      # Escape
            self._window.destroy()
            return True
        return False


def open_dictionary_window(config: Config, pipeline: TextPipeline) -> None:
    """Show the dictionary window and block in the GTK main loop (used by `--dictionary`)."""
    window = DictionaryWindow(pipeline, quit_on_close=True)
    window.show()
    Gtk.main()
