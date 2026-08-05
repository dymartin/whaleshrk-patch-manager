"""`rig.compile.samples` -- `<kit-alias>/<file.wav>` -> samp_source/samp_select.

Position formula verified against docs/platform/samples.md: index k of N
files gets `samp_select = 100 * (k + 0.5) / (N - 0.05)`, the midpoint of its
valid decode interval.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from rig.compile.samples import SampleCompileError, resolve_sample, scan_wav_folder, scan_wav_names
from rig.song.kits import KitsConfig


def _make_folder(tmp_path: Path, names: list[str]) -> Path:
    folder = tmp_path / "kits" / "warehouse"
    folder.mkdir(parents=True)
    for name in names:
        (folder / name).write_bytes(b"")
    return folder


def test_scan_sorts_in_plain_ascending_order(tmp_path: Path):
    folder = _make_folder(tmp_path, ["snare.wav", "kick.wav", "hat.wav"])
    names, findings = scan_wav_folder(folder, "ctx")
    assert names == ["hat.wav", "kick.wav", "snare.wav"]
    assert findings == []


def test_non_wav_file_is_ignored_and_warned(tmp_path: Path):
    folder = _make_folder(tmp_path, ["kick.wav", "notes.txt"])
    names, findings = scan_wav_folder(folder, "ctx")
    assert names == ["kick.wav"]
    assert [f.code for f in findings] == ["IGNORED_NON_WAV_FILE"]


def test_uppercase_extension_is_rejected_as_non_lowercase(tmp_path: Path):
    folder = _make_folder(tmp_path, ["kick.WAV"])
    names, findings = scan_wav_folder(folder, "ctx")
    assert names == []
    assert [f.code for f in findings] == ["INVALID_SAMPLE_FILENAME"]


def test_non_portable_character_is_rejected(tmp_path: Path):
    folder = _make_folder(tmp_path, ["kick drum!.wav"])
    names, findings = scan_wav_folder(folder, "ctx")
    assert names == []
    assert [f.code for f in findings] == ["INVALID_SAMPLE_FILENAME"]


def test_case_insensitive_collision_is_a_distinct_error():
    # A real filesystem (vfat/exfat on the card, but also NTFS and default
    # APFS) cannot reliably hold two on-disk entries differing only by case,
    # so this exercises name validation directly -- see scan_wav_names's
    # docstring. The git-tracked repo, unlike the checkout, really can hold
    # both.
    names, findings = scan_wav_names(["kick.wav", "Kick.wav"], "ctx")
    codes = [f.code for f in findings]
    assert "SAMPLE_FILENAME_COLLISION" in codes
    assert names == ["kick.wav"]  # the valid, lowercase entry is still usable


def test_missing_folder_is_a_hard_error(tmp_path: Path):
    names, findings = scan_wav_folder(tmp_path / "kits" / "nope", "ctx")
    assert names == []
    assert [f.code for f in findings] == ["MISSING_SAMPLE_FOLDER"]


def test_resolve_sample_first_of_two_files(tmp_path: Path):
    _make_folder(tmp_path, ["kick_808.wav", "snare.wav"])
    kits = KitsConfig({"warehouse": 1})
    resolved = resolve_sample("warehouse/kick_808.wav", kits, tmp_path, context="ctx")
    assert resolved.samp_source == 1
    assert resolved.samp_select == pytest.approx(100 * 0.5 / 1.95)


def test_resolve_sample_second_of_two_files(tmp_path: Path):
    _make_folder(tmp_path, ["kick_808.wav", "snare.wav"])
    kits = KitsConfig({"warehouse": 1})
    resolved = resolve_sample("warehouse/snare.wav", kits, tmp_path, context="ctx")
    assert resolved.samp_source == 1
    assert resolved.samp_select == pytest.approx(100 * 1.5 / 1.95)


def test_resolve_sample_uses_the_kit_number_from_kits_yaml(tmp_path: Path):
    _make_folder(tmp_path, ["kick.wav"])
    kits = KitsConfig({"warehouse": 7})
    resolved = resolve_sample("warehouse/kick.wav", kits, tmp_path, context="ctx")
    assert resolved.samp_source == 7


def test_resolve_sample_unknown_alias(tmp_path: Path):
    kits = KitsConfig({"warehouse": 1})
    with pytest.raises(SampleCompileError) as exc_info:
        resolve_sample("ghost/kick.wav", kits, tmp_path, context="ctx")
    assert exc_info.value.findings[0].code == "UNKNOWN_KIT_ALIAS"


def test_resolve_sample_missing_file(tmp_path: Path):
    _make_folder(tmp_path, ["kick.wav"])
    kits = KitsConfig({"warehouse": 1})
    with pytest.raises(SampleCompileError) as exc_info:
        resolve_sample("warehouse/snare.wav", kits, tmp_path, context="ctx")
    assert exc_info.value.findings[0].code == "MISSING_SAMPLE_FILE"


def test_resolve_sample_refuses_when_folder_has_a_collision(tmp_path: Path, monkeypatch):
    from rig.compile import samples as samples_module

    _make_folder(tmp_path, ["kick.wav"])
    monkeypatch.setattr(
        samples_module,
        "scan_wav_folder",
        lambda folder, context: (["kick.wav"], [samples_module.Finding("SAMPLE_FILENAME_COLLISION", "boom")]),
    )
    kits = KitsConfig({"warehouse": 1})
    with pytest.raises(SampleCompileError) as exc_info:
        resolve_sample("warehouse/kick.wav", kits, tmp_path, context="ctx")
    assert exc_info.value.findings[0].code == "SAMPLE_FILENAME_COLLISION"
