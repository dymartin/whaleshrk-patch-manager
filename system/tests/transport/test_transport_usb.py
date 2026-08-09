"""UsbMassStorage behaviour outside the shared conformance suite
(tests/test_transport_conformance.py): real bytes on disk, and what `flush`
actually does -- see docs/transport.md and Prompt/04-transport.md ruling 2.

No real USB hardware is available in this environment (Prompt/04-transport.md
global constraint #1); `flush`'s durability claim is verified against the
documented `os.fsync` contract (POSIX `fsync(2)`, Windows `FlushFileBuffers`
via `_commit`), not against a physical device.
"""

from __future__ import annotations

import os

import pytest

from rig.transport import TransportPathError, UsbMassStorage


def test_write_lands_real_bytes_on_disk(tmp_path):
    t = UsbMassStorage(tmp_path)
    t.write("data/orhack/rack.json", b'{"currentPreset": "Init"}')
    assert (tmp_path / "data" / "orhack" / "rack.json").read_bytes() == (
        b'{"currentPreset": "Init"}'
    )


def test_root_must_already_exist(tmp_path):
    with pytest.raises(TransportPathError):
        UsbMassStorage(tmp_path / "not-mounted")


def test_flush_fsyncs_every_file_written_since_last_flush(tmp_path, monkeypatch):
    synced: list[str] = []
    real_fsync = os.fsync

    def spy_fsync(fd):
        synced.append(fd)
        real_fsync(fd)

    monkeypatch.setattr(os, "fsync", spy_fsync)

    t = UsbMassStorage(tmp_path)
    t.write("a.json", b"1")
    t.write("dir/b.json", b"2")
    assert synced == []  # not yet flushed -- writes are buffered until flush()

    t.flush()
    assert len(synced) == 2


def test_flush_does_not_resync_already_flushed_files(tmp_path, monkeypatch):
    call_count = 0
    real_fsync = os.fsync

    def counting_fsync(fd):
        nonlocal call_count
        call_count += 1
        real_fsync(fd)

    monkeypatch.setattr(os, "fsync", counting_fsync)

    t = UsbMassStorage(tmp_path)
    t.write("a.json", b"1")
    t.flush()
    assert call_count == 1

    t.flush()  # nothing new written -- no redundant fsync
    assert call_count == 1


def test_flush_skips_a_file_deleted_before_flush(tmp_path):
    t = UsbMassStorage(tmp_path)
    t.write("a.json", b"1")
    t.delete("a.json")
    t.flush()  # must not raise chasing a path that no longer exists


def test_flush_follows_a_renamed_file(tmp_path, monkeypatch):
    synced: list[str] = []
    real_fsync = os.fsync

    def spy_fsync(fd):
        synced.append(fd)
        real_fsync(fd)

    monkeypatch.setattr(os, "fsync", spy_fsync)

    t = UsbMassStorage(tmp_path)
    t.write("a.json", b"1")
    t.rename("a.json", "b.json")
    t.flush()
    assert len(synced) == 1
    assert (tmp_path / "b.json").read_bytes() == b"1"
