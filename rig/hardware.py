"""Read-only hardware measurements against the band's Organelle S2.

The device boundary is system OpenSSH; the MIDI boundary is Windows WinMM.
Both are protocols so tests replay observations without a device or MIDI port.
"""

from __future__ import annotations

import ctypes
import hashlib
import json
import math
import queue
import statistics
import subprocess
import threading
import time
from ctypes import wintypes
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Protocol, Sequence

from rig.atomicio import write_text_atomic
from rig.catalog.slugs import slug
from rig.compile import format_program_prefix
from rig.push.state import hash_lock
from rig.song import Song


PROFILE_VERSION = "v1"
LOAD_ERROR_MARKERS = (
    "couldn't create",
    "unable to load",
    "loadmodule: unable to find",
    "unable to initialise module",
)
XRUN_MARKER = "(snd_pcm_recover) underrun occurred"
LOAD_MARKER = "preset loaded  : "
CARD_HASH_COMMAND = "cd /sdcard && find . -type f -print0 | sort -z | xargs -0 sha256sum | sha256sum"
LOG_READY = "__RIG_LOG_READY__"


class HardwareCheckError(RuntimeError):
    pass


class DeviceUnavailable(HardwareCheckError):
    pass


class MidiUnavailable(HardwareCheckError):
    pass


@dataclass(frozen=True)
class CpuStats:
    mean: float
    p95: float


@dataclass(frozen=True)
class SongMeasurement:
    song_id: str
    load_ms: float
    idle_cpu: CpuStats
    active_cpu: CpuStats
    errors: tuple[str, ...]
    underruns: int
    warnings: tuple[str, ...] = ()

    @property
    def passed(self) -> bool:
        return not self.errors and self.underruns == 0


@dataclass(frozen=True)
class Subject:
    commit: str
    module_lock: str
    device_id: str
    os: str
    pd: str
    orhack: str
    midi_port: str
    stimulus: str = PROFILE_VERSION

    @property
    def key(self) -> str:
        raw = json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode()).hexdigest()


@dataclass(frozen=True)
class Baseline:
    subject: Subject
    load_ms: float
    idle_cpu_mean: float
    idle_cpu_p95: float
    active_cpu_mean: float
    active_cpu_p95: float


class LogStream(Protocol):
    def mark(self) -> int: ...
    def wait_for_load(self, after: int, timeout: float) -> tuple[float, str]: ...
    def lines_since(self, after: int) -> list[str]: ...
    def close(self) -> None: ...


class Device(Protocol):
    def probe(self) -> tuple[str, str]: ...
    def card_hash(self) -> str: ...
    def open_log(self) -> LogStream: ...
    def sample_cpu(self, duration: float, interval: float) -> list[float]: ...


class MidiOutput(Protocol):
    @property
    def name(self) -> str: ...
    def program_change(self, channel: int, program: int) -> None: ...
    def note_on(self, channel: int, note: int, velocity: int) -> None: ...
    def note_off(self, channel: int, note: int) -> None: ...
    def close(self) -> None: ...


class SshLogStream:
    def __init__(self, process: subprocess.Popen[str], clock: Callable[[], float] = time.monotonic):
        self._process = process
        self._clock = clock
        self._lines: list[tuple[float, str]] = []
        self._condition = threading.Condition()
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._read, daemon=True)
        self._thread.start()

    def _read(self) -> None:
        assert self._process.stdout is not None
        for raw in self._process.stdout:
            line = raw.rstrip("\r\n")
            if line == LOG_READY:
                self._ready.set()
                continue
            with self._condition:
                self._lines.append((self._clock(), line))
                self._condition.notify_all()
        with self._condition:
            self._condition.notify_all()

    def wait_ready(self, timeout: float) -> None:
        if self._ready.wait(timeout):
            return
        message = "Organelle journal stream did not become ready"
        if self._process.poll() is not None and self._process.stderr is not None:
            message = self._process.stderr.read().strip() or message
        self.close()
        raise DeviceUnavailable(message)

    def mark(self) -> int:
        with self._condition:
            return len(self._lines)

    def wait_for_load(self, after: int, timeout: float) -> tuple[float, str]:
        deadline = self._clock() + timeout
        with self._condition:
            while True:
                for timestamp, line in self._lines[after:]:
                    if LOAD_MARKER in line:
                        return timestamp, line.split(LOAD_MARKER, 1)[1].strip()
                if self._process.poll() is not None:
                    raise DeviceUnavailable("Organelle journal stream closed")
                remaining = deadline - self._clock()
                if remaining <= 0:
                    raise HardwareCheckError("timed out waiting for preset load")
                self._condition.wait(remaining)

    def lines_since(self, after: int) -> list[str]:
        with self._condition:
            return [line for _timestamp, line in self._lines[after:]]

    def close(self) -> None:
        if self._process.poll() is None:
            self._process.terminate()
        try:
            self._process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            self._process.kill()


class SshDevice:
    def __init__(self, host: str = "organelle", timeout: float = 10):
        self.host = host
        self.timeout = timeout

    def _args(self, command: str) -> list[str]:
        return ["ssh", "-T", "-o", "BatchMode=yes", "-o", f"ConnectTimeout={int(self.timeout)}", self.host, command]

    def _run(self, command: str, *, timeout: float | None = None) -> str:
        try:
            result = subprocess.run(
                self._args(command), capture_output=True, text=True,
                timeout=timeout or self.timeout, check=False,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            raise DeviceUnavailable(f"could not run SSH for {self.host}: {exc}") from exc
        if result.returncode:
            message = result.stderr.strip() or f"remote command exited {result.returncode}"
            raise DeviceUnavailable(message)
        return result.stdout.strip()

    def probe(self) -> tuple[str, str]:
        lines = self._run("cat /etc/machine-id; pd -version 2>&1").splitlines()
        if len(lines) < 2 or not lines[0].strip():
            raise DeviceUnavailable("device identity or Pd version was unavailable")
        return lines[0].strip(), " ".join(line.strip() for line in lines[1:])

    def card_hash(self) -> str:
        digest = self._run(CARD_HASH_COMMAND, timeout=120).split()
        if not digest or len(digest[0]) != 64:
            raise HardwareCheckError("device returned an invalid card hash")
        return digest[0]

    def open_log(self) -> SshLogStream:
        try:
            process = subprocess.Popen(
                self._args(f"printf '{LOG_READY}\\n'; exec journalctl -f -n 0 -o cat -t Organelle"),
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1,
            )
        except FileNotFoundError as exc:
            raise DeviceUnavailable("OpenSSH client was not found") from exc
        stream = SshLogStream(process)
        stream.wait_ready(self.timeout)
        return stream

    def sample_cpu(self, duration: float, interval: float) -> list[float]:
        count = max(2, math.ceil(duration / interval) + 1)
        command = (
            "pid=$(pgrep -n pd) || exit 20; ticks=$(getconf CLK_TCK) || exit 21; "
            f"i=0; while [ $i -lt {count} ]; do "
            "[ -r /proc/$pid/stat ] || exit 22; printf 'S '; cat /proc/$pid/stat; "
            "printf 'U '; cat /proc/uptime; i=$((i+1)); "
            f"[ $i -lt {count} ] && sleep {interval}; done; printf 'T %s\\n' \"$ticks\""
        )
        output = self._run(command, timeout=duration + self.timeout + 5)
        stats: list[tuple[int, float]] = []
        ticks = 0
        pending: int | None = None
        for line in output.splitlines():
            if line.startswith("S "):
                stat = line[2:]
                end_comm = stat.rfind(")")
                fields = stat[end_comm + 2:].split()
                if end_comm < 0 or len(fields) < 13:
                    raise HardwareCheckError("invalid /proc Pd sample")
                pending = int(fields[11]) + int(fields[12])
            elif line.startswith("U ") and pending is not None:
                stats.append((pending, float(line[2:].split()[0])))
                pending = None
            elif line.startswith("T "):
                ticks = int(line[2:])
        if ticks <= 0 or len(stats) < 2:
            raise HardwareCheckError("not enough Pd CPU samples")
        samples = [
            100 * (b_ticks - a_ticks) / ticks / (b_time - a_time)
            for (a_ticks, a_time), (b_ticks, b_time) in zip(stats, stats[1:])
            if b_time > a_time
        ]
        if not samples:
            raise HardwareCheckError("Pd CPU sample clock did not advance")
        return samples


class _MidiOutCapsW(ctypes.Structure):
    _fields_ = [
        ("wMid", wintypes.WORD), ("wPid", wintypes.WORD),
        ("vDriverVersion", wintypes.UINT), ("szPname", wintypes.WCHAR * 32),
        ("wTechnology", wintypes.WORD), ("wVoices", wintypes.WORD),
        ("wNotes", wintypes.WORD), ("wChannelMask", wintypes.WORD),
        ("dwSupport", wintypes.DWORD),
    ]


class WinMidiOutput:
    def __init__(self, requested_name: str):
        try:
            winmm = ctypes.WinDLL("winmm")
        except (AttributeError, OSError) as exc:
            raise MidiUnavailable("live MIDI output requires Windows WinMM") from exc
        names: list[str] = []
        chosen: int | None = None
        for device_id in range(winmm.midiOutGetNumDevs()):
            caps = _MidiOutCapsW()
            if winmm.midiOutGetDevCapsW(device_id, ctypes.byref(caps), ctypes.sizeof(caps)) == 0:
                names.append(caps.szPname)
                if caps.szPname == requested_name:
                    chosen = device_id
        if chosen is None:
            available = ", ".join(names) or "none"
            raise MidiUnavailable(f"MIDI output {requested_name!r} not found; available: {available}")
        self._winmm = winmm
        self._handle = wintypes.HANDLE()
        if winmm.midiOutOpen(ctypes.byref(self._handle), chosen, 0, 0, 0) != 0:
            raise MidiUnavailable(f"could not open MIDI output {requested_name!r}")
        self._name = requested_name

    @property
    def name(self) -> str:
        return self._name

    def _send(self, status: int, data1: int, data2: int = 0) -> None:
        message = status | (data1 << 8) | (data2 << 16)
        if self._winmm.midiOutShortMsg(self._handle, message) != 0:
            raise MidiUnavailable(f"failed writing MIDI output {self._name!r}")

    def program_change(self, channel: int, program: int) -> None:
        self._send(0xC0 | channel, program)

    def note_on(self, channel: int, note: int, velocity: int) -> None:
        self._send(0x90 | channel, note, velocity)

    def note_off(self, channel: int, note: int) -> None:
        self._send(0x80 | channel, note, 0)

    def close(self) -> None:
        if self._handle:
            self._winmm.midiOutClose(self._handle)
            self._handle = wintypes.HANDLE()


def _cpu_stats(samples: Sequence[float]) -> CpuStats:
    ordered = sorted(samples)
    p95 = ordered[max(0, math.ceil(0.95 * len(ordered)) - 1)]
    return CpuStats(mean=statistics.fmean(ordered), p95=p95)


def _errors(lines: Sequence[str]) -> tuple[tuple[str, ...], int]:
    errors = tuple(line for line in lines if any(marker in line for marker in LOAD_ERROR_MARKERS))
    return errors, sum(XRUN_MARKER in line for line in lines)


def _note_channels(song: Song) -> list[int]:
    return sorted({
        channel - 1
        for position, chain in enumerate(song.chains, start=1)
        if (channel := chain.midi.channel if chain.midi.channel is not None else position) != 0
    })


def _stimulate(
    midi: MidiOutput, song: Song, duration: float, sleep: Callable[[float], None],
    stop: threading.Event | None = None,
) -> None:
    channels = _note_channels(song)
    notes = (48, 52, 55, 60, 64, 67, 72, 76)
    elapsed = 0.0
    active: list[tuple[int, int]] = []
    try:
        while elapsed < duration and not (stop and stop.is_set()):
            for note in notes:
                if elapsed >= duration or (stop and stop.is_set()):
                    break
                for channel in channels:
                    midi.note_on(channel, note, 100)
                    active.append((channel, note))
                on_time = min(0.5, duration - elapsed)
                sleep(on_time)
                elapsed += on_time
                for channel in channels:
                    midi.note_off(channel, note)
                    active.remove((channel, note))
                off_time = min(0.25, duration - elapsed)
                sleep(off_time)
                elapsed += off_time
    finally:
        for channel, note in active:
            midi.note_off(channel, note)


def _baseline_path(state_dir: Path, song_id: str) -> Path:
    return state_dir / "hardware" / f"{song_id}.json"


def read_baseline(state_dir: Path, song_id: str) -> Baseline | None:
    path = _baseline_path(state_dir, song_id)
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return Baseline(subject=Subject(**raw.pop("subject")), **raw)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise HardwareCheckError(f"invalid hardware baseline {path}: {exc}") from exc


def write_baseline(state_dir: Path, measurement: SongMeasurement, subject: Subject) -> None:
    baseline = Baseline(
        subject=subject, load_ms=measurement.load_ms,
        idle_cpu_mean=measurement.idle_cpu.mean, idle_cpu_p95=measurement.idle_cpu.p95,
        active_cpu_mean=measurement.active_cpu.mean, active_cpu_p95=measurement.active_cpu.p95,
    )
    write_text_atomic(
        _baseline_path(state_dir, measurement.song_id),
        json.dumps(asdict(baseline), indent=2, sort_keys=True) + "\n",
    )


def regression_warnings(measurement: SongMeasurement, baseline: Baseline | None, subject: Subject) -> tuple[str, ...]:
    if baseline is None or baseline.subject.key != subject.key:
        return ()
    checks = {
        "load time": (measurement.load_ms, baseline.load_ms),
        "idle CPU mean": (measurement.idle_cpu.mean, baseline.idle_cpu_mean),
        "idle CPU p95": (measurement.idle_cpu.p95, baseline.idle_cpu_p95),
        "active CPU mean": (measurement.active_cpu.mean, baseline.active_cpu_mean),
        "active CPU p95": (measurement.active_cpu.p95, baseline.active_cpu_p95),
    }
    return tuple(f"{name} is more than 20% above baseline" for name, (now, old) in checks.items() if old > 0 and now > old * 1.2)


def measure_song(
    song_id: str, song: Song, device: Device, midi: MidiOutput, *,
    load_timeout: float = 60, settle: float = 2, idle_window: float = 10,
    active_window: float = 20, interval: float = 0.5,
    sleep: Callable[[float], None] = time.sleep,
) -> SongMeasurement:
    log = device.open_log()
    start = log.mark()
    load_times: list[float] = []
    try:
        expected_preset = f"{format_program_prefix(song.program)}-{slug(song.name)}"
        for _ in range(3):
            after = log.mark()
            sent = time.monotonic()
            midi.program_change(15, song.program)
            loaded, name = log.wait_for_load(after, load_timeout)
            if name != expected_preset:
                raise HardwareCheckError(
                    f"program {song.program} loaded {name!r}, expected {expected_preset!r}"
                )
            load_times.append((loaded - sent) * 1000)
        sleep(settle)
        idle = _cpu_stats(device.sample_cpu(idle_window, interval))
        stop = threading.Event()
        stimulus_errors: queue.Queue[BaseException] = queue.Queue()

        def play() -> None:
            try:
                _stimulate(midi, song, active_window, sleep, stop)
            except BaseException as exc:
                stimulus_errors.put(exc)

        stimulus = threading.Thread(target=play)
        stimulus.start()
        try:
            active = _cpu_stats(device.sample_cpu(active_window, interval))
        finally:
            stop.set()
            stimulus.join()
        if not stimulus_errors.empty():
            raise HardwareCheckError(f"MIDI stimulus failed: {stimulus_errors.get()}")
        errors, underruns = _errors(log.lines_since(start))
        return SongMeasurement(song_id, statistics.median(load_times), idle, active, errors, underruns)
    finally:
        log.close()


def make_subject(device: Device, midi_port: str, lock: dict, repo: Path = Path(".")) -> Subject:
    device_id, pd_version = device.probe()
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True,
            text=True, check=True,
        ).stdout.strip()
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        raise HardwareCheckError("could not identify the current git commit") from exc
    return Subject(commit, hash_lock(lock), device_id, "Organelle OS 5.1", pd_version, "ORHACK 0.52b", midi_port)
