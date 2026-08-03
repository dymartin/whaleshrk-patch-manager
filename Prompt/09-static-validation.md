# Phase 9 — Static validation and CI (Tier 1)

## Goal

The canonical report schema, `rig validate --tier static`, `verify-report`, and
a required GitHub Actions job.

## Read first

`../docs/validation.md` (owns this phase), `../docs/catalog.md` (the gate),
`../docs/schema.md` (lint rules), `../docs/decisions.md` #61, #68.

## Land the report schema first

Phase 10 consumes it, so it lands before the tier that emits it. Canonical,
versioned JSON, with:

```
verdict            pass | fail | unavailable
tier               static | hardware
subject            (below)
run id
per-song checks    each may itself be `unavailable`
metrics
failures
start / end times
```

**Subject** is the exact identity a result belongs to:

```
commit + report schema + module-lock digest + S2 device id
+ OS 5.1 + Pd version + ORHACK 0.52b + MIDI port name
+ stimulus profile version
```

The stimulus profile is part of the subject because the numbers mean nothing
without it — lengthening the idle window or changing the note pattern changes
every measurement. Bumping the profile invalidates existing baselines by design.

Static-tier runs fill the members they can and mark the device-only members
absent.

Pin `Pd 0.53.1`, Debian bookworm's `puredata` (`0.53.1+ds-2+deb12u1`) at
`/usr/bin/pd`. Derived from the OS build recipe and confirmed against upstream
source, **not yet observed** — Phase 10 replaces it with the observed
`pd -version`. Audio subject is 44100 Hz, 64-sample blocks, `-audiobuf 6`
headless.

## `rig validate --tier static [SONG...]`

Runs, over every locked module and every song:

- the **Phase 1 catalog gate** — safe archive, valid metadata, ARM32 hard-float
  little-endian ELF, `DT_NEEDED` warnings, unique runtime path, modelled
  sidecars;
- the **Phase 2 schema rules and Phase 8 lint rules**.

Then emits a report.

**No symbol or Pd-object resolution** (#68). It was specified once and dropped:
the check needed a pinned Pd/rootfs symbol manifest that was a by-product of the
simulated-OS tier, and #61 removed that tier. Rebuilding the manifest from
Debian packages is real machinery to build, commit and keep in step, for a
failure the hardware check now catches anyway as a `couldn't create` line in the
device log. Cost, stated: an unresolvable external is found at rehearsal rather
than on a pull request.

A local song filter is **diagnostic only**. Static success never claims CPU cost
or that a module loads.

Confidence level produced: `static-only`.

## `rig validate verify-report REPORT`

Verifies a report has not been edited since it was written.

## CI

Required GitHub Actions job on every pull request and push. Public repo, so
Actions minutes are unmetered and this runs unconditionally.

CI also regenerates the catalog from the **frozen fixture** and fails on diff.
Never hits the live API.

## Verification

| Fixture | Expected |
|---|---|
| Broken ELF | fails with the intended check id |
| Wrong architecture | fails with the intended check id |
| Unsafe archive | fails with the intended check id |
| Unmodelled sidecar | fails with the intended check id |
| Good fixture | passes |
| Hand-edited report | `verify-report` rejects it |

## Done when

All six rows pass and the Actions job is required on the default branch.
