from __future__ import annotations

import json
import time

import pytest

from rig.hardware import (
    Baseline,
    CpuStats,
    DeviceUnavailable,
    SongMeasurement,
    Subject,
    SshDevice,
    _cpu_stats,
    _note_channels,
    _stimulate,
    measure_song,
    read_baseline,
    regression_warnings,
    write_baseline,
)
from rig.song import Chain, ChainMidi, Song


class FakeLog:
    def __init__(self, lines=()):
        self.lines = list(lines)
        self.closed = False

    def mark(self):
        return 0

    def wait_for_load(self, after, timeout):
        return time.monotonic() + 0.1, "003-test"

    def lines_since(self, after):
        return self.lines

    def close(self):
        self.closed = True


class FakeDevice:
    def __init__(self, lines=()):
        self.log = FakeLog(lines)

    def probe(self):
        return "device", "Pd-0.53.1"

    def card_hash(self):
        return "a" * 64

    def open_log(self):
        return self.log

    def sample_cpu(self, duration, interval):
        return [10.0, 20.0, 30.0]


class FakeMidi:
    name = "fake"

    def __init__(self):
        self.messages = []

    def program_change(self, channel, program):
        self.messages.append(("program_change", channel, program))

    def note_on(self, channel, note, velocity):
        self.messages.append(("note_on", channel, note, velocity))

    def note_off(self, channel, note):
        self.messages.append(("note_off", channel, note))

    def close(self):
        pass


def _subject(port="fake"):
    return Subject("commit", "lock", "device", "Organelle OS 5.1", "Pd", "ORHACK 0.52b", port)


def test_cpu_stats_uses_nearest_rank_p95():
    stats = _cpu_stats(range(1, 21))
    assert stats.mean == 10.5
    assert stats.p95 == 19


def test_ssh_cpu_parser_converts_proc_ticks_to_percent(monkeypatch):
    output = "\n".join([
        "S 42 (pd) S 0 0 0 0 0 0 0 0 0 0 100 50 0 0",
        "U 10.00 0.00",
        "S 42 (pd) S 0 0 0 0 0 0 0 0 0 0 125 55 0 0",
        "U 10.50 0.00",
        "T 100",
    ])
    device = SshDevice()
    monkeypatch.setattr(device, "_run", lambda *args, **kwargs: output)
    assert device.sample_cpu(0.5, 0.5) == [60.0]


def test_note_channels_resolve_defaults_and_skip_omni():
    song = Song("x", 0, chains=[
        Chain("default"),
        Chain("omni", midi=ChainMidi(0)),
        Chain("override", midi=ChainMidi(7)),
        Chain("shared", midi=ChainMidi(7)),
    ])
    assert _note_channels(song) == [0, 6]


def test_stimulus_emits_only_notes_and_balances_every_note_off():
    midi = FakeMidi()
    song = Song("x", 0, chains=[Chain("a"), Chain("omni", midi=ChainMidi(0))])
    _stimulate(midi, song, duration=1, sleep=lambda _seconds: None)
    kinds = [message[0] for message in midi.messages]
    assert set(kinds) == {"note_on", "note_off"}
    assert kinds.count("note_on") == kinds.count("note_off")
    assert {message[1] for message in midi.messages} == {0}


@pytest.mark.parametrize(
    ("lines", "passed", "underruns"),
    [
        ([], True, 0),
        (["foo: couldn't create"], False, 0),
        (["(snd_pcm_recover) underrun occurred"], False, 1),
    ],
)
def test_measure_song_replays_clean_error_and_underrun(lines, passed, underruns):
    device = FakeDevice(lines)
    midi = FakeMidi()
    result = measure_song(
        "test", Song("Test", 3, chains=[Chain("lead")]), device, midi,
        settle=0, idle_window=0.01, active_window=0.01, interval=0.005,
        sleep=lambda _seconds: None,
    )
    assert result.passed is passed
    assert result.underruns == underruns
    assert midi.messages[:3] == [("program_change", 15, 3)] * 3
    assert all(message[0] in {"program_change", "note_on", "note_off"} for message in midi.messages)
    assert device.log.closed


def test_baseline_round_trip_and_subject_scoped_regression(tmp_path):
    measurement = SongMeasurement("test", 120, CpuStats(10, 12), CpuStats(20, 24), (), 0)
    subject = _subject()
    write_baseline(tmp_path, measurement, subject)
    baseline = read_baseline(tmp_path, "test")
    assert baseline == Baseline(subject, 120, 10, 12, 20, 24)

    regressed = SongMeasurement("test", 145, CpuStats(10, 12), CpuStats(25, 30), (), 0)
    warnings = regression_warnings(regressed, baseline, subject)
    assert warnings == (
        "load time is more than 20% above baseline",
        "active CPU mean is more than 20% above baseline",
        "active CPU p95 is more than 20% above baseline",
    )
    assert regression_warnings(regressed, baseline, _subject("another")) == ()


def test_baseline_json_is_stable_and_contains_subject(tmp_path):
    measurement = SongMeasurement("test", 1, CpuStats(2, 3), CpuStats(4, 5), (), 0)
    write_baseline(tmp_path, measurement, _subject())
    raw = json.loads((tmp_path / "hardware" / "test.json").read_text(encoding="utf-8"))
    assert raw["subject"]["stimulus"] == "v1"
    assert raw["active_cpu_p95"] == 5
