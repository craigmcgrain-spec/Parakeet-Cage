"""Spoken punctuation for dictated text.

Parakeet transcribes spoken commands literally and punctuates them its own way, so
this is not a dictionary lookup. Measured real outputs (espeak speech, Parakeet
Redux):

    "How are you question mark See you tomorrow"      -> "How are you question mark? See you tomorrow."
    "I sent the file period Did you get it question mark" -> "I sent the file period did you get it, question mark."
    "Is it ready question mark"                       -> "Is it Reddy question Mark?"

So a command is replaced by its symbol and the pass then repairs what the model left
behind: punctuation attached to the command, separators stranded in front of a
terminal, duplicates, and the capitalisation of the clause that follows.

Commands are matched case-insensitively at word boundaries; the word "literal"
in front of a command suppresses it ("a literal period of time").

Spacing is driven per command class:

    sentence   removes trailing separators, one space follows, next word capitalised
    separator  no space before, one space after
    tight      joins both sides ("example dot com" -> "example.com")
    open/close brackets and quotes
    break      "new line" / "new paragraph", followed by capitalisation
    token      configured multi-character symbols (";-)"): space either side
"""

from __future__ import annotations

import re
from typing import Dict, List, Mapping, Optional, Tuple

SENTENCE = "sentence"
SEPARATOR = "separator"
TIGHT = "tight"
OPEN = "open"
CLOSE = "close"
BREAK = "break"
TOKEN = "token"

Command = Tuple[str, str]

DEFAULT_COMMANDS: Dict[str, Command] = {
    # sentence terminators
    "period": (".", SENTENCE),
    "full stop": (".", SENTENCE),
    "question mark": ("?", SENTENCE),
    "exclamation mark": ("!", SENTENCE),
    "exclamation point": ("!", SENTENCE),
    "ellipsis": ("…", SENTENCE),
    # separators
    "comma": (",", SEPARATOR),
    "semicolon": (";", SEPARATOR),
    "colon": (":", SEPARATOR),
    # breaks
    "new paragraph": ("\n\n", BREAK),
    "new line": ("\n", BREAK),
    # brackets and quotes
    "open quote": ('"', OPEN),
    "close quote": ('"', CLOSE),
    "open paren": ("(", OPEN),
    "close paren": (")", CLOSE),
    "open bracket": ("[", OPEN),
    "close bracket": ("]", CLOSE),
    "open brace": ("{", OPEN),
    "close brace": ("}", CLOSE),
    # symbols that join the words around them
    "dot": (".", TIGHT),
    "at sign": ("@", TIGHT),
    "underscore": ("_", TIGHT),
    "slash": ("/", TIGHT),
    "backslash": ("\\", TIGHT),
    "plus sign": ("+", TIGHT),
    "equals sign": ("=", TIGHT),
    "percent sign": ("%", TIGHT),
    "hash sign": ("#", TIGHT),
    "pound sign": ("#", TIGHT),
    "dollar sign": ("$", TIGHT),
    "ampersand": ("&", TIGHT),
    "pipe": ("|", TIGHT),
    "tilde": ("~", TIGHT),
    "caret": ("^", TIGHT),
    "asterisk": ("*", TIGHT),
    "hyphen": ("-", TIGHT),
    "dash": ("—", TIGHT),
}

_LITERAL = "literal"
_DROP_PUNCT = re.compile(r"^[!?.,;:…]+")
_TRAILING_SEPARATORS = re.compile(r"[ \t,;:]+$")


_PUNCTUATION_CHARS = frozenset(".,;:!?…—–-")


def _classify(symbol: str) -> str:
    """Spacing class for a symbol supplied by configuration."""
    if symbol.startswith("\n"):
        return BREAK
    if len(symbol) > 1 and not set(symbol) <= _PUNCTUATION_CHARS:
        return TOKEN        # a word-like symbol such as ";-)" keeps a space either side
    if symbol[:1] in (".", "?", "!"):
        return SENTENCE
    if symbol[:1] in (",", ";", ":"):
        return SEPARATOR
    if symbol[:1] in ("(", "[", "{"):
        return OPEN
    if symbol[:1] in (")", "]", "}"):
        return CLOSE
    return TIGHT


def _effective_commands(overrides: Optional[Mapping[str, Optional[str]]]) -> Dict[str, Command]:
    """Default table with user additions; a None value disables a command."""
    table: Dict[str, Command] = dict(DEFAULT_COMMANDS)
    for command, symbol in (overrides or {}).items():
        key = " ".join(str(command).split()).casefold()
        if not key:
            continue
        if symbol is None:
            table.pop(key, None)
        else:
            table[key] = (str(symbol), _classify(str(symbol)))
    return table


def _phrase_pattern(phrase: str) -> str:
    """Whole-word pattern for a command phrase, tolerant of spacing.

    re.escape() escapes the space in a multi-word phrase as a backslash-space, so the
    words are escaped individually and joined with an explicit whitespace matcher.
    """
    return r"\s+".join(re.escape(word) for word in phrase.split())


def _build_pattern(table: Mapping[str, Command]) -> "re.Pattern[str]":
    longest_first = sorted(table, key=len, reverse=True)
    alternatives = "|".join(_phrase_pattern(phrase) for phrase in longest_first)
    return re.compile(
        rf"(?<!\w)(?:(?P<literal>{_LITERAL})\s+)?(?P<command>{alternatives})(?!\w)",
        re.IGNORECASE,
    )


def _capitalize_first_alpha(segment: str) -> str:
    for index, char in enumerate(segment):
        if char.isalpha():
            return segment[:index] + char.upper() + segment[index + 1:]
    return segment


class _Builder:
    """Accumulates output while carrying the spacing state a command class implies."""

    def __init__(self) -> None:
        self._chars: List[str] = []
        self._space_before = False
        self._trim_leading = False
        self._drop_leading_punct = False
        self._capitalize = False

    def text(self, segment: str) -> None:
        if segment:
            # Repair model-inserted separators here, never across inserted symbols:
            # a user-defined symbol like ";-)" must survive intact.
            segment = _normalise_spacing(segment)
            if self._trim_leading:
                segment = segment.lstrip()
                self._trim_leading = False
            if self._drop_leading_punct:
                segment = _DROP_PUNCT.sub("", segment).lstrip()
                self._drop_leading_punct = False
            if self._capitalize:
                capitalized = _capitalize_first_alpha(segment)
                if capitalized != segment:
                    self._capitalize = False
                segment = capitalized
            if self._space_before and segment and not segment[0].isspace():
                self._chars.append(" ")
            self._space_before = False
        self._chars.extend(segment)

    def symbol(self, symbol: str, cls: str) -> None:
        if cls in (SENTENCE, SEPARATOR, TIGHT, CLOSE, BREAK):
            while self._chars and self._chars[-1] in (" ", "\t"):
                self._chars.pop()
        if cls == SENTENCE and self._chars:
            while self._chars and self._chars[-1] in (",", ";", ":"):
                self._chars.pop()
        if cls in (OPEN, TOKEN) and self._chars and self._chars[-1].isalnum():
            self._chars.append(" ")
        self._chars.extend(symbol)
        if cls in (SENTENCE, SEPARATOR, CLOSE, TOKEN):
            self._space_before = True
        if cls in (TIGHT, BREAK, OPEN):
            self._trim_leading = True
        if cls == SENTENCE:
            self._drop_leading_punct = True
        if cls in (SENTENCE, BREAK):
            self._capitalize = True

    def result(self) -> str:
        return "".join(self._chars)


def _normalise_spacing(text: str) -> str:
    """Model-inserted separators: no space in front, exactly one behind."""
    text = re.sub(r"[ \t]+([,;:])", r"\1", text)
    text = re.sub(r"([,;:])(?=\S)", r"\1 ", text)
    text = re.sub(r"[ \t]+\.(?=\s|$)", ".", text)
    return text


def apply_spoken_punctuation(
    text: str,
    commands: Optional[Mapping[str, Optional[str]]] = None,
) -> str:
    """Replace spoken punctuation commands with symbols and repair the result."""
    if not text:
        return text

    table = _effective_commands(commands)
    if not table:
        return _normalise_spacing(text)

    builder = _Builder()
    position = 0
    for match in _build_pattern(table).finditer(text):
        builder.text(text[position:match.start()])
        command = match.group("command")
        if match.group("literal"):
            builder.text(command)          # command spoken but not applied
        else:
            symbol, cls = table[" ".join(command.split()).casefold()]
            builder.symbol(symbol, cls)
        position = match.end()
    builder.text(text[position:])

    return builder.result()
