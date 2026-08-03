# Phase 8 — Lint and CLI surface

## Goal

The error/warning policy, and every remaining command wired up.

## Read first

`../docs/schema.md` ("Lint policy"), `../docs/workflows/README.md`,
`../docs/workflows/maintenance.md`, `../docs/decisions.md` #43, #56, #59.

## Lint policy

**Errors** cover deterministic breakage or destruction:

wrong slot class; CC 1 or CC 74; channel-16 conflicts; invalid or missing
samples or kits; non-finite values; undeclared sends; unsafe, reserved, overlong
or case-colliding paths; duplicate runtime module paths; unsafe archives.

**Warnings** cover valid but suspicious choices:

instrument after effect; two chains on the same numbered channel; a CC mapped to
multiple targets; an unused send; an empty chain; an unselected sampler;
above-unity gain; narrow width; ignored non-`.wav` media; `note-thru` on a
final slot.

Warn about repeated DSP-heavy modules **only with measured cost data** — Phase 10
is the only source of that, and it does not exist until Phase 10 runs.

## Commands

```
rig push [SONG...] [--dry-run] [--force]
rig pull [SONG...] [--dry-run]
rig lint [SONG...]
rig catalog update [--dry-run]
rig upgrade MODULE... [--dry-run]
rig rename-chain SONG OLD NEW
rig validate --tier static|hardware [SONG...]
rig validate verify-report REPORT
```

Empty song selection means all songs.

### `rig rename-chain SONG OLD NEW`

Rewrites `name:` in the song file **and** the matching `.rig/state/chains/`
binding, in one commit. The binding is name-keyed, so the two must move
together.

Editing `name:` by hand orphans the binding; push detects that and refuses
(Phase 5). Chains cannot be renamed on the device — it stores no chain names at
all.

### `rig upgrade MODULE... [--dry-run]`

Repo-only: rewrites `.rig/modules.lock` and `.rig/catalog/`. Touches no card and
needs none.

**Never rewrites `.rig/state/last-pushed/`.** The card is unchanged by an
upgrade, so doing so would fabricate a drift baseline and hide real device edits
on the next pull (#56).

**Refuses when a parameter slug used by any song changes the parameter id behind
it.** Parameter names are `slug(label)` with an index suffix following
declaration order, so an upstream reorder leaves `amount-3` resolving happily to
a different parameter — no error, no song-file diff, different sound. Slugs no
song uses remap freely.

This needs the catalog's recorded slug→id pairs from Phase 1, so it **cannot be
stubbed**. `fission` shares labels across 83 of 97 parameters, so this is
routine, not hypothetical.

The report names every affected slug, song and module. Proceeding means editing
the affected songs by hand.

Changed *defaults* need no special handling — #13 pins them per module version,
so they surface as a reviewable `.rig/catalog/` diff.

### Song rename and deletion need no command

Both fall out of Phase 5's preset classification. Renaming a song or changing
its `program` changes the compiled directory name; push compares computed
against recorded and moves the directory inside the same transaction. Deleting a
song is `git rm`; push sees a record with no song file and removes the directory.

## `--dry-run` on every mutating command

Reports the exact planned change set and touches nothing.

`push` and `pull` dry-runs **require the mounted card** and apply the real
command's preconditions and refusals. `rig lint` is the offline check.

## Ordering rules to surface in help text and errors

- **Pull before push.** Push refuses unknown presets by default.
- After `rig upgrade` or `rig catalog update`, the next push must be a full
  push.

## Verification

- One test per command asserting exit codes.
- `--dry-run` leaves both card and repo byte-identical, for every mutating
  command.
- A **slug→id reorder fixture** that `rig upgrade` must refuse.
- A **hand-renamed chain** that push must refuse, naming `rig rename-chain`.
- Every lint error and warning in the policy above has a fixture and a distinct
  identifier.

## Done when

All commands exit correctly, dry-runs are provably inert, and the two refusal
fixtures pass.
