"""Tests for parakeet_cage.postprocess (the two-stage text pipeline)."""

from pathlib import Path

from parakeet_cage.lexicon import Entry, Lexicon
from parakeet_cage.postprocess import TextPipeline, build_pipeline
from parakeet_cage.config import Config, TextConfig


def cheap_pieces(_token: str) -> int:
    """A word the model knows well (protected from fuzzy rewrites)."""
    return 1


def expensive_pieces(_token: str) -> int:
    """A rare word the model had to spell out (eligible for fuzzy rewrites)."""
    return 4


def test_spoken_punctuation_is_applied():
    pipeline = TextPipeline(punctuation=True)
    assert pipeline.process("are you ready question mark").final == "are you ready?"


def test_dictionary_runs_after_punctuation():
    lexicon = Lexicon([Entry(word="kestrel")], piece_cost=expensive_pieces)
    pipeline = TextPipeline(punctuation=True, lexicon=lexicon)

    change = pipeline.process("we use Castrell comma right")

    assert change.final == "we use kestrel, right"
    assert [applied.word for applied in change.applied] == ["kestrel"]


def test_change_carries_raw_text_for_undo():
    lexicon = Lexicon([Entry(word="kestrel", aliases=("castrell",))], piece_cost=expensive_pieces)
    pipeline = TextPipeline(punctuation=True, lexicon=lexicon)

    change = pipeline.process("castrell question mark")

    assert change.raw == "castrell question mark"
    assert change.final == "kestrel?"


def test_disabled_stages_leave_text_alone():
    pipeline = TextPipeline(punctuation=False)
    assert pipeline.process("hi question mark").final == "hi question mark"


def test_punctuation_still_runs_when_the_dictionary_fails():
    class Exploding(Lexicon):
        def apply(self, text):
            raise RuntimeError("boom")

    pipeline = TextPipeline(punctuation=True, lexicon=Exploding([]))
    assert pipeline.process("hello comma world").final == "hello, world"


def test_custom_commands_reach_the_pipeline():
    pipeline = TextPipeline(punctuation=True, punctuation_extra={"winky face": ";-)"})
    assert pipeline.process("done winky face").final == "done ;-)"


def test_blocked_candidate_is_reported_not_applied():
    lexicon = Lexicon([Entry(word="OAuth")], piece_cost=cheap_pieces)
    pipeline = TextPipeline(punctuation=True, lexicon=lexicon)

    change = pipeline.process("our roadmap")

    assert change.final == "our roadmap"
    assert [(queued.token, queued.suggestion) for queued in change.queued] == [("our", "OAuth")]


def test_record_hands_candidates_to_the_auto_dictionary(tmp_path):
    from parakeet_cage.auto_dictionary import AutoDictionary

    lexicon_path = tmp_path / "user.toml"
    lexicon_path.write_text('schema_version = 1\n\n[[word]]\nword = "OAuth"\n', encoding="utf-8")
    auto_path = tmp_path / "auto.toml"
    pipeline = TextPipeline(
        punctuation=True,
        lexicon=Lexicon([Entry(word="OAuth")], piece_cost=cheap_pieces, source_path=lexicon_path),
        auto=AutoDictionary.load(auto_path, piece_cost=cheap_pieces),
    )

    change = pipeline.process("our roadmap")
    pipeline.record(change)

    assert 'heard = "our"' in auto_path.read_text(encoding="utf-8")
    assert lexicon_path.read_text(encoding="utf-8") == 'schema_version = 1\n\n[[word]]\nword = "OAuth"\n'


def test_pipeline_picks_up_hand_edits_without_a_restart(tmp_path):
    """Editing the file (by hand or in the dictionary window) applies to the next dictation."""
    import os

    lexicon_path = tmp_path / "lexicon.toml"
    lexicon_path.write_text('schema_version = 1\n\n[[word]]\nword = "kestrel"\n', encoding="utf-8")
    pipeline = build_pipeline(TextConfig(lexicon_path=str(lexicon_path)), tokenizer_path=None)
    assert pipeline.process("we use castrell daily").final == "we use castrell daily"

    stamp = lexicon_path.stat().st_mtime_ns
    lexicon_path.write_text(
        'schema_version = 1\n\n[[word]]\nword = "kestrel"\naliases = ["castrell"]\n',
        encoding="utf-8",
    )
    # make the change unambiguously newer than the load, whatever the filesystem granularity
    os.utime(lexicon_path, ns=(stamp + 2_000_000_000, stamp + 2_000_000_000))

    assert pipeline.process("we use castrell daily").final == "we use kestrel daily"


def test_pipeline_saves_entries_through_to_the_file(tmp_path):
    lexicon_path = tmp_path / "lexicon.toml"
    pipeline = build_pipeline(TextConfig(lexicon_path=str(lexicon_path)), tokenizer_path=None)

    pipeline.save_entries([Entry(word="kestrel", aliases=("castrell",))])

    assert pipeline.process("castrell daily").final == "kestrel daily"
    assert 'aliases = ["castrell"]' in lexicon_path.read_text(encoding="utf-8")


MODEL_TOKENIZER = Path(__file__).resolve().parent.parent / "models" / "parakeet-redux" / "tokenizer.json"


def test_auto_entries_apply_alongside_your_own_dictionary(tmp_path):
    from parakeet_cage.auto_dictionary import AutoDictionary

    auto = AutoDictionary.load(tmp_path / "auto.toml")
    auto.add_entry("kestrel", ["castrell"])
    auto.save()

    pipeline = build_pipeline(
        TextConfig(lexicon_path=str(tmp_path / "user.toml")),
        tokenizer_path=None,
        auto_path=tmp_path / "auto.toml",
    )
    pipeline.save_entries([Entry(word="gRPC", aliases=("grpc",))])

    assert pipeline.process("we use castrell daily").final == "we use kestrel daily"
    assert pipeline.process("we use grpc daily").final == "we use gRPC daily"


def test_blocked_matches_land_in_the_auto_dictionary_not_your_file(tmp_path):
    pipeline = build_pipeline(
        TextConfig(lexicon_path=str(tmp_path / "user.toml")),
        tokenizer_path=MODEL_TOKENIZER,
        auto_path=tmp_path / "auto.toml",
    )
    pipeline.save_entries([Entry(word="kestrel")])

    change = pipeline.process("we use castle daily")
    pipeline.record(change)

    assert change.final == "we use castle daily"          # never rewritten on a hunch
    assert 'heard = "castle"' in (tmp_path / "auto.toml").read_text(encoding="utf-8")
    assert "castl" not in (tmp_path / "user.toml").read_text(encoding="utf-8")


def test_auto_dictionary_hot_reloads(tmp_path):
    from parakeet_cage.auto_dictionary import AutoDictionary

    auto_path = tmp_path / "auto.toml"
    pipeline = build_pipeline(
        TextConfig(lexicon_path=str(tmp_path / "user.toml")),
        tokenizer_path=None,
        auto_path=auto_path,
    )
    assert pipeline.process("castrell daily").final == "castrell daily"

    auto = AutoDictionary.load(auto_path)
    auto.add_entry("kestrel", ["castrell"])
    auto.save()

    assert pipeline.process("castrell daily").final == "kestrel daily"


def test_auto_dictionary_can_be_switched_off(tmp_path):
    pipeline = build_pipeline(
        TextConfig(lexicon_path=str(tmp_path / "user.toml"), auto_dictionary=False),
        tokenizer_path=None,
        auto_path=tmp_path / "auto.toml",
    )

    assert pipeline.auto is None
    assert not (tmp_path / "auto.toml").exists()


def test_build_pipeline_creates_a_documented_template(tmp_path):
    lexicon_path = tmp_path / "lexicon.toml"

    pipeline = build_pipeline(TextConfig(lexicon_path=str(lexicon_path)), tokenizer_path=None)

    text = lexicon_path.read_text(encoding="utf-8")
    assert "# [[word]]" in text            # the example stays commented out
    assert "schema_version = 1" in text
    assert pipeline.lexicon.entries == []


def test_build_pipeline_reads_its_lexicon_file(tmp_path):
    lexicon_path = tmp_path / "lexicon.toml"
    lexicon_path.write_text(
        'schema_version = 1\n\n[[word]]\nword = "kestrel"\naliases = ["castrell"]\n',
        encoding="utf-8",
    )
    pipeline = build_pipeline(TextConfig(lexicon_path=str(lexicon_path)), tokenizer_path=None)

    assert pipeline.process("castrell again").final == "kestrel again"


def test_build_pipeline_honours_config_switches(tmp_path):
    config = TextConfig(punctuation=False, lexicon=False, lexicon_path=str(tmp_path / "none.toml"))
    pipeline = build_pipeline(config, tokenizer_path=None)

    assert pipeline.process("castrell question mark").final == "castrell question mark"


def test_build_pipeline_survives_a_missing_model_tokenizer(tmp_path):
    lexicon_path = tmp_path / "lexicon.toml"
    lexicon_path.write_text('schema_version = 1\n\n[[word]]\nword = "kestrel"\n', encoding="utf-8")
    pipeline = build_pipeline(
        TextConfig(lexicon_path=str(lexicon_path)),
        tokenizer_path=tmp_path / "absent" / "tokenizer.json",
    )

    # exact/alias data still works, fuzzy guessing is disabled
    assert pipeline.process("kestrel here").final == "kestrel here"
    assert pipeline.process("castrell here").final == "castrell here"
