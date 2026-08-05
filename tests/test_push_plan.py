"""Gap placeholders, card-preset classification, chain-rename detection.

See rig/push/plan.py and docs/workflows/push.md steps 3-5.
"""

from __future__ import annotations

from rig.push.plan import (
    Classification,
    ChainRenameSuspect,
    classify_card_presets,
    detect_chain_rename,
    gap_programs,
    is_placeholder_directory,
)
from rig.song.model import Chain, Song


def test_gap_programs_fills_every_unused_value_below_the_highest():
    assert gap_programs([0, 3]) == [1, 2]


def test_gap_programs_empty_when_contiguous():
    assert gap_programs([0, 1, 2]) == []


def test_gap_programs_empty_when_no_songs():
    assert gap_programs([]) == []


def test_placeholder_directory_pattern_matches_bare_three_digits():
    assert is_placeholder_directory("002")
    assert not is_placeholder_directory("002-vellichor")
    assert not is_placeholder_directory("Init")
    assert not is_placeholder_directory("2")  # not zero-padded to 3


def test_classify_skips_init_and_placeholders():
    result = classify_card_presets(["Init", "001", "002-vellichor"], {"vellichor": "002-vellichor"}, {"vellichor"})
    assert result == Classification(managed={"vellichor": "002-vellichor"}, deletions=[], unrecorded=[])


def test_classify_managed_song_present_in_repo():
    result = classify_card_presets(["003-tide"], {"low-tide": "003-tide"}, {"low-tide"})
    assert result.managed == {"low-tide": "003-tide"}
    assert result.deletions == []
    assert result.unrecorded == []


def test_classify_recorded_song_deleted_from_repo_is_a_plain_deletion():
    result = classify_card_presets(["003-tide"], {"low-tide": "003-tide"}, set())
    assert result.deletions == ["003-tide"]
    assert result.managed == {}
    assert result.unrecorded == []


def test_classify_unrecorded_preset_is_flagged_for_refusal():
    result = classify_card_presets(["mycoolpatch"], {}, set())
    assert result.unrecorded == ["mycoolpatch"]
    assert result.deletions == []


def test_detect_chain_rename_none_when_bindings_match():
    song = Song(name="s", program=1, chains=[Chain(name="lead")])
    assert detect_chain_rename(song, {"lead": "A"}) is None


def test_detect_chain_rename_none_for_a_brand_new_song_with_no_bindings():
    song = Song(name="s", program=1, chains=[Chain(name="lead")])
    assert detect_chain_rename(song, {}) is None


def test_detect_chain_rename_none_when_a_chain_is_simply_removed():
    song = Song(name="s", program=1, chains=[Chain(name="lead")])
    assert detect_chain_rename(song, {"lead": "A", "pad": "B"}) is None


def test_detect_chain_rename_flags_simultaneous_orphan_and_unbound():
    song = Song(name="s", program=1, chains=[Chain(name="lead2")])
    suspect = detect_chain_rename(song, {"lead": "A"})
    assert suspect == ChainRenameSuspect(old_names=["lead"], new_names=["lead2"])


def test_detect_chain_rename_lists_every_candidate_when_ambiguous():
    song = Song(name="s", program=1, chains=[Chain(name="x"), Chain(name="y")])
    suspect = detect_chain_rename(song, {"a": "A", "b": "B"})
    assert suspect.old_names == ["a", "b"]
    assert suspect.new_names == ["x", "y"]
