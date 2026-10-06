"""Two-stage transcript post-processing: spoken punctuation, then the personal dictionary.

Stages are independent and individually switchable, and neither may ever break
dictation: if a stage raises, it is logged, skipped, and the text continues to the
clipboard.

The pipeline never writes to disk while producing text — `process()` is safe to call
anywhere, `record()` persists hit counters and queued candidates afterwards.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
import os
from pathlib import Path
from typing import Dict, Mapping, Optional, Tuple

from parakeet_cage.config import TextConfig
from parakeet_cage.lexicon import Applied, Lexicon, Queued, Result, piece_counter_for
from parakeet_cage.textnorm import apply_spoken_punctuation

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Change:
    """What one utterance looked like before and after post-processing."""

    raw: str
    final: str
    applied: Tuple[Applied, ...] = ()
    queued: Tuple[Queued, ...] = ()

    @property
    def corrected(self) -> bool:
        return self.final != self.raw


def default_lexicon_path() -> Path:
    """Where the user's personal dictionary lives."""
    config_home = os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config")
    return Path(config_home) / "parakeet-cage" / "lexicon.toml"


def default_queue_path() -> Path:
    """Where blocked dictionary candidates wait for review."""
    data_home = os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share")
    return Path(data_home) / "parakeet-cage" / "learning" / "pending.toml"


class TextPipeline:
    """Applies spoken punctuation and the personal dictionary to a transcript."""

    def __init__(
        self,
        punctuation: bool = True,
        punctuation_extra: Optional[Mapping[str, str]] = None,
        lexicon: Optional[Lexicon] = None,
    ) -> None:
        self.punctuation = punctuation
        self.punctuation_extra: Dict[str, str] = dict(punctuation_extra or {})
        self.lexicon = lexicon

    def _commands(self) -> Optional[Dict[str, Optional[str]]]:
        if not self.punctuation_extra:
            return None
        # an empty symbol disables a built-in command
        return {command: (symbol if symbol else None) for command, symbol in self.punctuation_extra.items()}

    def process(self, text: str) -> Change:
        """Run both stages. Stage failures are logged and skipped."""
        final = text

        if self.punctuation:
            try:
                final = apply_spoken_punctuation(final, self._commands())
            except Exception as e:
                logger.warning("Spoken punctuation failed (%s); continuing without it", e)

        applied: Tuple[Applied, ...] = ()
        queued: Tuple[Queued, ...] = ()
        if self.lexicon is not None:
            try:
                self.lexicon.reload_if_changed()
                result = self.lexicon.apply(final)
                final, applied, queued = result.text, result.applied, result.queued
            except Exception as e:
                logger.warning("Dictionary matching failed (%s); continuing without it", e)

        return Change(raw=text, final=final, applied=applied, queued=queued)

    def save_entries(self, entries) -> None:
        """Write edited entries through to the dictionary file (used by the editor window)."""
        if self.lexicon is None:
            return
        self.lexicon.save_entries(entries)

    def record(self, change: Change) -> None:
        """Persist hit counters and queued candidates for a processed change."""
        if self.lexicon is None:
            return
        self.lexicon.record(Result(text=change.final, applied=change.applied, queued=change.queued))


LEXICON_TEMPLATE = """# Parakeet Cage personal dictionary
#
# Teach the app the words this engine mishears: names, product names, jargon.
# `word` is what gets typed; `aliases` are spellings the model produces instead.
# Matching is case-insensitive, restricted to whole words, and never fires on
# words the model already knows well (that is what keeps "our" from becoming
# "OAuth").
#
# Example - uncomment and edit:
#
# [[word]]
# word = "kestrel"
# aliases = ["castrell", "kestral"]
# enabled = true
# hits = 0
#
# `parakeet-cage --pending` lists words the app nearly corrected but left alone;
# copy the ones you want into this file.
schema_version = 1
"""


def _write_lexicon_template(path: Path) -> None:
    """Create an empty, documented dictionary on first use so the format is discoverable."""
    try:
        if path.exists():
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(LEXICON_TEMPLATE, encoding="utf-8")
    except OSError as e:
        logger.debug("Could not create the lexicon template at %s: %s", path, e)


def build_pipeline(
    text_config: TextConfig,
    tokenizer_path: Optional[Path] = None,
    lexicon_path: Optional[Path] = None,
    queue_path: Optional[Path] = None,
) -> TextPipeline:
    """Build the pipeline described by a [text] config section.

    Without a usable model tokenizer the dictionary still applies exact and alias
    matches, but refuses to guess (see Lexicon): the tokenizer piece count is what
    distinguishes a misheard rare word from a word the model knows well.
    """
    lexicon: Optional[Lexicon] = None
    if text_config.lexicon:
        resolved_lexicon = Path(lexicon_path or text_config.lexicon_path or default_lexicon_path())
        resolved_queue = Path(queue_path) if queue_path is not None else default_queue_path()
        _write_lexicon_template(resolved_lexicon)
        piece_cost = piece_counter_for(Path(tokenizer_path)) if tokenizer_path else None
        lexicon = Lexicon.load(
            resolved_lexicon,
            piece_cost=piece_cost,
            queue_path=resolved_queue,
            max_distance=text_config.lexicon_max_distance,
        )

    return TextPipeline(
        punctuation=text_config.punctuation,
        punctuation_extra=text_config.punctuation_extra,
        lexicon=lexicon,
    )
