"""The content-hashing recipe push compares staged and swapped content with.

Both `rig.push.modules` and `rig.push.transact` rely on two properties here:
a digest depends on nothing but the (path, content) pairs, and it changes
whenever either side of any pair does. Tested directly so a regression fails
at this boundary rather than surfacing as a confusing mismatch mid-transaction.
"""

from __future__ import annotations

import hashlib

from rig.push.hashing import hash_bytes, hash_file_map, per_file_hashes


def test_hash_bytes_is_plain_sha256():
    assert hash_bytes(b"abc") == hashlib.sha256(b"abc").hexdigest()


def test_per_file_hashes_hashes_each_entry_independently():
    assert per_file_hashes({"a.pd": b"one", "b/c.txt": b"two"}) == {
        "a.pd": hash_bytes(b"one"),
        "b/c.txt": hash_bytes(b"two"),
    }


def test_hash_file_map_is_independent_of_insertion_order():
    forward = hash_file_map({"a": b"1", "b": b"2", "c": b"3"})
    reverse = hash_file_map({"c": b"3", "b": b"2", "a": b"1"})
    assert forward == reverse


def test_hash_file_map_changes_when_content_changes():
    before = hash_file_map({"a": b"1"})
    assert hash_file_map({"a": b"2"}) != before


def test_hash_file_map_changes_when_a_path_is_renamed():
    assert hash_file_map({"a": b"1"}) != hash_file_map({"b": b"1"})


def test_hash_file_map_separates_path_from_content():
    """A path/content boundary that hashed as one concatenated blob would
    collide here -- "ab" + "" reads the same as "a" + "b"."""
    assert hash_file_map({"ab": b""}) != hash_file_map({"a": b"b"})


def test_hash_file_map_of_no_files_is_the_empty_digest():
    assert hash_file_map({}) == hashlib.sha256().hexdigest()
