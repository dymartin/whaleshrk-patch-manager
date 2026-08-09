# Validation

Two things check the rig: `rig lint`, which runs in CI, and a hand-run
hardware check. No simulated-OS tier — see
[decisions.md](decisions.md) #61.

Neither claims DSP correctness or audio quality. Nothing does — see
[Deliberately not covered](#deliberately-not-covered).

## `rig lint`

```
rig lint [SONG...]
```

Prints findings, exits non-zero on any error. No report artifact, no run id,
no digest — the person running it is the person reading it, in the same
terminal (see [decisions.md](decisions.md) #69). CI fails a step on exit code
alone, which is the whole contract.

Two things it checks:

- **Songs.** The schema and lint rules in [schema.md](schema.md), per song,
  plus the cross-song rules (duplicate `program`, and so on). A song filter is
  diagnostic only; cross-song rules always run over every song.
- **Stored module archives.** Every module `system/data/modules.lock` pins is
  re-gated out of `system/modules/`: digest verified, archive re-run through the
  catalog gate from [catalog.md](catalog.md) — safe archive, ARM32 hard-float
  little-endian ELF, modelled sidecars — and the module the entry names
  located inside it.

That second check is the repo's reproducibility proof: it demonstrates
`system/data/catalog/` was generated from the archives actually committed, rather
than hand-edited, and that each archive still passes what it passed when it
was added. It is affordable on every run precisely because the catalog is a
shopping list rather than a mirror of Patchstorage.

No symbol or Pd-object resolution. It was specified once and dropped; see
[decisions.md](decisions.md) #68.

`rig lint` never claims a module loads or what it costs in CPU. Nothing
off-device can.

## `rig hardware-check`

Phase 10 of `../Prompt/PLAN.md`. Nothing below has run; do not cite it as
evidence.

```
rig hardware-check [SONG...] --midi-port "<exact Windows output name>" [--host organelle]
```

Run by hand from the Windows laptop, with the S2 on the same network and a MIDI
port connected. Not CI, not scheduled, no runner. Intended use is soundcheck or
after a push that changed a song. It reports four things — load time, CPU, Pd
load errors, ALSA underruns — and prints them; there is no report schema to fill.

**Read-only on the device.** `Rack::loadPreset` and `loadFilePreset` write
nothing; `rack.json` is written only by an explicit `savesettings` and
`params.json` only by `savePreset`. The check therefore needs no backup,
restore or quarantine — and it must never send CC 102 or any save command, the
only inputs that would break that property.

### Channels

| Purpose | Channel |
|---|---|
| Load a song | MIDI Program Change on channel 16 |
| Note stimulus | MIDI notes on each chain's own channel |
| Ready signal, errors, xruns | keyed OpenSSH, following the Organelle journal |
| CPU sampling | keyed OpenSSH, reading `/proc/<pd-pid>/stat` and `/proc/uptime` |

Nothing is installed and no sudo is used during a check. The one-time keyed SSH
bootstrap is manual; see [platform/surfaces.md](platform/surfaces.md). The
system OpenSSH client owns aliases, keys and host-key verification. The MIDI
boundary uses Windows' built-in WinMM API, so there is no Python MIDI dependency.
The journal subprocess emits a remote readiness marker before following; no
Program Change is sent until that marker arrives.

Program Change is used rather than OSC load-by-name because it also proves what
the compiler bets on: that zero-padded prefixes and gap placeholders put each
song at the program number its YAML declares.

**Security constraint.** OS 5.1 still serves its stock web app unauthenticated
on `0.0.0.0:8080`, and `/terminal` is effectively a root shell. The check does
not use it, but enabling SSH does not remove it. Run only on a network you
control, and never expose the S2 to an untrusted one.

### The subject

Hardware numbers are comparable only within one subject:

```
commit + module-lock digest + S2 device id + OS 5.1 + Pd version
+ ORHACK 0.52b + MIDI port name + stimulus profile version
```

The stimulus profile is part of the subject because the numbers mean nothing
without it: lengthening the idle window or changing the note pattern changes
every measurement. Bumping the profile invalidates existing baselines by
design, rather than silently comparing against numbers taken a different way.

V1 supports Organelle S2 and OS 5.1 only.

The Pd member is **Pd 0.53.1**, Debian bookworm's `puredata`
(`0.53.1+ds-2+deb12u1`) at `/usr/bin/pd`. **Observed 2026-08-08**, confirming
what the OS build recipe implied: `pd -version` reports `Pd-0.53.1 ("")
compiled for Debian (0.53.1+ds-2+deb12u1) on 2024/09/26 at 07:17:50 UTC`.
Audio subject is 44100 Hz,
64-sample blocks, `-audiobuf 6` headless — see
[platform/runtime.md](platform/runtime.md).

### Per song

Three repetitions, median reported:

1. Send Program Change; timestamp it on the laptop clock.
2. Wait for `preset loaded  : <name>`; that timestamp is load complete. Error is
   network plus journald latency — milliseconds against loads measured in
   hundreds of milliseconds.
3. Sample Pd process CPU over the idle window.
4. Play the note pattern on each chain's channel; sample CPU again.
5. Count ALSA underruns and Pd load errors seen throughout.

### Stimulus profile v1

Versioned, and named alongside every set of measurements.

| Setting | Value |
|---|---|
| Settle before sampling | 2 s after load complete |
| Idle window | 10 s, CPU sampled every 500 ms |
| Note pattern | 8 notes, MIDI 48/52/55/60/64/67/72/76, velocity 100 |
| Note timing | 500 ms on, 250 ms off, looped for 20 s |
| Chains | every chain in the song, simultaneously, each on its own channel |
| Omni chains | skipped — an omni chain would receive every other chain's notes |
| CPU statistic | mean and nearest-rank p95 of the samples in each window |

Notes are sent on each chain's compiled note channel, never on channel 16.
Sustaining modules get the full window rather than being cut off, so the CPU
figure includes release tails.

### Verdicts

Hard fail:

- any Pd load-error line — `couldn't create`, `unable to load`,
  `loadmodule: unable to find`, `unable to initialise module`;
- any ALSA underrun during the run.

No absolute CPU or timing gate exists, and none is invented before real numbers
do. Device unreachable is reported as such, not as a failure.

## Deliberately not covered

Nothing here proves any of this. Rehearsal and the band's ears do:

- DSP correctness, audio quality, level, or whether a chain is silent;
- temperature, throttling, or long-run thermal behaviour;
- MIDI latency and jitter;
- that a module's externals and Pd objects resolve on the device — the ELF check
  proves the binary is the right shape, not that its dependencies exist;
- that a module loads at all, before it reaches the device. `rig lint` sees the
  archive, the hardware check sees the device, and there is nothing in between.

## Acceptance

- `rig lint` gates every pull request; broken-ELF, wrong-arch, unsafe-archive
  and unmodelled-sidecar archive fixtures each fail.
- A locked module with no committed archive, or one failing its pinned digest,
  fails `rig lint` and refuses at push.
- Hardware check on an unreachable device says so and records nothing.
- A hardware run leaves the card byte-identical.
- A load-error fixture and an xrun fixture each fail.
