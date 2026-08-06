# Validation

Two tiers: static CI, and a hand-run hardware check. No simulated-OS tier — see
[decisions.md](decisions.md) #61.

Validation belongs to an exact subject:

```
commit + report schema + module-lock digest + S2 device id
+ OS 5.1 + Pd version + ORHACK 0.52b + MIDI port name
+ stimulus profile version
```

The stimulus profile is part of the subject because the numbers mean nothing
without it: lengthening the idle window or changing the note pattern changes
every measurement. Bumping the profile invalidates existing baselines by design,
rather than silently comparing against numbers taken a different way.

Hardware numbers are comparable only within one subject. V1 supports Organelle
S2 and OS 5.1 only.

The Pd member is **Pd 0.53.1**, Debian bookworm's `puredata`
(`0.53.1+ds-2+deb12u1`) at `/usr/bin/pd`. Derived from the OS build recipe and
confirmed against upstream source, not yet observed: record `pd -version` at
first device contact and replace this line. Audio subject is 44100 Hz,
64-sample blocks, `-audiobuf 6` headless — see
[platform/runtime.md](platform/runtime.md).

## Confidence levels

- `static-only`: archive and source checks pass.
- `hardware-observed`: the named checks passed on the S2 named in the report.

Neither claims DSP correctness or audio quality. Nothing does — see
[Deliberately not covered](#deliberately-not-covered).

## CLI and report

```
rig validate --tier static|hardware [SONG...]
rig validate verify-report REPORT
```

Each run emits canonical, versioned JSON: verdict (`pass`, `fail`,
`unavailable`), tier, the subject above, run id, per-song checks, metrics,
failures, start/end times, a `confidence` label (below) and a `scope_note` --
a fixed disclaimer carried in the report data itself, not just CLI output, so
a saved or forwarded report cannot be misread as proof of anything the tier
did not check. Individual checks may be `unavailable`.

`rig validate --tier static` writes its report to `.rig/state/reports/`
(gitignored, not committed -- see [repo-layout.md](repo-layout.md)) and
prints the path. `verify-report` recomputes a sha256 digest embedded in the
file and rejects it if the content no longer matches -- not a signature (no
third party needs convincing, per #62's reasoning), just enough to catch a
hand edit.

Hardware runs also write a baseline per song to
`.rig/state/hardware/<song>.json` — median load time and CPU, keyed by subject.
One file per song, like every other piece of repo state. Baselines are
committed; reports are not.

## Tier 1: static CI

Required on every pull request and push. Public repo, so Actions minutes are
unmetered and this runs unconditionally.

Static validation **is** the catalog gate from [catalog.md](catalog.md), run
over every locked module and every song: safe archive, valid metadata, ARM32
hard-float little-endian ELF, `DT_NEEDED` warnings, unique runtime path,
modelled sidecars — plus the schema and lint rules in [schema.md](schema.md).

No symbol or Pd-object resolution. It was specified once and dropped; see
[decisions.md](decisions.md) #68.

A local song filter is diagnostic only. Static success never claims CPU cost or
that a module loads.

**Re-running the gate needs an archive, and the repo keeps none.**
`.rig/catalog/` and `.rig/modules.lock` are themselves built by gating the
frozen fixture (`rig.catalog.frozen`), so `rig validate --tier static`
re-gates the same way — every module `.rig/modules.lock` currently pins,
replayed against the frozen fixture, rather than a live Patchstorage
re-fetch (only `rig catalog update` does that). A locked module whose
candidate is not in the fixture — ingested by a later `rig catalog update`
run after the fixture was frozen — cannot be re-gated offline; its check
reports `unavailable`, never a silent pass. CI's own "regenerate from the
frozen fixture and fail on diff" is a separate check, over the whole
committed catalog rather than only what one repo's songs use.

## Tier 2: hardware check

Run by hand — `rig validate --tier hardware` — from the laptop, with the S2 on
the same network and a MIDI port connected. Not CI, not scheduled, no runner.
Intended use is soundcheck or after a push that changed a song.

**Read-only on the device.** `Rack::loadPreset` and `loadFilePreset` write
nothing; `rack.json` is written only by an explicit `savesettings` and
`params.json` only by `savePreset`. The check therefore needs no backup, restore
or quarantine — and it must never send CC 102 or any save command, the only
inputs that would break that property.

### Channels

| Purpose | Channel |
|---|---|
| Load a song | MIDI Program Change on channel 16 |
| Note stimulus | MIDI notes on each chain's own channel |
| Ready signal, errors, xruns | `/log_stream` websocket on port 8080 |
| CPU sampling | `/terminal` websocket, reading `/proc` |

All three device endpoints already exist in OS 5.1. Nothing is installed and no
sudo is used. See [platform/surfaces.md](platform/surfaces.md) for the endpoints
and the `preset loaded` event.

Program Change is used rather than OSC load-by-name because it also proves what
the compiler bets on: that zero-padded prefixes and gap placeholders put each
song at the program number its YAML declares.

**Security constraint.** OS 5.1 serves that web app unauthenticated on
`0.0.0.0:8080`, and `/terminal` is a real shell. Run the check only on a network
you control, and never expose the S2 to an untrusted one. The check adds no
exposure, but it depends on this one.

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

Committed alongside the baselines, versioned, and named in every report.

| Setting | Value |
|---|---|
| Settle before sampling | 2 s after load complete |
| Idle window | 10 s, CPU sampled every 500 ms |
| Note pattern | 8 notes, MIDI 48/52/55/60/64/67/72/76, velocity 100 |
| Note timing | 500 ms on, 250 ms off, looped for 20 s |
| Chains | every chain in the song, simultaneously, each on its own channel |
| Omni chains | skipped — an omni chain would receive every other chain's notes |
| CPU statistic | mean and p95 of the samples in each window |

Notes are sent on each chain's compiled note channel, never on channel 16.
Sustaining modules get the full window rather than being cut off, so the CPU
figure includes release tails.

### Verdicts

Hard fail:

- any Pd load-error line — `couldn't create`, `unable to load`,
  `loadmodule: unable to find`, `unable to initialise module`;
- any ALSA underrun during the run.

Warn: load time or CPU more than 20% above this song's committed baseline.

No absolute CPU or timing gate exists, and none is invented before real numbers
do. The first run on a new subject records a baseline and warns about nothing.

Device unreachable is `unavailable`, not a failure.

## Deliberately not covered

Nothing in either tier proves any of this. Rehearsal and the band's ears do:

- DSP correctness, audio quality, level, or whether a chain is silent;
- temperature, throttling, or long-run thermal behaviour;
- MIDI latency and jitter;
- that a module's externals and Pd objects resolve on the device — the ELF check
  proves the binary is the right shape, not that its dependencies exist;
- that a module loads at all, before it reaches the device. Tier 1 sees the
  archive, Tier 2 sees the device, and there is nothing in between.

## Acceptance

- Static job gates every pull request; broken-ELF, wrong-arch, unsafe-archive
  and unmodelled-sidecar fixtures each fail with the intended check id.
- Hardware check on an unreachable device reports `unavailable` and writes no
  baseline.
- A hardware run leaves the card byte-identical — asserted by hashing before and
  after.
- A load-error fixture and an xrun fixture each fail; a regressed baseline warns
  without failing.
- `verify-report` rejects a hand-edited report.

## Implementation order

Phases 9 and 10 of `../Prompt/PLAN.md`. The report schema lands before the tier that
emits it. Core patch-manager work proceeds in parallel.
