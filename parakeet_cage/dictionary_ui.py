"""Dictionary window: manage the personal vocabulary without editing TOML by hand.

The GTK layer is deliberately thin. Everything that decides what happens to the two files —
which entry a candidate belongs to, what gets written, what is dropped — lives in
`DictionaryModel`, which has no widgets in it and is tested without a display.
"""

from __future__ import annotations

from dataclasses import replace
import logging
from pathlib import Path
from typing import Callable, List, Optional, Sequence

import gi

try:
    gi.require_version("Gdk", "3.0")
    gi.require_version("Gtk", "3.0")
except ValueError:
    pass
from gi.repository import Gtk, GLib

from parakeet_cage.config import Config
from parakeet_cage.lexicon import Entry, Queued, read_queue, write_queue
from parakeet_cage.postprocess import TextPipeline

logger = logging.getLogger(__name__)


class DictionaryModel:
    """Entries and queued candidates, and the rules for changing them.

    Edits stay in memory until `save()`, so a window can be abandoned without touching
    the dictionary the daemon is using.
    """

    def __init__(self, pipeline: TextPipeline) -> None:
        self._pipeline = pipeline
        self._entries: List[Entry] = []
        self._candidates: List[Queued] = []
        self.reload()

    # -- state ---------------------------------------------------------------

    def reload(self) -> None:
        """Read both files, picking up hand edits made outside the window."""
        lexicon = self._pipeline.lexicon
        if lexicon is not None:
            lexicon.reload_if_changed()
            self._entries = [replace(entry) for entry in lexicon.entries]
        else:
            self._entries = []
        queue = self.queue_path()
        self._candidates = read_queue(queue) if queue is not None else []

    def entries(self) -> List[Entry]:
        return list(self._entries)

    def candidates(self) -> List[Queued]:
        return list(self._candidates)

    def lexicon_path(self) -> Optional[Path]:
        lexicon = self._pipeline.lexicon
        return lexicon.source_path if lexicon is not None else None

    def queue_path(self) -> Optional[Path]:
        lexicon = self._pipeline.lexicon
        return lexicon.queue_path if lexicon is not None else None

    # -- entries -------------------------------------------------------------

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

    def set_entries(self, entries: Sequence[Entry]) -> None:
        """Replace the working set: while the window is open, its rows are the truth."""
        self._entries = list(entries)

    # -- candidates ----------------------------------------------------------

    def confirm_candidate(self, index: int) -> None:
        """Accept a suggestion: the heard spelling becomes an alias of the suggested word."""
        candidate = self._candidates[index]
        target = next(
            (position for position, entry in enumerate(self._entries)
             if entry.word.casefold() == candidate.suggestion.casefold()),
            None,
        )
        if target is None:
            self._entries.append(Entry(word=candidate.suggestion, aliases=(candidate.token,)))
        else:
            entry = self._entries[target]
            known = {alias.casefold() for alias in entry.aliases}
            if candidate.token.casefold() != entry.word.casefold() and candidate.token.casefold() not in known:
                self._entries[target] = replace(entry, aliases=(*entry.aliases, candidate.token))
        del self._candidates[index]

    def ignore_candidate(self, index: int) -> None:
        del self._candidates[index]

    # -- persistence ---------------------------------------------------------

    def save(self) -> None:
        self._pipeline.save_entries(self._entries)
        queue = self.queue_path()
        if queue is not None:
            write_queue(queue, self._candidates)


def _clean_aliases(aliases: Optional[Sequence[str]]) -> tuple:
    return tuple(dict.fromkeys(alias.strip() for alias in (aliases or ()) if alias.strip()))


class DictionaryWindow:
    """GTK 3 window listing dictionary entries and the candidates awaiting review."""

    def __init__(self, pipeline: TextPipeline, quit_on_close: bool = False) -> None:
        self._model = DictionaryModel(pipeline)
        self._quit_on_close = quit_on_close
        self._rows: List[tuple] = []
        self._hits: dict = {}
        self._window: Optional[Gtk.Window] = None
        self._status: Optional[Gtk.Label] = None

    def show(self) -> None:
        """Build and present the window on the GLib main loop."""
        GLib.idle_add(self._create_and_show)

    # -- construction --------------------------------------------------------

    def _create_and_show(self) -> bool:
        for entry in self._model.entries():
            self._hits[entry.word.casefold()] = entry.hits

        window = Gtk.Window(title="Parakeet Cage — Dictionary")
        window.set_default_size(820, 560)
        window.set_position(Gtk.WindowPosition.CENTER)
        window.set_border_width(12)
        window.connect("key-press-event", self._on_key_press)
        if self._quit_on_close:
            window.connect("destroy", Gtk.main_quit)

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        window.add(outer)

        path = self._model.lexicon_path()
        words = Gtk.Label(xalign=0, use_markup=True)
        words.set_markup(
            "<b>Words</b>\n<small><i>"
            + (str(path) if path else "no dictionary file")
            + "</i></small>"
        )
        outer.pack_start(words, False, False, 0)

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

        header = Gtk.Label(xalign=0, use_markup=True)
        header.set_markup(
            "<b>Suggested from what it misheard</b>\n"
            "<small><i>Accepting one adds the heard spelling as an alias of the suggestion.</i></small>"
        )
        outer.pack_start(header, False, False, 0)

        self._candidates_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        outer.pack_start(self._scrolled(self._candidates_box), True, True, 0)

        self._window = window
        self._render()
        window.show_all()
        return False

    @staticmethod
    def _scrolled(child: Gtk.Widget) -> Gtk.ScrolledWindow:
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.add(child)
        return scroller

    # -- rendering -----------------------------------------------------------

    def _render(self) -> None:
        self._render_rows(self._model.entries())
        self._render_candidates()

    def _render_rows(self, entries: Sequence[Entry]) -> None:
        for child in self._rows_box.get_children():
            self._rows_box.remove(child)
        self._rows = []

        for index, entry in enumerate(entries):
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

    def _render_candidates(self) -> None:
        for child in self._candidates_box.get_children():
            self._candidates_box.remove(child)

        candidates = self._model.candidates()
        if not candidates:
            self._candidates_box.pack_start(
                Gtk.Label(xalign=0, label="Nothing waiting for review."), False, False, 0
            )
        for index, candidate in enumerate(candidates):
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            label = Gtk.Label(
                xalign=0,
                label=f'heard "{candidate.token}" → "{candidate.suggestion}"'
                      f"  ({candidate.method}, distance {candidate.distance}, seen {candidate.count}×)",
            )
            accept = Gtk.Button(label="Add as alias")
            accept.connect("clicked", lambda _button, position=index: self._on_confirm(position))
            ignore = Gtk.Button(label="Ignore")
            ignore.connect("clicked", lambda _button, position=index: self._on_ignore(position))
            row.pack_start(label, True, True, 0)
            row.pack_start(accept, False, False, 0)
            row.pack_start(ignore, False, False, 0)
            self._candidates_box.pack_start(row, False, False, 0)
        self._candidates_box.show_all()

    def _set_status(self, message: str) -> None:
        if self._status is not None:
            self._status.set_markup(f"<small>{message}</small>")

    # -- actions -------------------------------------------------------------

    def _current_entries(self, rows: Optional[Sequence[tuple]] = None) -> List[Entry]:
        """What the rows say right now; rows with an empty word cannot be saved, so they drop."""
        entries: List[Entry] = []
        for word_widget, aliases_widget, enabled_widget, original in (self._rows if rows is None else rows):
            word = word_widget.get_text().strip()
            if not word:
                continue
            entries.append(
                Entry(
                    word=word,
                    aliases=_clean_aliases(aliases_widget.get_text().split(",")),
                    enabled=enabled_widget.get_active(),
                    hits=self._hits.get(original.casefold(), 0),
                )
            )
        return entries

    def _collect_rows(self) -> None:
        self._model.set_entries(self._current_entries())

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

    def _on_confirm(self, index: int) -> None:
        self._collect_rows()
        self._model.confirm_candidate(index)
        self._render()
        self._set_status("Accepted — press Save to write it")

    def _on_ignore(self, index: int) -> None:
        self._collect_rows()
        self._model.ignore_candidate(index)
        self._render()
        self._set_status("Ignored — press Save to write it")

    def _on_save_clicked(self, _button) -> None:
        self._collect_rows()
        try:
            self._model.save()
        except Exception as e:
            logger.warning("Could not save the dictionary: %s", e)
            self._set_status(f"Could not save: {e}")
            return
        self._model.reload()
        self._hits = {entry.word.casefold(): entry.hits for entry in self._model.entries()}
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
