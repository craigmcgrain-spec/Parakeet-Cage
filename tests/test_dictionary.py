"""Tests for the dictionary window's non-GUI core: two stores, two files.

The GTK layer is thin and smoke-tested by hand (the repository has no GUI tests, see
tests/test_ui.py); everything that decides what happens to the files lives in
DictionaryModel and is tested here.
"""

from parakeet_cage.auto_dictionary import AutoDictionary
from parakeet_cage.config import TextConfig
from parakeet_cage.dictionary_ui import DictionaryModel
from parakeet_cage.lexicon import Entry, Lexicon, Queued
from parakeet_cage.postprocess import build_pipeline


def make_pipeline(tmp_path):
    return build_pipeline(
        TextConfig(lexicon_path=str(tmp_path / "user.toml")),
        tokenizer_path=None,
        auto_path=tmp_path / "auto.toml",
    )


def seed_candidates(tmp_path, *candidates: Queued) -> None:
    auto = AutoDictionary.load(tmp_path / "auto.toml")
    for candidate in candidates:
        auto.add_candidate(candidate)
    auto.save()


def test_the_two_stores_are_separate_files(tmp_path):
    pipeline = make_pipeline(tmp_path)
    model = DictionaryModel(pipeline)

    model.add_entry("kestrel", ["castrell"])
    model.save()

    assert "kestrel" in (tmp_path / "user.toml").read_text(encoding="utf-8")
    assert "kestrel" not in (tmp_path / "auto.toml").read_text(encoding="utf-8")


def test_accepting_a_candidate_lands_in_auto_not_your_dictionary(tmp_path):
    pipeline = make_pipeline(tmp_path)
    seed_candidates(tmp_path, Queued(token="castle", suggestion="kestrel", method="phonetic", distance=1))
    model = DictionaryModel(pipeline)

    model.accept_candidate(0)
    model.save()

    user = (tmp_path / "user.toml").read_text(encoding="utf-8")
    auto = (tmp_path / "auto.toml").read_text(encoding="utf-8")
    assert Lexicon.load(tmp_path / "user.toml").entries == []      # your dictionary stays yours
    assert 'word = "kestrel"' in auto and 'aliases = ["castle"]' in auto
    assert model.candidates() == []
    assert pipeline.process("we use castle daily").final == "we use kestrel daily"


def test_promote_moves_an_auto_word_into_your_dictionary(tmp_path):
    pipeline = make_pipeline(tmp_path)
    auto = AutoDictionary.load(tmp_path / "auto.toml")
    auto.add_entry("kestrel", ["castle"])
    auto.save()
    model = DictionaryModel(pipeline)

    model.promote_entry(0)
    model.save()

    assert "kestrel" in (tmp_path / "user.toml").read_text(encoding="utf-8")
    assert "kestrel" not in (tmp_path / "auto.toml").read_text(encoding="utf-8")
    assert pipeline.process("we use castle daily").final == "we use kestrel daily"


def test_ignore_drops_a_candidate_without_accepting_it(tmp_path):
    pipeline = make_pipeline(tmp_path)
    seed_candidates(tmp_path, Queued(token="castle", suggestion="kestrel", method="phonetic", distance=1))
    model = DictionaryModel(pipeline)

    model.ignore_candidate(0)
    model.save()

    assert model.candidates() == []
    assert pipeline.process("we use castle daily").final == "we use castle daily"


def test_clear_auto_empties_the_auto_store_only(tmp_path):
    pipeline = make_pipeline(tmp_path)
    model = DictionaryModel(pipeline)
    model.add_entry("gRPC")
    model.save()
    auto = AutoDictionary.load(tmp_path / "auto.toml")
    auto.add_entry("kestrel")
    auto.add_candidate(Queued(token="castle", suggestion="kestrel", method="phonetic", distance=1))
    auto.save()
    model.reload()

    model.clear_auto()
    model.save()

    assert model.auto_entries() == [] and model.candidates() == []
    assert [entry.word for entry in model.entries()] == ["gRPC"]


def test_editing_auto_rows_writes_only_the_auto_file(tmp_path):
    pipeline = make_pipeline(tmp_path)
    auto = AutoDictionary.load(tmp_path / "auto.toml")
    auto.add_entry("kestrel", ["castrell"])
    auto.save()
    model = DictionaryModel(pipeline)

    model.set_auto_entries([Entry(word="kestrel", aliases=("castrell", "castle"), enabled=False, hits=2)])
    model.save()

    auto_text = (tmp_path / "auto.toml").read_text(encoding="utf-8")
    assert 'aliases = ["castrell", "castle"]' in auto_text
    assert "enabled = false" in auto_text
    assert pipeline.process("castrell daily").final == "castrell daily"      # disabled


def test_model_reloads_hand_edits_when_the_window_opens(tmp_path):
    pipeline = make_pipeline(tmp_path)
    (tmp_path / "user.toml").write_text('schema_version = 1\n\n[[word]]\nword = "kestrel"\n', encoding="utf-8")
    auto = AutoDictionary.load(tmp_path / "auto.toml")
    auto.add_entry("Möbius")
    auto.save()

    model = DictionaryModel(pipeline)

    assert [entry.word for entry in model.entries()] == ["kestrel"]
    assert [entry.word for entry in model.auto_entries()] == ["Möbius"]
