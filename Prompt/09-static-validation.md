# Phase 9 — Lint and CI

## Goal

`rig lint [SONG...]` and a required GitHub Actions job.

## Read first

`../docs/validation.md` (owns this phase), `../docs/catalog.md` (the gate),
`../docs/schema.md` (lint rules), `../docs/decisions.md` #61, #68, #71, #73.

## No report artifact

Decision #73. No `Report` schema, no `run_id`, no `confidence`/`scope_note`,
no sha256 `verify-report`, no `--tier` flag. Findings go to stdout/stderr and
the exit code carries the verdict — that is the whole contract CI needs, and
CI's own step never consumed anything more.

Phase 10 prints its measurements rather than filling a shape, so nothing here
lands "first" on its behalf.

## `rig lint [SONG...]`

Two checks, both offline:

- **Songs** — the Phase 2 schema rules and the Phase 8 lint rules per song,
  plus the cross-song rules. A song filter is **diagnostic only**; cross-song
  rules always run over every song.
- **Stored archives** — for every module `.rig/modules.lock` pins, read
  `modules/<slug>@v<revision>.zip`, verify it against `archive_sha256`, re-run
  the Phase 1 catalog gate over it, and locate the module the catalog entry
  names inside it.

The second check is the repo's reproducibility proof: it demonstrates
`.rig/catalog/` was generated from the archives actually committed rather than
hand-edited. It is affordable on every run because the catalog is a shopping
list, not a mirror of Patchstorage (#71).

Exit non-zero on any error. Warnings do not fail.

**No symbol or Pd-object resolution** (#68). It was specified once and dropped:
the check needed a pinned Pd/rootfs symbol manifest that was a by-product of the
simulated-OS tier, and #61 removed that tier. Rebuilding the manifest from
Debian packages is real machinery to build, commit and keep in step, for a
failure the hardware check now catches anyway as a `couldn't create` line in the
device log. Cost, stated: an unresolvable external is found at rehearsal rather
than on a pull request.

Lint never claims CPU cost or that a module loads.

## CI

Required GitHub Actions job on every pull request and push. Public repo, so
Actions minutes are unmetered and this runs unconditionally.

`uv run pytest -q`, then `uv run rig lint`. Every socket is blocked for the
whole pytest session, and `rig lint` opens none, so CI never reaches the live
API.

## Verification

| Fixture | Expected |
|---|---|
| Broken ELF archive | fails |
| Wrong-architecture archive | fails |
| Unsafe archive | fails |
| Unmodelled-sidecar archive | fails |
| Locked module with no committed archive | fails |
| Committed archive failing its pinned digest | fails |
| Good repo | passes, exit 0 |

## Done when

All seven rows pass and the Actions job is required on the default branch.
