"""Tests for the dictionary window's non-GUI core.

The GTK layer is thin and smoke-tested by hand (the repository has no GUI tests, see
tests/test_ui.py); everything that decides what happens to the files lives in
DictionaryModel and is tested here.
"""

from pathlib import Path

import pytest

from parakeet_cage.config import TextConfig
from parakeet_cage.dictionary_ui import DictionaryModel
from parakeet_cage.lexicon import Entry, Queued, read_queue, write_queue
from parakeet_cage.postprocess import build_pipeline


def make_pipeline(tmp_path) -> "object":
    return build_pipeline(
        TextConfig(lexicon_path=str(tmp_path / "lexicon.toml")),
        tokenizer_path=None,
        queue_path=tmp_path / "pending.toml",
    )


def queue_path_of(pipeline) -> Path:
    return pipeline.lexicon.queue_path


def test_confirm_candidate_adds_the_heard_spelling_as_an_alias(tmp_path):
    pipeline = make_pipeline(tmp_path)
    pipeline.save_entries([Entry(word="kestrel")])
    write_queue(queue_path_of(pipeline), [Queued(token="castle", suggestion="kestrel", method="phonetic", distance=1)])
    model = DictionaryModel(pipeline)

    model.confirm_candidate(0)
    model.save()

    assert pipeline.process("we use castle daily").final == "we use kestrel daily"
    assert model.candidates() == []
    assert read_queue(queue_path_of(pipeline)) == []


def test_confirm_candidate_creates_the_entry_when_the_word_is_new(tmp_path):
    pipeline = make_pipeline(tmp_path)
    write_queue(queue_path_of(pipeline), [Queued(token="castrell", suggestion="kestrel", method="phonetic", distance=0)])
    model = DictionaryModel(pipeline)

    model.confirm_candidate(0)
    model.save()

    assert pipeline.process("castrell daily").final == "kestrel daily"
    assert 'word = "kestrel"' in (tmp_path / "lexicon.toml").read_text(encoding="utf-8")


def test_ignore_candidate_drops_it_without_touching_the_dictionary(tmp_path):
    pipeline = make_pipeline(tmp_path)
    pipeline.save_entries([Entry(word="kestrel")])
    write_queue(queue_path_of(pipeline), [Queued(token="castle", suggestion="kestrel", method="phonetic", distance=1)])
    model = DictionaryModel(pipeline)

    model.ignore_candidate(0)
    model.save()

    assert model.candidates() == []
    assert read_queue(queue_path_of(pipeline)) == []
    assert pipeline.process("we use castle daily").final == "we use castle daily"


def test_add_edit_and_remove_entries(tmp_path):
    pipeline = make_pipeline(tmp_path)
    model = DictionaryModel(pipeline)

    model.add_entry("kestrel", ["castrell"])
    model.save()
    assert pipeline.process("castrell daily").final == "kestrel daily"

    model.update_entry(0, aliases=["castrell", "kestral"], enabled=False)
    model.save()
    assert model.entries()[0].enabled is False
    assert pipeline.process("castrell daily").final == "castrell daily"

    model.remove_entry(0)
    model.save()
    assert model.entries() == []


def test_model_reloads_hand_edits_when_the_window_opens(tmp_path):
    pipeline = make_pipeline(tmp_path)
    lexicon_path = tmp_path / "lexicon.toml"
    lexicon_path.write_text('schema_version = 1\n\n[[word]]\nword = "kestrel"\n', encoding="utf-8")

    model = DictionaryModel(pipeline)

    assert [entry.word for entry in model.entries()] == ["kestrel"]


def test_queue_round_trip_keeps_counts_and_order(tmp_path):
    path = tmp_path / "pending.toml"
    candidates = [
        Queued(token="castle", suggestion="kestrel", method="phonetic", distance=1, count=3),
        Queued(token="our", suggestion="OAuth", method="phonetic", distance=1, count=1),
    ]

    write_queue(path, candidates)

    assert read_queue(path) == candidates


def test_read_queue_handles_a_missing_file(tmp_path):
    assert read_queue(tmp_path / "absent.toml") == []
