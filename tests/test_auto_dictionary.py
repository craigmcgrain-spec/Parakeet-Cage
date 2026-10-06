"""Tests for parakeet_cage.auto_dictionary.

The auto dictionary is what the app proposes: candidates it observed but refused to apply,
and the ones you accepted. It is deliberately a separate store from the dictionary you
maintain by hand, so machine-proposed words never mix into your own list.
"""

import os
from pathlib import Path

from parakeet_cage.auto_dictionary import AutoDictionary
from parakeet_cage.lexicon import Entry, Queued


def build(tmp_path, **kwargs) -> AutoDictionary:
    return AutoDictionary.load(tmp_path / "auto.toml", **kwargs)


def test_starts_empty_and_writes_a_documented_file(tmp_path):
    auto = build(tmp_path)

    auto.add_candidate(Queued(token="castle", suggestion="kestrel", method="phonetic", distance=1))
    auto.accept_candidate(0)
    auto.save()

    text = (tmp_path / "auto.toml").read_text(encoding="utf-8")
    assert "managed by Parakeet Cage" in text
    assert 'word = "kestrel"' in text and 'aliases = ["castle"]' in text
    assert "schema_version = 1" in text


def test_candidates_and_entries_round_trip(tmp_path):
    auto = build(tmp_path)
    auto.add_candidate(Queued(token="castral", suggestion="kestrel", method="phonetic", distance=0, count=3))
    auto.add_entry("Möbius", ["Mobilius"])
    auto.save()

    reloaded = build(tmp_path)
    assert [(c.token, c.suggestion, c.count) for c in reloaded.candidates()] == [("castral", "kestrel", 3)]
    assert [(e.word, e.aliases) for e in reloaded.entries()] == [("Möbius", ("Mobilius",))]


def test_accepting_a_candidate_keeps_it_in_the_auto_dictionary(tmp_path):
    auto = build(tmp_path)
    auto.add_entry("kestrel")
    auto.add_candidate(Queued(token="castle", suggestion="kestrel", method="phonetic", distance=1))

    auto.accept_candidate(0)

    assert auto.candidates() == []
    assert [(entry.word, entry.aliases) for entry in auto.entries()] == [("kestrel", ("castle",))]


def test_accepting_an_unknown_word_creates_an_auto_entry(tmp_path):
    auto = build(tmp_path)
    auto.add_candidate(Queued(token="castral", suggestion="kestrel", method="phonetic", distance=0))

    auto.accept_candidate(0)

    assert [(e.word, e.aliases) for e in auto.entries()] == [("kestrel", ("castral",))]


def test_ignoring_a_candidate_only_drops_it(tmp_path):
    auto = build(tmp_path)
    auto.add_candidate(Queued(token="castle", suggestion="kestrel", method="phonetic", distance=1))

    auto.ignore_candidate(0)

    assert auto.candidates() == []
    assert auto.entries() == []


def test_promote_hands_an_entry_over_and_removes_it_here(tmp_path):
    auto = build(tmp_path)
    auto.add_entry("kestrel", ["castle"])

    promoted = auto.promote_entry(0)

    assert promoted == Entry(word="kestrel", aliases=("castle",))
    assert auto.entries() == []


def test_clear_drops_everything(tmp_path):
    auto = build(tmp_path)
    auto.add_entry("kestrel")
    auto.add_candidate(Queued(token="castle", suggestion="kestrel", method="phonetic", distance=1))

    auto.clear()
    auto.save()

    assert build(tmp_path).entries() == []
    assert build(tmp_path).candidates() == []


def test_reloads_when_the_file_changes(tmp_path):
    auto = build(tmp_path)
    auto.save()
    path = tmp_path / "auto.toml"

    stamp = path.stat().st_mtime_ns
    other = AutoDictionary.load(path)
    other.add_entry("kestrel")
    other.save()
    os.utime(path, ns=(stamp + 2_000_000_000, stamp + 2_000_000_000))

    assert auto.reload_if_changed() is True
    assert [entry.word for entry in auto.entries()] == ["kestrel"]


def test_migrates_candidates_from_the_older_queue_file(tmp_path):
    legacy = tmp_path / "pending.toml"
    legacy.write_text(
        "schema_version = 1\n\n[[candidate]]\nheard = \"castle\"\nsuggested = \"kestrel\"\n"
        'method = "phonetic"\ndistance = 1\ncount = 2\n',
        encoding="utf-8",
    )

    auto = AutoDictionary.load(tmp_path / "auto.toml", legacy_queue_path=legacy)

    assert [(c.token, c.count) for c in auto.candidates()] == [("castle", 2)]


def test_matching_view_applies_entries_and_counts_hits(tmp_path):
    auto = build(tmp_path, piece_cost=lambda _token: 4)
    auto.add_entry("kestrel", ["castrell"])

    result = auto.lexicon_view().apply("we use castrell daily")

    assert result.text == "we use kestrel daily"
    assert auto.entries()[0].hits == 1
