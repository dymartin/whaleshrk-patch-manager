# Overview

## What this is

A CLI treating whaleshrk's live synth rig as version-controlled configuration: a
Critter & Guitari Organelle S2 running ORHACK, an ORAC community fork.

One YAML file describes each song's rig. Push compiles it to the SD card; pull
turns device changes into PRs.

Manual patch setup is repetitive and error-prone. Version control gives
reviewable history and reconstructs any past show's rig.

## Goals

- A song's rig state is fully described by its YAML file plus pinned module
  versions. Same repo, same push, same rig — on any day.
- Musicians read and write only friendly YAML. No device slot ids, no raw CC
  numbers, no `moduleType` paths, no Pure Data internals.
- Device drift made during rehearsal becomes a reviewable PR, one per song.
- The repo is the source of truth on push.

## Planned, not built

**Chain auto-assembly skill.** Prompt.md requires a Claude skill building chains
from fuzzy tone/vibe/mood descriptions and the full catalog. Deferred until the
CLI works. Ingest populates `tags` to avoid a later re-ingest; see
[catalog.md](catalog.md) and `Prompt/PLAN.md`'s final phase.

## Non-goals

- No daemon, no background device watching. The CLI runs by hand around
  rehearsals and gigs.
- No SSH or network transport for push/pull yet; transport stays pluggable. The
  hardware check does talk to the device, but only reads and never moves files —
  see [validation.md](validation.md).
- No vendoring of patch binaries or Pure Data source. Band-authored samples are
  user content and exempt — see [media.md](media.md).
- No custom Pure Data patches. Chains use ORHACK built-ins and community
  modules.

## The guarantee, and its edges

The core promise is reproducibility: the repo defines the rig. Three things sit
deliberately outside it, each a conscious trade recorded in
[decisions.md](decisions.md):

- **Sequencer patterns and morpher banks** are untracked. Note material comes
  from a hand-authored DAW file played by an external controller, so on-device
  sequencers are not where the band's compositional work lives.
- **On-device parameter tweaks** are captured by pull, but overwritten by the
  next push if not merged.
- **Samples added to the card by hand** are destroyed by the next push. The repo
  owns the sample folders outright.
