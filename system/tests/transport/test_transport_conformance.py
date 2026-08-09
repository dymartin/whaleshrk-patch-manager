"""Shared conformance suite: every test here runs against both
InMemoryTransport and UsbMassStorage, unmodified -- see Prompt/04-transport.md
"Verification". A per-backend variant would let the two implementations
drift apart exactly where docs/transport.md warns a subtle difference eats
samples.

`transport` is parametrized over both backends; USB is backed by a fresh
`tmp_path` per test.
"""

from __future__ import annotations

import pytest

from rig.transport import InMemoryTransport, TransportPathError, UsbMassStorage


@pytest.fixture(params=["memory", "usb"])
def transport(request, tmp_path):
    if request.param == "memory":
        return InMemoryTransport()
    return UsbMassStorage(tmp_path)


def test_write_then_read_round_trips_identical_bytes(transport):
    transport.write("data/orhack/rack.json", b'{"currentPreset": "Init"}')
    assert transport.read("data/orhack/rack.json") == b'{"currentPreset": "Init"}'


def test_rename_moves_file(transport):
    transport.write("a.json", b"1")
    transport.rename("a.json", "b.json")
    assert not transport.exists("a.json")
    assert transport.read("b.json") == b"1"


def test_rename_over_an_existing_target_overwrites_it(transport):
    transport.write("a.json", b"1")
    transport.write("b.json", b"2")
    transport.rename("a.json", "b.json")
    assert not transport.exists("a.json")
    assert transport.read("b.json") == b"1"


def test_delete_removes_file(transport):
    transport.write("a.json", b"1")
    transport.delete("a.json")
    assert not transport.exists("a.json")


def test_list_reflects_write_rename_and_delete(transport):
    transport.write("dir/a.json", b"1")
    transport.write("dir/b.json", b"2")
    assert transport.list("dir") == ["a.json", "b.json"]

    transport.rename("dir/a.json", "dir/c.json")
    assert transport.list("dir") == ["b.json", "c.json"]

    transport.delete("dir/b.json")
    assert transport.list("dir") == ["c.json"]


def test_list_missing_directory_is_empty(transport):
    assert transport.list("nope") == []


def test_exists_true_for_directories_and_files(transport):
    transport.mkdir("data/orhack/presets/Init")
    assert transport.exists("data/orhack/presets/Init")
    assert not transport.exists("data/orhack/presets/Init/params.json")
    transport.write("data/orhack/presets/Init/params.json", b"{}")
    assert transport.exists("data/orhack/presets/Init/params.json")


def test_mkdir_nested_creates_parents(transport):
    transport.mkdir("a/b/c")
    assert transport.exists("a")
    assert transport.exists("a/b")
    assert transport.exists("a/b/c")


def test_mkdir_is_idempotent(transport):
    transport.mkdir("a/b")
    transport.mkdir("a/b")
    assert transport.exists("a/b")


def test_rename_directory_moves_all_contents(transport):
    transport.write("src/x.txt", b"x")
    transport.write("src/nested/y.txt", b"y")
    transport.rename("src", "dst")
    assert not transport.exists("src")
    assert transport.read("dst/x.txt") == b"x"
    assert transport.read("dst/nested/y.txt") == b"y"


def test_rename_directory_over_an_existing_directory_overwrites_it(transport):
    transport.write("src/x.txt", b"x")
    transport.write("dst/stale.txt", b"old")
    transport.rename("src", "dst")
    assert not transport.exists("src")
    assert transport.read("dst/x.txt") == b"x"
    assert not transport.exists("dst/stale.txt")


def test_delete_directory_removes_everything_under_it(transport):
    transport.write("dir/a.txt", b"1")
    transport.write("dir/nested/b.txt", b"2")
    transport.delete("dir")
    assert not transport.exists("dir")
    assert not transport.exists("dir/a.txt")
    assert not transport.exists("dir/nested/b.txt")


def test_read_missing_file_raises(transport):
    with pytest.raises(FileNotFoundError):
        transport.read("nope.json")


def test_delete_missing_path_raises(transport):
    with pytest.raises(FileNotFoundError):
        transport.delete("nope")


def test_flush_after_write_leaves_data_readable(transport):
    transport.write("a.json", b"1")
    transport.flush()
    assert transport.read("a.json") == b"1"


def test_flush_with_no_writes_does_not_raise(transport):
    transport.flush()


@pytest.mark.parametrize("path", ["/abs/path", "../escape", "a/../../escape"])
def test_rejects_paths_that_escape_the_root(transport, path):
    with pytest.raises(TransportPathError):
        transport.write(path, b"x")


def test_write_under_an_existing_file_raises_instead_of_corrupting_tree(transport):
    transport.write("a", b"file contents")
    with pytest.raises(TransportPathError):
        transport.write("a/b", b"nested")


def test_mkdir_under_an_existing_file_raises(transport):
    transport.write("a", b"file contents")
    with pytest.raises(TransportPathError):
        transport.mkdir("a/b")


def test_write_over_an_existing_directory_raises(transport):
    transport.write("dir/a.txt", b"1")
    with pytest.raises(TransportPathError):
        transport.write("dir", b"not a directory anymore")
