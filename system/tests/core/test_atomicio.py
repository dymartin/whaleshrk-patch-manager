"""Crash-safe repo writes.

The properties that matter: the replacement is all-or-nothing, a failed write
leaves the previous content intact, no temp file survives either outcome, and
text writes stay byte-identical to `Path.write_text` -- `.rig/catalog/` is
committed, so a change in newline handling would rewrite every generated file.
"""

from __future__ import annotations

import pytest

from rig.atomicio import write_bytes_atomic, write_text_atomic


def test_write_bytes_atomic_creates_missing_parents(tmp_path):
    target = tmp_path / "a" / "b" / "state.json"
    write_bytes_atomic(target, b"content")
    assert target.read_bytes() == b"content"


def test_write_text_atomic_replaces_existing_content(tmp_path):
    target = tmp_path / "state.json"
    write_text_atomic(target, "first\n")
    write_text_atomic(target, "second\n")
    assert target.read_text(encoding="utf-8") == "second\n"


def test_write_text_atomic_matches_write_text_byte_for_byte(tmp_path):
    """Newline translation included -- committed generated files depend on it."""
    expected = tmp_path / "expected.json"
    expected.write_text('{\n  "a": 1\n}\n', encoding="utf-8")

    actual = tmp_path / "actual.json"
    write_text_atomic(actual, '{\n  "a": 1\n}\n')

    assert actual.read_bytes() == expected.read_bytes()


def test_no_temp_file_is_left_behind(tmp_path):
    write_text_atomic(tmp_path / "state.json", "content\n")
    assert [p.name for p in tmp_path.iterdir()] == ["state.json"]


def test_a_failed_write_leaves_the_old_content_and_no_temp_file(tmp_path):
    target = tmp_path / "state.json"
    write_text_atomic(target, "original\n")

    with pytest.raises(TypeError):
        # Fails inside the write, after the temp file already exists -- the
        # path that must not leave the target or the directory disturbed.
        write_text_atomic(target, object())  # type: ignore[arg-type]

    assert target.read_text(encoding="utf-8") == "original\n"
    assert [p.name for p in tmp_path.iterdir()] == ["state.json"]
