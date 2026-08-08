# Phase 7 — Pull

Default transport is keyed SSH through the `organelle` alias. USB requires
`--transport usb` and retains structural card detection.

## Goal

`rig pull [SONG...] [--dry-run]` — turn device drift into one branch and PR per
drifted song.

## Read first

`../docs/workflows/pull.md` (owns this phase), `../docs/workflows/README.md`,
`../docs/repo-layout.md`, `../docs/decisions.md` #5, #17, #36, #37, #38, #54,
#55.

## Sequence

1. Read every preset directory on the card.
2. **Match by the recorded directory name** in
   `.rig/state/last-pushed/<song>.meta.json` — never by reconstructing it from
   the song file, never by setlist order. Reconstruction breaks on a repo-side
   rename that has not been pushed yet, and pull-before-push makes that the
   normal order, not an edge case. Ignore compiler-owned gap placeholders.
3. Diff each `params.json` against `.rig/state/last-pushed/<song>.json`.
4. Per drifted song: reverse-map only what moved (Phase 6), edit the song YAML
   in place preserving comments, commit, branch, PR.
5. **Ignore presets no recorded song claims.** Pull never mints a song file
   (#74).
6. **Ignore media entirely** (#5). Sample *selection* is captured — `samp_source`
   and `samp_select` are ordinary parameters — but the media tree is not.

## Missing-preset rules

| Situation | Behaviour |
|---|---|
| One recorded preset absent from the card | **Warn and skip.** Never remove a song file |
| **All** recorded presets absent | **Abort the run** |

The repo is authoritative for song *existence*; the device is authoritative only
for parameter *values* (#54). One missing preset is news about one song; every
one missing is the wrong card, and mirror-with-deletions makes acting on that
unrecoverable.

## Branches and PRs

- Branch name is `pull/<song-slug>` — deterministic, a pure function of the
  song, **no timestamp or counter**.
- A later pull **force-pushes** that branch and **reuses its open PR**,
  replacing earlier unmerged drift. A timestamped name would accumulate stale
  branches and duplicate PRs.
- Open the PR via `gh` when none is open.
- One branch and PR per drifted song. Unrelated songs never share a review.
- Each PR touches one `songs/` file and its `.rig/state/last-pushed/` entry.

`gh` is a runtime prerequisite and is **not installed on the development machine
as of 2026-08-02**. Tests stub it. The command must fail with a clear message
when it is absent.

## Presets no song claims

Reported, never turned into a song file. The repo is authoritative for whether
a song exists; the device is not (#54, #74). Songs are hand-authored and their
parameters are then experimented with on the device — that direction only.

**Chain letters are honoured, not recomputed.** Declaration order alone will
not reproduce an existing assignment — a 3-module chain on D would be
reassigned to C by the capacity rule, and the next pull would report drift on a
song nobody touched. `.rig/state/chains/` records each name→letter binding and
the compiler honours it instead of assigning (#37).

**The drift baseline is written by push**, into `.rig/state/last-pushed/`:
`<song>.json` (the compiled `params.json`, byte-exact) and `<song>.meta.json`
(the directory name and program). A song never pushed has no baseline and
cannot drift.

**Reverse-map the sample selection, never default it.** With no `sample:` field,
#13 fills `samp_source` from its catalog default of `0` and the next push
replaces a working sampler chain with silence.

## `--dry-run`

Requires the reachable SSH device, or an explicitly selected mounted USB card,
and applies the real command's preconditions and refusals. Creates no branch,
commit or PR. Read-only `gh` queries to detect an existing open PR are fine.

## Verification

Fixture card with seeded drift produces the expected branch and PR set, with
`gh` stubbed. Cover:

- one drifted song, one clean song — only the drifted one gets a branch;
- a second pull on the same drift force-pushes and reuses the open PR;
- an unmapped module aborts that song only, others still process;
- one recorded preset missing warns; all missing aborts;
- a card preset no record claims produces no branch and no PR.

## Done when

Every bullet above passes and `gh` absence produces a clear, non-crashing error.
