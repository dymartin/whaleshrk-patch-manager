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

OS 5.1 serves a Flask app **unauthenticated** on `0.0.0.0:8080`, and its
`/terminal` endpoint is a real bash PTY. SSH ships disabled; the web terminal is
the access path. Treat the Organelle as a device that trusts its LAN completely.

Run this check **only on a network you control**, and never expose the S2 to an
untrusted one. The check adds no exposure, but it depends on that property.

## 1. Device session

Connect to the web app on port 8080:

| Endpoint | Use |
|---|---|
| `/log_stream` | websocket streaming `journalctl -f -o cat -t Organelle` |
| `/terminal` | websocket to a live bash PTY, for `/proc` sampling |

Everything Pd prints reaches journald: `start-mother.sh` runs
`mother 2>&1 | systemd-cat --identifier=Organelle`, and Pd inherits mother's
stdout. Journald storage is volatile and `/var/log` is tmpfs — the log survives
until reboot, not past it.

The web UI filters `(snd_pcm_recover) underrun occurred` out of its log view;
**the raw stream still carries them**, which makes xruns observable for free.

Device unreachable → verdict `unavailable`, not a failure. Write no baseline.

**On the first successful connection**, record `pd -version` and `locale -a`,
then update the two confirm-on-contact entries in `../docs/open-questions.md`
and the Pd line in `../docs/validation.md`.

Nothing is installed. No sudo. No agent. Off-device observation goes through the
journal because the mec OSC broadcaster hardcodes host `127.0.0.1` — commands can
come from the network, events cannot leave it.

## 2. Load timing

Send **Program Change on channel 16** and timestamp it on the laptop clock. Wait
for the log line

```
preset loaded  : <name>
```

and take that timestamp as load complete. Error is network plus journald
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
pattern on each chain's channel. Count ALSA underruns and Pd load-error lines
from the same stream.

### Stimulus profile v1

Committed alongside the baselines, versioned, and named in every report.

| Setting | Value |
|---|---|
| Settle before sampling | 2 s after load complete |
| Idle window | 10 s, CPU sampled every 500 ms |
| Note pattern | 8 notes, MIDI 48/52/55/60/64/67/72/76, velocity 100 |
| Note timing | 500 ms on, 250 ms off, looped for 20 s |
| Chains | every chain in the song, simultaneously, each on its own channel |
| Omni chains | **skipped** — an omni chain would receive every other chain's notes |
| CPU statistic | mean and p95 of the samples in each window |

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

The command sends **only** Program Change and notes. Never CC 102. Never any
save command.

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

**Assert it: hash the card before and after a run and require byte-identity.**

## Not covered by this or any tier

Full list in `../docs/validation.md` — "Deliberately not covered". No report may
be read as "this sounds right"; the band's ears are the oracle (#63).

## Verification

A **stubbed device session replays recorded log streams**:

| Recording | Expected verdict |
|---|---|
| Clean run | `pass`, baseline written if none exists |
| Run containing a load-error line | `fail` |
| Run containing an underrun | `fail` |
| Regressed run, >20% over baseline | `pass` with a warning |
| Unreachable device | `unavailable`, no baseline written |

Plus the card byte-identity assertion around a real run.

## Done when

All five replay cases produce the intended verdict, the card hash assertion
passes, and `../docs/open-questions.md`'s two confirm-on-contact entries are
replaced with observed values.
