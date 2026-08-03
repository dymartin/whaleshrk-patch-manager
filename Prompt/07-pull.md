# Phase 7 — Pull

## Goal

`rig pull [SONG...] [--dry-run]` — turn device drift into one branch and PR per
drifted song, and adopt unknown presets as new songs.

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
5. Adopt presets with no song file as new songs, one PR each.
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

## Adoption

Adoption **mints** a song file. Build it as a **separate emitter**, not a
special case of the reverse mapper.

Device presets carry no friendly names, so derive them without exposing device
identifiers:

| Field | Rule |
|---|---|
| Song slug | Preset name, lowercased, non-alphanumerics collapsed to `-`. Collisions take `-2`, `-3`. Used as both filename and branch name |
| `program` | A recognised numeric prefix becomes the YAML `program`; otherwise assign the next free value. The PR invites correction before merge |
| Chain and send names | Catalog key of the first module with `@source` dropped — a chain starting with `rings@orhack` becomes `rings`. Duplicates within a song take `-2`, `-3`. **Empty chains and sends are omitted, not named** |

Never name a chain `chain-a` — that would embed a slot letter, the exact class of
device identifier the schema hides (#36).

**Preserve chain letters, do not recompute them.** Declaration order alone will
not reproduce the device's assignment — a 3-module chain on D would be reassigned
to C by the capacity rule, and the next pull would report drift on a song nobody
touched. Adoption writes the observed name→letter binding into
`.rig/state/chains/`; the compiler honours a recorded binding instead of
assigning (#37).

**Preserve MIDI channels likewise.** Device `r-chin-midich-N` values need not
match what declaration position produces, so write an explicit
`midi: { channel: N }` on any chain whose channel differs from its positional
default.

**Adoption writes both `.rig/state/last-pushed/` files:**

- `<song>.json` — the observed `params.json`, snapshotted. Without it the song
  has no drift baseline — it is never pushed, being already correct on the
  device — and the next pull reports the whole preset as drift (#38).
- `<song>.meta.json` — the observed directory name and program. Without it the
  next push refuses the preset it just adopted as a stranger.

**Reverse-map the sample selection, never default it.** With no `sample:` field,
#13 fills `samp_source` from its catalog default of `0` and the next push
replaces a working sampler chain with silence.

The PR body states that names were derived and invites renaming before merge,
pointing at `rig rename-chain` for chains.

## `--dry-run`

Requires the mounted card and applies the real command's preconditions and
refusals. Creates no branch, commit or PR. Read-only `gh` queries to detect an
existing open PR are fine.

## Verification

Fixture card with seeded drift produces the expected branch and PR set, with
`gh` stubbed. Cover:

- one drifted song, one clean song — only the drifted one gets a branch;
- a second pull on the same drift force-pushes and reuses the open PR;
- an unmapped module aborts that song only, others still process;
- one recorded preset missing warns; all missing aborts;
- an unknown preset adopts, writing both state files and the chain binding;
- an adopted song, pushed immediately, is recognised as managed;
- an adopted song, pulled immediately again, reports no drift.

## Done when

Every bullet above passes and `gh` absence produces a clear, non-crashing error.
