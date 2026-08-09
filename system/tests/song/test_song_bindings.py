from __future__ import annotations

from pathlib import Path

import pytest

from rig.song.bindings import read_bindings, write_bindings


def test_read_missing_binding_is_empty(tmp_path: Path):
    assert read_bindings(tmp_path, "vellichor") == {}


def test_write_then_read_round_trips(tmp_path: Path):
    write_bindings(tmp_path, "vellichor", {"pads": "B", "guitar": "A"})
    assert read_bindings(tmp_path, "vellichor") == {"pads": "B", "guitar": "A"}


def test_write_sorts_keys_two_space_indent_trailing_newline(tmp_path: Path):
    write_bindings(tmp_path, "vellichor", {"pads": "B", "guitar": "A"})
    text = (tmp_path / "vellichor.json").read_text(encoding="utf-8")
    assert text == '{\n  "guitar": "A",\n  "pads": "B"\n}\n'


def test_invalid_letter_rejected(tmp_path: Path):
    with pytest.raises(ValueError):
        write_bindings(tmp_path, "vellichor", {"pads": "E"})


def test_bindings_are_one_file_per_song(tmp_path: Path):
    write_bindings(tmp_path, "vellichor", {"pads": "A"})
    write_bindings(tmp_path, "low-tide", {"guitar": "B"})
    assert read_bindings(tmp_path, "vellichor") == {"pads": "A"}
    assert read_bindings(tmp_path, "low-tide") == {"guitar": "B"}
