# Phase 10 — Hardware check

## Goal

Its own command, run by hand from the laptop against the S2 on the same
network. No CI, no runner, no attestation.

**This is the project's first and only hardware feedback channel**, and it covers
exactly four things: load time, CPU, Pd load errors, ALSA underruns. Until this
lands, source reading is the only evidence. Never cite it as if it had already
run.

**No report artifact** (#73). Measurements are printed, alongside the stimulus
profile version they were taken under. Sections below that predate that
decision and speak of writing or verifying a report are superseded by
`../docs/validation.md`, which owns this phase.

## Read first

`../docs/validation.md` (owns this phase), `../docs/platform/surfaces.md`,
`../docs/platform/midi.md`, `../docs/platform/runtime.md`,
`../docs/open-questions.md`, `../docs/decisions.md` #62, #64, #65, #66, #67,
#73.

## Security constraint — read before connecting

The check uses the operator's `organelle` OpenSSH alias and key. It never stores
an address, username or credential in the repo, never enables sshd itself, and
runs every remote command with `BatchMode=yes` so a missing key fails instead of
falling back to an interactive prompt. The one-time device bootstrap is owned by
`../docs/platform/surfaces.md`.

OS 5.1 still serves its stock Flask app **unauthenticated** on `0.0.0.0:8080`,
and its `/terminal` endpoint is effectively a root shell. The hardware check no
longer depends on that app, but enabling SSH does not remove the exposure. Run
the check only on a network you control and never expose the S2 to an untrusted
one.

## 1. Device session

Use read-only SSH subprocesses through the `organelle` alias:

| Process | Use |
|---|---|
| `ssh -T -o BatchMode=yes organelle <ready marker; exec journalctl -f -n 0 -o cat -t Organelle>` | prove the follower is attached, then stream new Organelle journal lines |
| short-lived `ssh -T -o BatchMode=yes organelle <command>` calls | `/proc` sampling, subject metadata and card hashes |

Use the system `ssh` executable, not a Python SSH dependency. OpenSSH already
owns host aliases, keys, host-key verification and connection errors. Keep the
log stream separate from sampling commands so a slow sample cannot delay the
`preset loaded` timestamp. Timestamp each received log line immediately with
the laptop's monotonic clock. Do not send the first Program Change until the
remote readiness marker has been received; process creation alone does not prove
`journalctl` is attached.

Everything Pd prints reaches journald: `start-mother.sh` runs
`mother 2>&1 | systemd-cat --identifier=Organelle`, and Pd inherits mother's
stdout. Journald storage is volatile and `/var/log` is tmpfs — the log survives
until reboot, not past it.

The web UI filters `(snd_pcm_recover) underrun occurred` out of its view;
`journalctl` carries the unfiltered line, which makes xruns observable for free.

An unresolved alias, failed host-key check, rejected key, unreachable sshd, or
remote command that exits before readiness → verdict `unavailable`, not a
failure. Write no baseline. Never weaken host-key checking or authentication to
turn an unavailable device into a connection.

The first-contact `pd -version` and `locale -a` observations were recorded on
2026-08-08 in `../docs/validation.md`, `../docs/platform/midi.md`, and
`../docs/open-questions.md`; the command does not repeat or mutate that
documentation.

Nothing is installed. No sudo. No agent. The command runs only `journalctl`,
`sh`, `pgrep`, `getconf`, `cat`, `sleep`, `printf`, `find`, `sort`, `xargs`,
`sha256sum`, and `pd` on the
device. Off-device observation goes through the journal because the mec OSC
broadcaster hardcodes host `127.0.0.1` — commands can come from the network,
events cannot leave it.

## 2. Load timing

Send **Program Change on channel 16** and timestamp it on the laptop clock. Wait
for the log line

```
preset loaded  : <name>
```

and take that timestamp as load complete. Require the reported name to equal
the expected `<zero-padded program>-<song slug>`; otherwise the Program Change
ordering check failed. Error is network plus journald
latency — milliseconds against loads measured in hundreds of milliseconds.

That event is emitted by `PdCallback::loadPreset`, which `Rack::loadFilePreset`
calls **after** swapping every changed module and applying every parameter. It
fires for every load path and always after the work is done. It says nothing
about a module's internal warm-up.

**Three repetitions per song, median reported.**

Program Change rather than OSC load-by-name, deliberately: MIDI cannot load by
name, which is exactly why it is the right test input — it exercises the
zero-padded prefix and gap-placeholder scheme the compiler depends on. Loading
by name would hide an ordering bug.

Expect silence during the load: `KontrolRack_loadmodule` sends `pd dsp 0` before
clearing a slot and `pd dsp 1` after building it.

## 3. CPU and errors

Sample the Pd process over a fixed idle window, then again under a fixed note
pattern on each chain's channel. Resolve the process once with `pgrep -n pd`,
obtain clock ticks once with `getconf CLK_TCK`, and read `/proc/<pid>/stat` plus
`/proc/uptime` through one SSH sampling command per window. A vanished or
replaced Pd process makes the song check fail; silently changing the sampled PID
would join two incomparable windows. Count ALSA underruns and Pd load-error
lines from the journal stream.

### Stimulus profile v1

Versioned in the implementation and named alongside every printed measurement
and committed baseline.

| Setting | Value |
|---|---|
| Settle before sampling | 2 s after load complete |
| Idle window | 10 s, CPU sampled every 500 ms |
| Note pattern | 8 notes, MIDI 48/52/55/60/64/67/72/76, velocity 100 |
| Note timing | 500 ms on, 250 ms off, looped for 20 s |
| Chains | every chain in the song, simultaneously, each on its own channel |
| Omni chains | **skipped** — an omni chain would receive every other chain's notes |
| CPU statistic | mean and nearest-rank p95 of the samples in each window |

Notes go on each chain's compiled note channel, **never on channel 16**.
Sustaining modules get the full window rather than being cut off, so the CPU
figure includes release tails.

## 4. Verdict and baseline

**Hard fail:**

- any Pd load-error line — `couldn't create`, `unable to load`,
  `loadmodule: unable to find`, `unable to initialise module`;
- any ALSA underrun during the run.

**Warn:** load time or CPU more than 20% above this song's committed baseline.

**No absolute CPU or timing gate exists, and none is invented before real
numbers do.** A ceiling chosen before any measurement either blocks a working
song or never fires. The first run on a new subject records a baseline and warns
about nothing.

Baselines live in `.rig/state/hardware/<song>.json` — median load time and CPU,
keyed by subject. One file per song. **Baselines are committed; reports are
not.** Hardware numbers are comparable only within one subject; V1 supports
Organelle S2 and OS 5.1 only.

## 5. Prove it is read-only

The command sends **only** Program Change, Note On and explicit Note Off
messages. Never any Control Change — including CC 102 and CC 123 — and never any
save command. MIDI libraries generally number channels from zero: channel 16 on
the wire is `15` in such an API, while a song chain's 1-based channel is sent as
`channel - 1`.

This matters concretely: with stock values, a CC 102 of value ≥ 64 on MIDI
channel 16 overwrites the currently loaded preset on the device. There is no
master disable — `r-midi-pgmgate` gates program change, not these CCs, and no
numeric range includes an "off" value. CC 100 and 101 select previous/next
preset by the same route.

Read-only is verified in `mec`: `loadFilePreset` writes nothing, `rack.json` is
written only by an explicit `savesettings`, `params.json` only by `savePreset`.
That is what removes any need for backup, restore or quarantine (#64) — the
most dangerous machinery in the plan, a restore path that could destroy the card
it was protecting.

**Assert it:** before starting the journal stream and after every explicit Note
Off has been sent, calculate this digest through SSH and
require equality:

```sh
cd /sdcard && find . -type f -print0 | sort -z | xargs -0 sha256sum | sha256sum
```

The inner hashes cover contents and include paths; the sorted stream makes the
outer digest independent of directory enumeration order. Failure to calculate
either digest is a failed check, not permission to skip the assertion.

## Not covered by this or any tier

Full list in `../docs/validation.md` — "Deliberately not covered". No printed
verdict or baseline may be read as "this sounds right"; the band's ears are the
oracle (#63).

## Verification

A **stubbed device session replays recorded remote observations**:

| Recording | Expected verdict |
|---|---|
| Clean run | `pass`, baseline written if none exists |
| Run containing a load-error line | `fail` |
| Run containing an underrun | `fail` |
| Regressed run, >20% over baseline | `pass` with a warning |
| SSH alias/key missing or device unreachable | `unavailable`, no baseline written |

The fake SSH boundary supplies recorded journal lines, `/proc` samples and card
digests. The fake MIDI boundary records messages; assert that every message is
Program Change, Note On or Note Off, and that Program Change is on channel 16.
Plus the card byte-identity assertion around a real run.

## Done when

All five replay cases produce the intended verdict, the fake MIDI boundary
proves no Control Change was sent, and the card hash assertion passes on a real
run.
