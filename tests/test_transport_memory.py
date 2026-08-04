"""InMemoryTransport: round-trip behaviour required by docs/transport.md.

Phase 4 promotes this class into a shared conformance suite alongside
UsbMassStorage; these tests only cover what Phase 0 must already guarantee.
"""

import pytest

from rig.transport import InMemoryTransport, TransportPathError


def test_write_then_read_round_trips_identical_bytes():
    t = InMemoryTransport()
    t.write("data/orhack/rack.json", b'{"currentPreset": "Init"}')
    assert t.read("data/orhack/rack.json") == b'{"currentPreset": "Init"}'


def test_rename_moves_file():
    t = InMemoryTransport()
    t.write("a.json", b"1")
    t.rename("a.json", "b.json")
    assert not t.exists("a.json")
    assert t.read("b.json") == b"1"


def test_delete_removes_file():
    t = InMemoryTransport()
    t.write("a.json", b"1")
    t.delete("a.json")
    assert not t.exists("a.json")


def test_list_reflects_write_rename_and_delete():
    t = InMemoryTransport()
    t.write("dir/a.json", b"1")
    t.write("dir/b.json", b"2")
    assert t.list("dir") == ["a.json", "b.json"]

    t.rename("dir/a.json", "dir/c.json")
    assert t.list("dir") == ["b.json", "c.json"]

    t.delete("dir/b.json")
    assert t.list("dir") == ["c.json"]


def test_list_missing_directory_is_empty():
    t = InMemoryTransport()
    assert t.list("nope") == []


def test_exists_true_for_directories_and_files():
    t = InMemoryTransport()
    t.mkdir("data/orhack/presets/Init")
    assert t.exists("data/orhack/presets/Init")
    assert not t.exists("data/orhack/presets/Init/params.json")
    t.write("data/orhack/presets/Init/params.json", b"{}")
    assert t.exists("data/orhack/presets/Init/params.json")


def test_mkdir_nested_creates_parents():
    t = InMemoryTransport()
    t.mkdir("a/b/c")
    assert t.exists("a")
    assert t.exists("a/b")
    assert t.exists("a/b/c")


def test_rename_directory_moves_all_contents():
    t = InMemoryTransport()
    t.write("src/x.txt", b"x")
    t.write("src/nested/y.txt", b"y")
    t.rename("src", "dst")
    assert not t.exists("src")
    assert t.read("dst/x.txt") == b"x"
    assert t.read("dst/nested/y.txt") == b"y"


def test_delete_directory_removes_everything_under_it():
    t = InMemoryTransport()
    t.write("dir/a.txt", b"1")
    t.write("dir/nested/b.txt", b"2")
    t.delete("dir")
    assert not t.exists("dir")
    assert not t.exists("dir/a.txt")
    assert not t.exists("dir/nested/b.txt")


def test_read_missing_file_raises():
    t = InMemoryTransport()
    with pytest.raises(FileNotFoundError):
        t.read("nope.json")


def test_delete_missing_path_raises():
    t = InMemoryTransport()
    with pytest.raises(FileNotFoundError):
        t.delete("nope")


def test_flush_is_a_noop_after_write():
    t = InMemoryTransport()
    t.write("a.json", b"1")
    t.flush()
    assert t.read("a.json") == b"1"


@pytest.mark.parametrize("path", ["/abs/path", "../escape", "a/../../escape"])
def test_rejects_paths_that_escape_the_root(path):
    t = InMemoryTransport()
    with pytest.raises(TransportPathError):
        t.write(path, b"x")


def test_write_under_an_existing_file_raises_instead_of_corrupting_tree():
    t = InMemoryTransport()
    t.write("a", b"file contents")
    with pytest.raises(TransportPathError):
        t.write("a/b", b"nested")


def test_mkdir_under_an_existing_file_raises():
    t = InMemoryTransport()
    t.write("a", b"file contents")
    with pytest.raises(TransportPathError):
        t.mkdir("a/b")


def test_write_over_an_existing_directory_raises():
    t = InMemoryTransport()
    t.write("dir/a.txt", b"1")
    with pytest.raises(TransportPathError):
        t.write("dir", b"not a directory anymore")
