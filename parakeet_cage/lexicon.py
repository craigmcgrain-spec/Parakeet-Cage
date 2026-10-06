"""Personal dictionary: teach the app the words this engine reliably mishears.

Measured on Parakeet Redux (see CHANGELOG 1.2.0): rare personal vocabulary fails even
with clean audio, and the errors are *phonetic* near-misses whose edit distance can
look large -- "kestrel" is heard as "Castrell", "Parakeet" as "Parakita".

Decoder-side hints are impossible for this model: the runtime answers
``"Parakeet TDT does not support an initial prompt"`` and rejects unknown options such
as ``hotwords``, so a dictionary can only act on the transcribed text.

Tiers (semi-confident matches are applied only to words the model does not know):

    exact     token equals an entry or one of its aliases -> always applied
    edit      edit distance <= max_distance                -> applied when the token is rare
    phonetic  consonant skeleton *exactly* equal           -> applied when the token is rare
    candidate a looser match (one skeleton edit away) or a match blocked by the rarity
              guard                                        -> queued for review, text untouched

The rarity signal is the model's own tokenizer: ordinary words it knows cost one or two
subword pieces ("our" 1, "socket" 2) while misheard rare words are spelled out
("castrell" 4, "parakita" 3). That is why "our -> OAuth" is queued instead of applied.
Skeleton *equality* is required for the same reason: "castle" is one skeleton edit from
"kestrel" and must never be rewritten on that basis.
"""

from __future__ import annotations

from dataclasses import dataclass, replace as _replace
import logging
import re
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple
import tomllib

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1
DEFAULT_MAX_DISTANCE = 2
MAX_SKELETON_DISTANCE = 1     # review threshold: closer than this is a plausible candidate
MIN_FUZZY_LENGTH = 3
PROTECTED_PIECES = 2

EXACT = "exact"
EDIT = "edit"
PHONETIC = "phonetic"

_WORD = re.compile(r"[^\W_]+(?:['’\-][^\W_]+)*", re.UNICODE)
_PUNCTUATION = frozenset(".,;:!?…—–-\"'()[]{}")


@dataclass
class Entry:
    """One vocabulary item: the spelling to write, plus spellings the model produces."""

    word: str
    aliases: Tuple[str, ...] = ()
    enabled: bool = True
    hits: int = 0

    @property
    def forms(self) -> Tuple[str, ...]:
        return (self.word, *self.aliases)


@dataclass(frozen=True)
class Applied:
    before: str
    after: str
    word: str
    method: str


@dataclass(frozen=True)
class Queued:
    token: str
    suggestion: str
    method: str
    distance: int
    count: int = 1


@dataclass(frozen=True)
class Result:
    text: str
    applied: Tuple[Applied, ...] = ()
    queued: Tuple[Queued, ...] = ()


PieceCost = Callable[[str], int]


def piece_counter_for(tokenizer_path: Path) -> Optional[PieceCost]:
    """Subword-piece counter for a model tokenizer, or None when it cannot be loaded.

    None disables the fuzzy tiers: with no way to tell a known word from a misheard one,
    guessing would risk rewriting words the user meant.
    """
    tokenizer_path = Path(tokenizer_path)
    try:
        from tokenizers import Tokenizer
    except ImportError as e:
        logger.warning("tokenizers unavailable, dictionary matching is exact-match only: %s", e)
        return None

    if not tokenizer_path.exists():
        logger.warning("tokenizer not found at %s, dictionary matching is exact-match only", tokenizer_path)
        return None

    tokenizer = Tokenizer.from_file(str(tokenizer_path))
    cache: Dict[str, int] = {}

    def cost(token: str) -> int:
        key = token.casefold()
        if key not in cache:
            cache[key] = len(tokenizer.encode(token, add_special_tokens=False).tokens)
        return cache[key]

    return cost


def _edit_distance(left: str, right: str) -> int:
    if left == right:
        return 0
    if not left:
        return len(right)
    if not right:
        return len(left)
    previous = list(range(len(right) + 1))
    for i, lch in enumerate(left, 1):
        current = [i]
        for j, rch in enumerate(right, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (lch != rch)))
        previous = current
    return previous[-1]


def _skeleton(word: str) -> str:
    """Consonant skeleton: the cheapest way to recognise a misheard rare word."""
    text = word.casefold().replace("ph", "f").replace("ck", "k").replace("qu", "k").replace("x", "ks")
    text = "".join(char for char in text if char.isalpha())
    text = text.replace("c", "k").replace("q", "k").replace("z", "s").replace("v", "f")
    if not text:
        return ""
    out, previous = text[0], text[0]
    for char in text[1:]:
        if char in "aeiouyh" or char == previous:
            continue
        out, previous = out + char, char
    return out


def _is_sentence_initial(text: str, start: int) -> bool:
    prefix = text[:start].rstrip()
    return not prefix or prefix[-1] in ".?!…\n"


def _mirror(source: str, replacement: str, sentence_initial: bool) -> str:
    """Replacement casing.

    ALLCAPS input is preserved (the user shouted or spelled it out) and a capitalised
    token at the start of a sentence keeps its capital. A Capitalised token *inside* a
    sentence is the model's own habit of treating anything rare as a proper noun
    ("we use Castrell for this" for "kestrel"), so it does not survive; entries with
    intentional casing (gRPC, PostgreSQL, Möbius) are always written verbatim.

    Capitalisation is never invented: a lowercase source stays lowercase.
    """
    if len(source) > 1 and source.isupper():
        return replacement.upper()
    if sentence_initial and source[:1].isupper() and replacement.islower():
        return replacement[:1].upper() + replacement[1:]
    return replacement


def _mirror_phrase(match_text: str, replacement: str) -> str:
    return replacement.upper() if len(match_text) > 1 and match_text.isupper() else replacement


def _phrase_pattern(phrase: str) -> str:
    return r"\s+".join(re.escape(word) for word in phrase.split())


def _write_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def _toml_string(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def read_queue(path) -> List[Queued]:
    """Candidates awaiting review, as written by blocked dictionary matches."""
    path = Path(path)
    if not path.exists():
        return []
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning("Candidate queue %s is unreadable (%s); ignoring it", path, e)
        return []
    candidates: List[Queued] = []
    for row in data.get("candidate", []):
        heard = str(row.get("heard", "")).strip()
        if not heard:
            continue
        candidates.append(
            Queued(
                token=heard,
                suggestion=str(row.get("suggested", "")).strip(),
                method=str(row.get("method", "")),
                distance=int(row.get("distance", 0)),
                count=int(row.get("count", 1)),
            )
        )
    return candidates


def write_queue(path, candidates: Sequence[Queued]) -> None:
    lines = [f"schema_version = {SCHEMA_VERSION}", ""]
    for candidate in candidates:
        lines.append("[[candidate]]")
        lines.append(f"heard = {_toml_string(candidate.token)}")
        lines.append(f"suggested = {_toml_string(candidate.suggestion)}")
        lines.append(f"method = {_toml_string(candidate.method)}")
        lines.append(f"distance = {candidate.distance}")
        lines.append(f"count = {candidate.count}")
        lines.append("")
    _write_atomic(Path(path), "\n".join(lines))


class Lexicon:
    """Applies a personal dictionary to transcribed text."""

    def __init__(
        self,
        entries: Iterable[Entry],
        piece_cost: Optional[PieceCost] = None,
        queue_path: Optional[Path] = None,
        max_distance: int = DEFAULT_MAX_DISTANCE,
        source_path: Optional[Path] = None,
    ) -> None:
        self.entries: List[Entry] = list(entries)
        self.piece_cost = piece_cost
        self.queue_path = Path(queue_path) if queue_path else None
        self.max_distance = max_distance
        self.source_path = Path(source_path) if source_path else None
        self._loaded_stamp: Optional[int] = self._stamp()

    def _stamp(self) -> Optional[int]:
        """Modification time of the dictionary file, or None when there is no file."""
        if self.source_path is None:
            return None
        try:
            return self.source_path.stat().st_mtime_ns
        except OSError:
            return None

    def reload_if_changed(self) -> bool:
        """Pick up edits made outside this process: hand edits or the dictionary window.

        Called before each utterance, so a saved change applies to the very next dictation.
        """
        if self.source_path is None:
            return False
        stamp = self._stamp()
        if stamp is None or stamp == self._loaded_stamp:
            return False
        fresh = Lexicon.load(
            self.source_path,
            piece_cost=self.piece_cost,
            queue_path=self.queue_path,
            max_distance=self.max_distance,
        )
        self.entries = fresh.entries
        self._loaded_stamp = fresh._loaded_stamp
        logger.debug("Reloaded the dictionary: %d entries", len(self.entries))
        return True

    # -- loading and persistence ---------------------------------------------

    @classmethod
    def load(
        cls,
        path: Path,
        piece_cost: Optional[PieceCost] = None,
        queue_path: Optional[Path] = None,
        max_distance: int = DEFAULT_MAX_DISTANCE,
    ) -> "Lexicon":
        path = Path(path)
        entries: List[Entry] = []
        if path.exists():
            try:
                data = tomllib.loads(path.read_text(encoding="utf-8"))
                for row in data.get("word", []):
                    word = str(row.get("word", "")).strip()
                    if not word:
                        continue
                    aliases = tuple(str(a).strip() for a in row.get("aliases", ()) if str(a).strip())
                    entries.append(
                        Entry(
                            word=word,
                            aliases=aliases,
                            enabled=bool(row.get("enabled", True)),
                            hits=int(row.get("hits", 0)),
                        )
                    )
            except Exception as e:
                logger.warning("Lexicon %s is unreadable (%s); continuing without it", path, e)
        return cls(entries, piece_cost=piece_cost, queue_path=queue_path,
                   max_distance=max_distance, source_path=path)

    def _entries_text(self) -> str:
        lines = [f"schema_version = {SCHEMA_VERSION}", ""]
        for entry in self.entries:
            lines.append("[[word]]")
            lines.append(f"word = {_toml_string(entry.word)}")
            if entry.aliases:
                aliases = ", ".join(_toml_string(alias) for alias in entry.aliases)
                lines.append(f"aliases = [{aliases}]")
            lines.append(f"enabled = {'true' if entry.enabled else 'false'}")
            lines.append(f"hits = {entry.hits}")
            lines.append("")
        return "\n".join(lines)

    def _queue_text(self, candidates: Sequence[Queued]) -> str:
        lines = [f"schema_version = {SCHEMA_VERSION}", ""]
        for candidate in candidates:
            lines.append("[[candidate]]")
            lines.append(f"heard = {_toml_string(candidate.token)}")
            lines.append(f"suggested = {_toml_string(candidate.suggestion)}")
            lines.append(f"method = {_toml_string(candidate.method)}")
            lines.append(f"distance = {candidate.distance}")
            lines.append("count = 1")
            lines.append("")
        return "\n".join(lines)

    def _persist_hits(self, path: Path) -> None:
        """Update only the `hits = N` values, in place.

        The lexicon is a file the user hand-edits, so comments, formatting and ordering must
        survive a counter update. Only a file we cannot line up is rewritten outright.
        """
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            _write_atomic(path, self._entries_text())
            return

        blocks = list(re.finditer(r"^\[\[word\]\]", text, re.MULTILINE))
        if len(blocks) != len(self.entries):
            _write_atomic(path, self._entries_text())
            return

        pieces: List[str] = []
        position = 0
        for index, block in enumerate(blocks):
            end = blocks[index + 1].start() if index + 1 < len(blocks) else len(text)
            body = text[block.start():end]
            updated, replaced = re.subn(
                r"(?m)^hits\s*=\s*-?\d+",
                f"hits = {self.entries[index].hits}",
                body,
                count=1,
            )
            if not replaced:
                _write_atomic(path, self._entries_text())
                return
            pieces.append(text[position:block.start()])
            pieces.append(updated)
            position = end
        pieces.append(text[position:])

        _write_atomic(path, "".join(pieces))
        self._loaded_stamp = self._stamp()

    # -- editing (used by the dictionary window) ------------------------------

    @staticmethod
    def _block_entry(body: str) -> Optional[Entry]:
        """The entry a `[[word]]` block currently expresses, with TOML defaults applied."""
        word_match = re.search(r'(?m)^\s*word\s*=\s*"([^"]*)"', body)
        if not word_match:
            return None
        aliases_match = re.search(r"(?m)^\s*aliases\s*=\s*\[(.*?)\]", body)
        aliases: Tuple[str, ...] = ()
        if aliases_match and aliases_match.group(1).strip():
            aliases = tuple(part.strip().strip('"') for part in aliases_match.group(1).split(",") if part.strip())
        hits_match = re.search(r"(?m)^\s*hits\s*=\s*(\d+)", body)
        return Entry(
            word=word_match.group(1),
            aliases=aliases,
            enabled=not re.search(r"(?m)^\s*enabled\s*=\s*false", body),
            hits=int(hits_match.group(1)) if hits_match else 0,
        )

    def _render_block(self, entry: Entry) -> str:
        lines = ["[[word]]", f"word = {_toml_string(entry.word)}"]
        if entry.aliases:
            lines.append("aliases = [" + ", ".join(_toml_string(alias) for alias in entry.aliases) + "]")
        lines.append(f"enabled = {'true' if entry.enabled else 'false'}")
        lines.append(f"hits = {entry.hits}")
        return "\n".join(lines) + "\n"

    @staticmethod
    def _rewrite_block(body: str, entry: Entry) -> str:
        """Replace one block's values, leaving its comments, spacing and ordering alone."""

        def set_line(pattern: str, replacement: str) -> None:
            nonlocal body
            if re.search(pattern, body, re.MULTILINE):
                body = re.sub(pattern, replacement.replace("\\", "\\\\"), body, count=1, flags=re.MULTILINE)
            else:
                body = body.rstrip("\n") + f"\n{replacement}\n\n"

        set_line(r'(?m)^\s*word\s*=\s*".*"', f"word = {_toml_string(entry.word)}")
        if entry.aliases:
            values = ", ".join(_toml_string(alias) for alias in entry.aliases)
            set_line(r"(?m)^\s*aliases\s*=\s*\[.*\]", f"aliases = [{values}]")
        else:
            body = re.sub(r"(?m)^\s*aliases\s*=\s*\[.*\]\n", "", body, count=1)
        set_line(r"(?m)^\s*enabled\s*=\s*(?:true|false)", f"enabled = {'true' if entry.enabled else 'false'}")
        set_line(r"(?m)^\s*hits\s*=\s*-?\d+", f"hits = {entry.hits}")
        return body

    def save_entries(self, entries: Sequence[Entry]) -> None:
        """Reconcile the dictionary file with `entries`, preserving hand-written content.

        Blocks are matched by word: kept blocks are only touched where a value differs, new
        words are appended, deleted words lose their block. Everything else in the file —
        comments, blank lines, ordering — is left exactly as the user wrote it.
        """
        new_entries = list(entries)
        path = self.source_path

        if path is None or not path.exists():
            if path is not None:
                _write_atomic(path, "\n".join(self._render_block(e) for e in new_entries))
            self.entries = new_entries
            return

        text = path.read_text(encoding="utf-8")
        blocks = list(re.finditer(r"^\[\[word\]\]", text, re.MULTILINE))
        remaining = {entry.word: entry for entry in new_entries}
        pieces: List[str] = []
        position = 0
        kept: List[str] = []

        for index, block in enumerate(blocks):
            end = blocks[index + 1].start() if index + 1 < len(blocks) else len(text)
            body = text[block.start():end]
            current = self._block_entry(body)
            target = remaining.pop(current.word, None) if current else None
            pieces.append(text[position:block.start()])
            if target is not None:
                kept.append(target.word)
                pieces.append(body if current == target else self._rewrite_block(body, target))
            position = end
        pieces.append(text[position:])

        result = "".join(pieces)
        appended = [entry for entry in new_entries if entry.word not in kept]
        if appended:
            if not result.endswith("\n"):
                result += "\n"
            result += "\n" + "\n".join(self._render_block(entry) for entry in appended)

        if result != text:
            _write_atomic(path, result)
        self.entries = new_entries
        self._loaded_stamp = self._stamp()

    def record(self, result: Result) -> None:
        """Persist hit counters and queue the blocked candidates. Never raises."""
        if not result.applied and not result.queued:
            return          # nothing to persist: never rewrite the user's files needlessly
        try:
            if self.source_path is not None:
                self._persist_hits(self.source_path)
            if result.queued and self.queue_path is not None:
                self._merge_queue(result.queued)
        except Exception as e:
            logger.warning("Could not persist dictionary state: %s", e)

    def _merge_queue(self, queued: Sequence[Queued]) -> None:
        existing = read_queue(self.queue_path)
        counts = {(c.token, c.suggestion, c.method, c.distance): c.count for c in existing}
        originals = {(c.token, c.suggestion, c.method, c.distance): c for c in existing}
        order = [(c.token, c.suggestion, c.method, c.distance) for c in existing]
        for candidate in queued:
            key = (candidate.token, candidate.suggestion, candidate.method, candidate.distance)
            if not key[0]:
                continue
            if key not in counts:
                order.append(key)
                counts[key] = 0
                originals[key] = candidate
            counts[key] += candidate.count

        write_queue(self.queue_path, [_replace(originals[key], count=counts[key]) for key in order])

    # -- matching ------------------------------------------------------------

    def _protected(self, token: str) -> bool:
        if self.piece_cost is None:
            return False
        try:
            return self.piece_cost(token) <= PROTECTED_PIECES
        except Exception as e:
            logger.debug("Piece count failed for %r: %s", token, e)
            return False

    def _fuzzy_available(self) -> bool:
        return self.piece_cost is not None

    def _best_match(self, token: str) -> Optional[Tuple[str, int, Entry, bool]]:
        """Closest (method, distance, entry, applicable) for a token, or None.

        `applicable` is False for matches that are only plausible: those are reported for
        review instead of being written into the user's text.
        """
        key = token.casefold()
        if len(token) < MIN_FUZZY_LENGTH or not self._fuzzy_available():
            return None
        best: Optional[Tuple[str, int, Entry, bool]] = None
        for entry in self.entries:
            if not entry.enabled:
                continue
            for form in entry.forms:
                form_key = form.casefold()
                if key == form_key:
                    continue
                distance_edit = _edit_distance(key, form_key)
                if distance_edit <= self.max_distance:
                    candidate = (EDIT, distance_edit, entry, True)
                else:
                    distance_skeleton = _edit_distance(_skeleton(token), _skeleton(form))
                    if distance_skeleton > MAX_SKELETON_DISTANCE:
                        continue
                    candidate = (PHONETIC, distance_skeleton, entry, distance_skeleton == 0)
                if best is None or candidate[1] < best[1]:
                    best = candidate
        return best

    def _exact_match(self, token: str) -> Optional[Entry]:
        key = token.casefold()
        for entry in self.entries:
            if not entry.enabled:
                continue
            if any(key == form.casefold() for form in entry.forms):
                return entry
        return None

    def apply(self, text: str) -> Result:
        """Apply the dictionary to `text`, counting hits; `record()` persists them.

        The engine reports what it did without writing anything to disk.
        """
        if not text or not self.entries:
            return Result(text=text)

        applied: List[Applied] = []
        queued: List[Queued] = []

        text = self._apply_phrases(text, applied)

        pieces: List[str] = []
        position = 0
        for match in _WORD.finditer(text):
            token = match.group(0)
            if token.isdigit():
                continue
            entry = self._exact_match(token)
            replacement: Optional[str] = None
            if entry is not None:
                replacement = _mirror(token, entry.word, _is_sentence_initial(text, match.start()))
                method = EXACT
            else:
                match_info = self._best_match(token)
                if match_info is not None:
                    method, distance, entry, applicable = match_info
                    if applicable and not self._protected(token):
                        replacement = _mirror(token, entry.word,
                                              _is_sentence_initial(text, match.start()))
                    else:
                        queued.append(Queued(token=token, suggestion=entry.word,
                                             method=method, distance=distance))
            if replacement is not None and replacement != token:
                pieces.append(text[position:match.start()])
                pieces.append(replacement)
                position = match.end()
                entry.hits += 1
                applied.append(Applied(before=token, after=replacement, word=entry.word, method=method))
        pieces.append(text[position:])

        return Result(text="".join(pieces), applied=tuple(applied), queued=tuple(queued))

    def _apply_phrases(self, text: str, applied: List[Applied]) -> str:
        """Entries containing a space are matched as phrases, canonical form verbatim."""
        phrases: List[Tuple[str, Entry]] = []
        for entry in self.entries:
            if not entry.enabled:
                continue
            for form in entry.forms:
                if " " in form.strip():
                    phrase = " ".join(form.split())
                    if not any(existing == phrase.casefold() for existing, _ in phrases):
                        phrases.append((phrase, entry))
        if not phrases:
            return text

        longest_first = sorted(phrases, key=lambda item: len(item[0]), reverse=True)
        pattern = re.compile(
            rf"(?<!\w)({'|'.join(_phrase_pattern(p) for p, _ in longest_first)})(?!\w)",
            re.IGNORECASE,
        )
        by_form = {" ".join(phrase.split()).casefold(): entry for phrase, entry in longest_first}

        def substitute(match: "re.Match[str]") -> str:
            matched = match.group(0)
            entry = by_form[" ".join(matched.split()).casefold()]
            after = _mirror_phrase(matched, entry.word)
            entry.hits += 1
            applied.append(Applied(before=matched, after=after, word=entry.word, method=EXACT))
            return after

        return pattern.sub(substitute, text)
