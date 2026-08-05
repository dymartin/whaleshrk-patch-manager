"""Media mirror planning: rig/push/media.py."""

from __future__ import annotations

import pytest

from rig.push.errors import PushError
from rig.push.media import build_media_plan
from rig.song.kits import KitsConfig


def test_samples_group_includes_loops_and_synths_nested(tmp_path):
    media_root = tmp_path / "media"
    (media_root / "samples" / "loops").mkdir(parents=True)
    (media_root / "samples" / "synths").mkdir(parents=True)
    (media_root / "samples" / "kick.wav").write_bytes(b"kick")
    (media_root / "samples" / "loops" / "loop1.wav").write_bytes(b"loop")
    (media_root / "samples" / "synths" / "pad.wav").write_bytes(b"pad")

    plan = build_media_plan(media_root, KitsConfig({}))
    samples = next(g for g in plan.groups if g.name == "samples")
    assert samples.card_path == "media/orhack/samples"
    assert samples.files == {
        "kick.wav": b"kick",
        "loops/loop1.wav": b"loop",
        "synths/pad.wav": b"pad",
    }


def test_only_aliased_kits_produce_groups(tmp_path):
    media_root = tmp_path / "media"
    (media_root / "kits" / "warehouse").mkdir(parents=True)
    (media_root / "kits" / "warehouse" / "a.wav").write_bytes(b"a")
    (media_root / "kits" / "unused").mkdir(parents=True)
    (media_root / "kits" / "unused" / "b.wav").write_bytes(b"b")

    plan = build_media_plan(media_root, KitsConfig({"warehouse": 3}))
    kit_groups = [g for g in plan.groups if g.name.startswith("kit:")]
    assert len(kit_groups) == 1
    assert kit_groups[0].card_path == "media/orhack/kits/kit-3"
    assert kit_groups[0].files == {"a.wav": b"a"}


def test_missing_media_directories_produce_empty_groups(tmp_path):
    plan = build_media_plan(tmp_path / "media", KitsConfig({"tape": 2}))
    assert all(g.files == {} for g in plan.groups)


def test_non_wav_files_are_ignored_and_reported(tmp_path):
    media_root = tmp_path / "media"
    (media_root / "samples").mkdir(parents=True)
    (media_root / "samples" / "notes.txt").write_text("hi")
    (media_root / "samples" / "kick.wav").write_bytes(b"kick")

    plan = build_media_plan(media_root, KitsConfig({}))
    assert any(p.endswith("notes.txt") for p in plan.ignored_non_wav)
    samples = next(g for g in plan.groups if g.name == "samples")
    assert samples.files == {"kick.wav": b"kick"}


def test_case_insensitive_collision_within_a_group_refuses(tmp_path):
    media_root = tmp_path / "media"
    (media_root / "samples").mkdir(parents=True)
    (media_root / "samples" / "Kick.wav").write_bytes(b"a")
    (media_root / "samples" / "kick.wav").write_bytes(b"b")
    if len(list((media_root / "samples").iterdir())) < 2:
        pytest.skip("host filesystem is case-insensitive; both names collapsed to one file")

    with pytest.raises(PushError) as exc:
        build_media_plan(media_root, KitsConfig({}))
    assert exc.value.code == "MEDIA_CASE_COLLISION"


def test_symlinked_wav_is_rejected(tmp_path):
    media_root = tmp_path / "media"
    (media_root / "samples").mkdir(parents=True)
    real = tmp_path / "real.wav"
    real.write_bytes(b"real")
    link = media_root / "samples" / "linked.wav"
    try:
        link.symlink_to(real)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks require elevated privilege or dev mode on this host")

    with pytest.raises(PushError) as exc:
        build_media_plan(media_root, KitsConfig({}))
    assert exc.value.code == "MEDIA_SYMLINK_REJECTED"
