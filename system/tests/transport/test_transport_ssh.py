from __future__ import annotations

import subprocess

import pytest

from rig.transport import SshTransport, SshTransportError, TransportPathError


def test_ssh_transport_uses_card_relative_paths_and_binary_stdin(monkeypatch):
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, b"", b"")

    monkeypatch.setattr(subprocess, "run", run)
    transport = SshTransport("synth")
    transport.write("data/orhack/test file", b"\x00payload")
    transport.flush()

    assert calls[0][0][:6] == ["ssh", "-T", "-o", "BatchMode=yes", "synth", calls[0][0][5]]
    assert "'/sdcard/data/orhack/test file'" in calls[0][0][5]
    assert calls[0][1]["input"] == b"\x00payload"
    assert calls[1][0][-1] == "sync"


def test_ssh_transport_checks_manifest_in_one_remote_command(monkeypatch):
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, b"0RHACK/mother.pd: OK\n", b"")

    monkeypatch.setattr(subprocess, "run", run)
    assert SshTransport().check_sha1_manifest(b"digest  0RHACK/mother.pd\n") is None
    assert len(calls) == 1
    assert calls[0][1]["input"] == b"digest  0RHACK/mother.pd\n"


def test_ssh_transport_rejects_escape_and_reports_ssh_failure(monkeypatch):
    transport = SshTransport()
    with pytest.raises(TransportPathError):
        transport.exists("../escape")

    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 255, b"", b"offline"),
    )
    with pytest.raises(SshTransportError, match="offline"):
        transport.flush()
