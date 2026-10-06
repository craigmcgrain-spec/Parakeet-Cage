"""Tests for parakeet_cage.lexicon (personal dictionary).

Tiers and thresholds come from measuring Parakeet Redux on rare words (see
CHANGELOG 1.2.0): errors are near-misses phonetically even when edit distance is
large ("kestrel" heard as "Castrell"), while the model encodes ordinary words it
knows in one or two subword pieces ("our", "will", "socket") and those must never
be rewritten on a hunch.
"""

from pathlib import Path

import pytest

from parakeet_cage.lexicon import Entry, Lexicon, Result, piece_counter_for

MODEL_DIR = Path(__file__).resolve().parent.parent / "models" / "parakeet-redux"
TOKENIZER = MODEL_DIR / "tokenizer.json"


@pytest.fixture
def counted(tmp_path):
    """A lexicon whose entries are matched with the real model tokenizer."""
    def build(entries, **kwargs):
        return Lexicon(entries, piece_cost=piece_counter_for(TOKENIZER), **kwargs)
    return build


# --- exact and alias matching ------------------------------------------------


def test_alias_is_replaced_with_the_canonical_spelling(counted):
    lex = counted([Entry(word="gRPC", aliases=("rpc",))])
    result = lex.apply("we use rpc here")
    assert result.text == "we use gRPC here"
    assert [a.method for a in result.applied] == ["exact"]


def test_capitalisation_of_the_source_token_is_mirrored(counted):
    lex = counted([Entry(word="kestrel")])
    assert lex.apply("Kestrel is fast").text == "Kestrel is fast"
    assert lex.apply("KESTREL is fast").text == "KESTREL is fast"
    assert lex.apply("castrell is fast").text == "kestrel is fast"


def test_entry_with_internal_caps_is_used_verbatim(counted):
    lex = counted([Entry(word="PostgreSQL", aliases=("postgresql",))])
    assert lex.apply("we run postgresql").text == "we run PostgreSQL"


def test_disabled_entry_is_ignored(counted):
    lex = counted([Entry(word="kestrel", aliases=("castrell",), enabled=False)])
    assert lex.apply("castrell is fast").text == "castrell is fast"
    assert lex.apply("castrell is fast").applied == ()


def test_unknown_word_is_left_alone(counted):
    lex = counted([Entry(word="kestrel")])
    result = lex.apply("nothing to correct here")
    assert result.text == "nothing to correct here"
    assert result.applied == () and result.queued == ()


# --- fuzzy tiers and the rarity guard ---------------------------------------


def test_phonetically_close_rare_word_is_corrected(counted):
    lex = counted([Entry(word="kestrel")])
    result = lex.apply("we use Castrell for this")
    assert result.text == "we use kestrel for this"
    assert result.applied[0].method == "phonetic"


def test_edit_distance_match_is_corrected(counted):
    lex = counted([Entry(word="PostgreSQL")])
    result = lex.apply("PostGrescuL is the database")
    assert result.text == "PostgreSQL is the database"
    assert result.applied[0].method == "edit"


def test_skeleton_adjacent_common_word_is_queued_not_applied(counted):
    """'castle' is one skeleton edit from 'kestrel' and a word in its own right.

    Caught by the end-to-end run: applying a single-skeleton-edit match rewrote
    "we use castle for this". Only an exact skeleton match may be applied; anything
    looser is a candidate for review.
    """
    lex = counted([Entry(word="kestrel")])
    result = lex.apply("we use castle for this")
    assert result.text == "we use castle for this"
    assert result.applied == ()
    assert [(q.token, q.suggestion) for q in result.queued] == [("castle", "kestrel")]


def test_exact_skeleton_match_is_still_applied(counted):
    """The measured real mishearing remains correctable: Castrell -> kestrel."""
    lex = counted([Entry(word="kestrel")])
    result = lex.apply("we use Castrell for this")
    assert result.text == "we use kestrel for this"
    assert result.applied[0].method == "phonetic"


def test_common_word_is_never_rewritten_on_a_hunch(counted):
    """`our` costs one tokenizer piece: the model knows it, so it must be left alone."""
    lex = counted([Entry(word="OAuth")])
    result = lex.apply("our team ships it")
    assert result.text == "our team ships it"
    assert result.applied == ()
    assert [(q.token, q.suggestion) for q in result.queued] == [("our", "OAuth")]


def test_protected_token_still_rewrites_when_listed_as_an_alias(counted):
    """An explicit alias is the user saying so, and bypasses the rarity guard."""
    lex = counted([Entry(word="OAuth", aliases=("our",))])
    assert lex.apply("our team ships it").text == "OAuth team ships it"


def test_fuzzy_matching_needs_three_characters(counted):
    lex = counted([Entry(word="kestrel")])
    assert lex.apply("ok go").applied == ()


def test_match_does_not_fire_inside_a_longer_word(counted):
    lex = counted([Entry(word="Sean")])
    assert lex.apply("the Seance was long").text == "the Seance was long"


def test_fuzzy_matching_is_off_without_a_tokenizer():
    lex = Lexicon([Entry(word="kestrel")], piece_cost=None)
    result = lex.apply("we use Castrell for this")
    assert result.text == "we use Castrell for this"
    assert result.applied == ()


def test_multi_word_entry_matches_a_phrase(counted):
    lex = counted([Entry(word="Parakeet Cage")])
    assert lex.apply("install parakeet cage now").text == "install Parakeet Cage now"


# --- idempotence, counting, persistence --------------------------------------


def test_second_pass_changes_nothing(counted):
    lex = counted([Entry(word="kestrel")])
    once = lex.apply("we use Castrell here").text
    assert lex.apply(once).text == once


def test_hits_are_counted_per_entry(counted):
    lex = counted([Entry(word="kestrel", aliases=("castrell",))])
    lex.apply("castrell here")
    lex.apply("castrell again")
    assert lex.entries[0].hits == 2


def test_load_and_record_round_trip(tmp_path, counted):
    lexicon_path = tmp_path / "lexicon.toml"
    lexicon_path.write_text(
        'schema_version = 1\n\n[[word]]\nword = "kestrel"\naliases = ["castrell"]\nenabled = true\n',
        encoding="utf-8",
    )
    queue_path = tmp_path / "pending.toml"      # legacy queue must not be created any more
    lex = Lexicon.load(lexicon_path, piece_cost=piece_counter_for(TOKENIZER))

    result = lex.apply("castrell is fast")
    lex.record(result)

    reloaded = Lexicon.load(lexicon_path, piece_cost=piece_counter_for(TOKENIZER))
    assert reloaded.apply("castrell again").applied[0].after == "kestrel"
    assert "hits = 1" in lexicon_path.read_text(encoding="utf-8")
    assert not list(tmp_path.glob("*.tmp"))
    assert not queue_path.exists()


def test_record_keeps_hand_written_comments(tmp_path, counted):
    """The user hand-edits this file: updating counters must not reformat it."""
    lexicon_path = tmp_path / "lexicon.toml"
    lexicon_path.write_text(
        "# my own notes: kestrel is the ASR engine\n"
        "schema_version = 1\n"
        "\n"
        "[[word]]\n"
        'word = "kestrel"          # what I say\n'
        'aliases = ["castrell"]    # what it hears\n'
        "enabled = true\n"
        "hits = 0\n",
        encoding="utf-8",
    )
    lex = Lexicon.load(lexicon_path, piece_cost=piece_counter_for(TOKENIZER))

    lex.record(lex.apply("we use castrell daily"))

    text = lexicon_path.read_text(encoding="utf-8")
    assert "# my own notes" in text
    assert "# what I say" in text
    assert "hits = 1" in text


def test_record_touches_nothing_when_nothing_changed(tmp_path, counted):
    lexicon_path = tmp_path / "lexicon.toml"
    lexicon_path.write_text(
        "# notes\nschema_version = 1\n\n[[word]]\nword = \"kestrel\"\nhits = 0\n",
        encoding="utf-8",
    )
    before = lexicon_path.read_bytes()
    lex = Lexicon.load(lexicon_path, piece_cost=piece_counter_for(TOKENIZER))

    lex.record(lex.apply("nothing to correct here"))

    assert lexicon_path.read_bytes() == before


def test_save_entries_adds_a_word_without_touching_the_rest(tmp_path):
    """The dictionary window edits a file the user also maintains by hand."""
    lexicon_path = tmp_path / "lexicon.toml"
    lexicon_path.write_text(
        "# keep me\nschema_version = 1\n\n[[word]]\n"
        'word = "kestrel"          # notes survive\nhits = 3\n',
        encoding="utf-8",
    )
    lex = Lexicon.load(lexicon_path, piece_cost=None)

    lex.save_entries([*lex.entries, Entry(word="Möbius", aliases=("Mobilius",))])

    text = lexicon_path.read_text(encoding="utf-8")
    assert "# keep me" in text
    assert "# notes survive" in text
    assert 'word = "Möbius"' in text and 'aliases = ["Mobilius"]' in text
    assert "\n\n[[word]]\nword = \"Möbius\"" in text      # appended with a blank line, like the rest
    reloaded = Lexicon.load(lexicon_path, piece_cost=None)
    assert [entry.word for entry in reloaded.entries] == ["kestrel", "Möbius"]
    assert reloaded.entries[0].hits == 3


def test_save_entries_separates_several_new_words(tmp_path):
    lexicon_path = tmp_path / "lexicon.toml"
    lexicon_path.write_text("schema_version = 1\n", encoding="utf-8")
    lex = Lexicon.load(lexicon_path, piece_cost=None)

    lex.save_entries([Entry(word="kestrel"), Entry(word="Möbius")])

    text = lexicon_path.read_text(encoding="utf-8")
    assert "\n\n[[word]]\nword = \"kestrel\"" in text
    assert "\n\n[[word]]\nword = \"Möbius\"" in text


def test_save_entries_edits_aliases_and_enabled_in_place(tmp_path):
    lexicon_path = tmp_path / "lexicon.toml"
    lexicon_path.write_text(
        "schema_version = 1\n\n[[word]]\n"
        'word = "kestrel"\naliases = ["castrell"]\nenabled = true\nhits = 0\n',
        encoding="utf-8",
    )
    lex = Lexicon.load(lexicon_path, piece_cost=None)

    lex.save_entries([Entry(word="kestrel", aliases=("castrell", "kestral"), enabled=False, hits=7)])

    text = lexicon_path.read_text(encoding="utf-8")
    assert 'aliases = ["castrell", "kestral"]' in text
    assert "enabled = false" in text
    assert "hits = 7" in text


def test_save_entries_removes_a_deleted_word(tmp_path):
    lexicon_path = tmp_path / "lexicon.toml"
    lexicon_path.write_text(
        "# header\nschema_version = 1\n\n[[word]]\n"
        'word = "kestrel"\n\n[[word]]\nword = "OAuth"\n',
        encoding="utf-8",
    )
    lex = Lexicon.load(lexicon_path, piece_cost=None)

    lex.save_entries([Entry(word="OAuth")])

    text = lexicon_path.read_text(encoding="utf-8")
    assert "# header" in text
    assert "kestrel" not in text
    assert 'word = "OAuth"' in text
    assert [entry.word for entry in Lexicon.load(lexicon_path, piece_cost=None).entries] == ["OAuth"]


def test_save_entries_leaves_an_unchanged_file_alone(tmp_path):
    lexicon_path = tmp_path / "lexicon.toml"
    lexicon_path.write_text(
        "schema_version = 1\n\n[[word]]\nword = \"kestrel\"\nhits = 0\n",
        encoding="utf-8",
    )
    before = lexicon_path.read_bytes()
    lex = Lexicon.load(lexicon_path, piece_cost=None)

    lex.save_entries(list(lex.entries))

    assert lexicon_path.read_bytes() == before


def test_lexicon_never_writes_candidates(tmp_path, counted):
    """Candidates belong to the auto dictionary; your dictionary only holds your words."""
    lexicon_path = tmp_path / "user.toml"
    lexicon_path.write_text('schema_version = 1\n\n[[word]]\nword = "OAuth"\n', encoding="utf-8")
    lex = Lexicon.load(lexicon_path, piece_cost=piece_counter_for(TOKENIZER))

    result = lex.apply("our team")
    lex.record(result)

    assert [(queued.token, queued.suggestion) for queued in result.queued] == [("our", "OAuth")]
    assert sorted(path.name for path in tmp_path.iterdir()) == ["user.toml"]


def test_empty_lexicon_is_a_no_op(counted):
    lex = counted([])
    result = lex.apply("anything at all")
    assert result.text == "anything at all" and result.applied == ()


# --- the rarity signal itself ------------------------------------------------


@pytest.mark.skipif(not TOKENIZER.exists(), reason="model weights not present")
def test_piece_counter_matches_the_measured_model_behaviour():
    cost = piece_counter_for(TOKENIZER)
    assert cost("our") == 1 and cost("will") == 1      # known words: cheap
    assert cost("socket") == 2 and cost("ready") == 2  # ordinary words: still cheap
    assert cost("castrell") == 4                       # misheard rare word: spelled out
    assert cost("parakita") == 3
