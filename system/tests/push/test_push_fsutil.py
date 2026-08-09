"""Recursive listing over a Transport.

Module reconciliation and transaction verification both decide what to install
or verify from `list_files_recursive`, so its treatment of nesting, of an
empty directory, and of a missing root is tested here directly rather than
only through those callers.
"""

from __future__ import annotations

from rig.push.fsutil import list_files_recursive, read_file_map
from rig.transport.memory import InMemoryTransport


def _seeded(files: dict[str, bytes]) -> InMemoryTransport:
    transport = InMemoryTransport()
    for path, data in files.items():
        transport.write(path, data)
    return transport


def test_lists_every_file_under_root_relative_and_sorted():
    transport = _seeded(
        {
            "root/b.pd": b"b",
            "root/a.pd": b"a",
            "root/nested/deep/c.txt": b"c",
        }
    )
    assert list_files_recursive(transport, "root") == ["a.pd", "b.pd", "nested/deep/c.txt"]


def test_files_outside_root_are_not_listed():
    transport = _seeded({"root/in.pd": b"1", "other/out.pd": b"2"})
    assert list_files_recursive(transport, "root") == ["in.pd"]


def test_missing_root_yields_no_files():
    assert list_files_recursive(InMemoryTransport(), "nope") == []


def test_empty_directory_contributes_nothing():
    """`Transport.list` cannot distinguish an empty directory from a missing
    one (docs/transport.md), so an mkdir'd-but-empty directory must simply
    contribute no files rather than being reported as a file itself."""
    transport = _seeded({"root/real.pd": b"1"})
    transport.mkdir("root/empty")
    assert list_files_recursive(transport, "root") == ["real.pd"]


def test_read_file_map_reads_each_path_relative_to_root():
    transport = _seeded({"root/a.pd": b"aaa", "root/nested/b.pd": b"bbb"})
    assert read_file_map(transport, "root", ["a.pd", "nested/b.pd"]) == {
        "a.pd": b"aaa",
        "nested/b.pd": b"bbb",
    }
