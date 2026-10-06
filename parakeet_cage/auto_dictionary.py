"""The auto dictionary: what the app proposed, kept apart from the words you entered.

Two stores, deliberately:

* `lexicon.toml` — your dictionary. Only you add to it.
* `auto.toml` — this file. `[[candidate]]` blocks are near-misses the app noticed but never
  touched your text with; `[[word]]` blocks are candidates you accepted. Accepting one keeps
  it here, so a machine-proposed word never becomes indistinguishable from one you typed.

Both are applied when dictating: your entries first, then the auto ones.
"""

from __future__ import annotations

from dataclasses import replace
import logging
from pathlib import Path
from typing import List, Optional, Sequence
import tomllib

from parakeet_cage.lexicon import (
    Entry,
    Lexicon,
    Queued,
    entry_from_row,
    queued_from_rows,
    read_queue,
    render_candidate_block,
    render_entry_block,
    write_atomic,
)

logger = logging.getLogger(__name__)

FILE_HEADER = """# Parakeet Cage auto dictionary
#
# The contents are managed by Parakeet Cage: `[[candidate]]` entries are words it heard but
# refused to apply, `[[word]]` entries are the ones you accepted. Your own words live in
# lexicon.toml, so the two never mix.
#
# `parakeet-cage --dictionary` edits this file; `parakeet-cage --pending` lists candidates.
"""


def accept(entries: List[Entry], candidates: List[Queued], index: int) -> None:
    """Accept the candidate at `index`: the heard spelling becomes an alias of the suggestion.

    Shared by the store and the editor window, so both behave identically.
    """
    candidate = candidates[index]
    target = next(
        (position for position, entry in enumerate(entries)
         if entry.word.casefold() == candidate.suggestion.casefold()),
        None,
    )
    if target is None:
        entries.append(Entry(word=candidate.suggestion, aliases=(candidate.token,)))
    else:
        entry = entries[target]
        known = {alias.casefold() for alias in entry.aliases}
        if candidate.token.casefold() != entry.word.casefold() and candidate.token.casefold() not in known:
            entries[target] = replace(entry, aliases=(*entry.aliases, candidate.token))
    del candidates[index]


class AutoDictionary:
    """Candidates observed by the app plus the ones accepted, in their own file."""

    def __init__(self, path, piece_cost=None, max_distance: int = 2) -> None:
        self.path = Path(path)
        self.piece_cost = piece_cost
        self.max_distance = max_distance
        self._entries: List[Entry] = []
        self._candidates: List[Queued] = []
        self._loaded_stamp: Optional[int] = None

    # -- loading and persistence ---------------------------------------------

    @classmethod
    def load(
        cls,
        path,
        piece_cost=None,
        max_distance: int = 2,
        legacy_queue_path=None,
    ) -> "AutoDictionary":
        auto = cls(path, piece_cost=piece_cost, max_distance=max_distance)
        auto.reload(legacy_queue_path=legacy_queue_path)
        return auto

    def _stamp(self) -> Optional[int]:
        try:
            return self.path.stat().st_mtime_ns
        except OSError:
            return None

    def reload(self, legacy_queue_path=None) -> None:
        """Read the file, or import an older standalone candidate queue if there is one."""
        self._entries = []
        self._candidates = []
        if self.path.exists():
            try:
                data = tomllib.loads(self.path.read_text(encoding="utf-8"))
            except Exception as e:
                logger.warning("Auto dictionary %s is unreadable (%s); ignoring it", self.path, e)
                self._loaded_stamp = self._stamp()
                return
            self._entries = [entry for entry in (entry_from_row(row) for row in data.get("word", [])) if entry]
            self._candidates = queued_from_rows(data.get("candidate", []))
        elif legacy_queue_path is not None and Path(legacy_queue_path).exists():
            self._candidates = read_queue(legacy_queue_path)
        self._loaded_stamp = self._stamp()

    def reload_if_changed(self) -> bool:
        stamp = self._stamp()
        if stamp == self._loaded_stamp:
            return False
        self.reload()
        return True

    def save(self) -> None:
        blocks = [render_candidate_block(c) for c in self._candidates]
        blocks += [render_entry_block(e) for e in self._entries]
        body = f"schema_version = 1\n\n" + "\n\n".join(blocks) + ("\n" if blocks else "")
        write_atomic(self.path, FILE_HEADER + "\n" + body)
        self._loaded_stamp = self._stamp()

    # -- accessors -----------------------------------------------------------

    def entries(self) -> List[Entry]:
        return list(self._entries)

    def candidates(self) -> List[Queued]:
        return list(self._candidates)

    def is_empty(self) -> bool:
        return not self._entries and not self._candidates

    def lexicon_view(self) -> Lexicon:
        """A matcher over the accepted entries; hits are counted on these same objects."""
        return Lexicon(self._entries, piece_cost=self.piece_cost, max_distance=self.max_distance)

    # -- mutation ------------------------------------------------------------

    def add_entry(self, word: str, aliases: Sequence[str] = ()) -> bool:
        word = word.strip()
        if not word or any(entry.word.casefold() == word.casefold() for entry in self._entries):
            return False
        self._entries.append(Entry(word=word, aliases=tuple(a.strip() for a in aliases if a.strip())))
        return True

    def update_entry(
        self,
        index: int,
        aliases: Optional[Sequence[str]] = None,
        enabled: Optional[bool] = None,
    ) -> None:
        entry = self._entries[index]
        self._entries[index] = replace(
            entry,
            aliases=tuple(a.strip() for a in aliases if a.strip()) if aliases is not None else entry.aliases,
            enabled=entry.enabled if enabled is None else bool(enabled),
        )

    def remove_entry(self, index: int) -> None:
        del self._entries[index]

    def add_candidate(self, candidate: Queued) -> None:
        for position, existing in enumerate(self._candidates):
            if (existing.token, existing.suggestion) == (candidate.token, candidate.suggestion):
                self._candidates[position] = replace(existing, count=existing.count + candidate.count)
                return
        self._candidates.append(candidate)

    def accept_candidate(self, index: int) -> None:
        """Accept a candidate: it becomes an auto entry, *not* one of your own words."""
        accept(self._entries, self._candidates, index)

    def ignore_candidate(self, index: int) -> None:
        del self._candidates[index]

    def set_entries(self, entries: Sequence[Entry]) -> None:
        """Replace the accepted entries (the editor window stages its rows this way)."""
        self._entries = list(entries)

    def set_candidates(self, candidates: Sequence[Queued]) -> None:
        self._candidates = list(candidates)

    def promote_entry(self, index: int) -> Entry:
        """Hand an accepted entry over to your own dictionary and drop it from here."""
        return self._entries.pop(index)

    def clear(self) -> None:
        self._entries = []
        self._candidates = []
