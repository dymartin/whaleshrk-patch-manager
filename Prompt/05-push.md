# Phase 5 — Push

## Goal

`rig push [SONG...] [--dry-run] [--force]` — make the card match the repo.
Composes Phases 1-4.

## Read first

`../docs/workflows/push.md` (owns this phase), `../docs/workflows/README.md`,
`../docs/media.md`, `../docs/platform/card.md`, `../docs/platform/state.md`
(dangling `currentPreset`), `../docs/decisions.md` #4, #29, #44, #45, #51, #52,
#53, #57, #58, #59.

## Sequence

### 1. Resolve the card

Through the Phase 4 transport. Refuse on zero or multiple candidates.

### 2. Reconcile modules

Verify ORHACK structure, optionally its 2,353-entry manifest — `install_package.sh`
regenerates sha1sums and diffs against the package's own `manifest.txt`, so this
is an offline integrity check needing no network and no device. **Never install
or repair ORHACK** (#45).

Reconcile installed modules against `.rig/modules.lock` **by content hash**:
install what is missing, replace what does not match. An upgraded module is
present at the wrong version, not absent — hash comparison is the only check
that catches it.

Report available updates. Never install them.

**Refuse a selective push when the lock changed since the last push.** Modules
are repo-wide: one card holds one copy, so reconciliation cannot be scoped to a
song selection without leaving the card matching no commit. Tell the user to
rerun with no selection. This triggers only after `rig upgrade` or
`rig catalog update`.

Two offline cases, deliberately different (#29):

| Situation | Behaviour |
|---|---|
| Cannot reach a source to *check* for updates | Silent skip. Never blocks push |
| A module named in the lock is absent from the card and its source is unreachable | **Hard error, push aborts** |

The second cannot be skipped: the preset would reference a `moduleType` that
does not resolve, producing a silently broken slot.

### 3. Compile

Each selected song, via Phase 3. Two points that belong to push rather than the
compiler:

- Zero-padded 3-digit `program` prefixes with silent gap placeholders below the
  highest program in use.
- Sidecar `.txt` files inside a preset directory are **mirrored, deletions
  included** — a slot whose occupant changed must have the previous module's
  files removed.

### 4. Classify every card preset

Against `.rig/state/last-pushed/*.meta.json`:

| Card preset | Meaning | Action |
|---|---|---|
| Recorded, song file present | Managed song, possibly renamed | Write it; **rename the directory** if the recorded name differs |
| Recorded, song file gone | Deliberate deletion | **Delete on a plain push**, named in the output |
| Not recorded | Made on the device | **Refuse.** `--force` deletes |

`--force` bypasses **only** the third refusal. All validation still applies.
`Init` is never touched, under any flag — the `chmod 555` in `deploy.sh` only
takes effect on an ext-formatted card, so protect it by rule.

Retiring a song therefore does not require the flag that destroys unmerged
device experiments (#52).

### 5. Detect an un-commanded chain rename

An orphaned binding in `.rig/state/chains/` plus a chain with no binding means
someone hand-edited `name:`. **Refuse**, naming the likely rename and the command
that performs it (`rig rename-chain SONG OLD NEW`). Ambiguous cases list every
candidate and refuse.

Without this the compiler assigns a fresh letter and the next pull reports drift
on a song nobody musically touched.

### 6. Mirror media

The four playback paths, deletions included:

```
media/samples/ → media/orhack/samples/
media/samples/loops/ → media/orhack/samples/loops/
media/samples/synths/ → media/orhack/samples/synths/
media/kits/<alias>/ → media/orhack/kits/kit-N        (via .rig/kits.yaml)
```

**Excluded and never touched** — the device writes them:

- `media/orhack/recordings/` — multitrack capture, the only irreplaceable thing
  on the card;
- `media/samples/` on the card — shared Organelle directory written by the
  sampler's own record function.

Mirroring with deletions is what makes positional sample references
trustworthy. An additive copy leaves stray files that shift every ordinal.

### 7. Transact

Stage the complete target on-card with a hash manifest, then:

```
flush → rename live directories to backups → install staged directories
      → flush → verify hashes
```

Each individual file also uses temporary-file-plus-rename. I/O failure restores
backups.

Write a journal. **Recover an interrupted transaction before any new push** —
read the journal and either complete or restore, deterministically. Operator
guidance: do not insert an interrupted card into the device; reconnect it and
rerun push.

Global atomicity is impossible — presets and positional media use separate fixed
roots — so a journalled recovery is the strongest available guarantee (#44).

### 8. Repair `currentPreset`

In `data/orhack/rack.json`, **only if this push left it naming a directory that
no longer exists.** Repoint to the lowest-numbered managed preset, else `Init`.
Otherwise leave it alone: it is the device's performance cursor, not repo state.

Why it matters: a dangling `currentPreset` is not a startup failure and not a
silent device. `Rack::loadSettings` calls `loadFilePreset` on the name
unconditionally without checking the scanned list; a missing `params.json` logs
`unable to load preferences file` and returns, leaving the device booted into
`main.pd`'s hardcoded rack — which declares `a1 = sequencers/sequences` and
`a2 = instruments/modular/plaits+`, **two paths that do not exist**. Next/prev
preset then both jump to index 0, and the next on-device save materialises that
broken rack under the missing name. Pull would see it as drift.

### 9. Record state

Only **after** card verification:

- `.rig/state/last-pushed/<song>.json` — the compiled `params.json`,
  byte-exact, so verification is a plain hash comparison and the drift diff
  needs no unwrapping;
- `.rig/state/last-pushed/<song>.meta.json` — the preset directory name and
  program actually written;
- `.rig/state/chains/<song>` — the name→letter bindings.

Then remove backups and the transaction marker.

## `--dry-run`

Reports the exact planned change set, touches nothing. **Requires the mounted
card** and applies the real command's preconditions and refusals — the
destructive set is a comparison of card against repo, so a cardless dry-run
could only report the harmless part while appearing complete (#59). It still
performs the same network update *check*, under the same silent-skip rule.

## Verification

- Push to a fixture card, assert the resulting tree **exactly**.
- Assert rollback leaves the card unchanged.
- Assert every refusal path: unrecorded preset without `--force`, selective push
  after a lock change, absent module with unreachable source, un-commanded chain
  rename, zero/multiple cards.
- **Rename, delete and `currentPreset` repair each need a seeded-card test** —
  all three are comparisons against recorded state, not pure functions of the
  repo.
- **Gap placeholders and sidecar mirror-with-deletion are push's, not the
  compiler's** — the compiler cannot see the whole song set or the card. Assert
  a placeholder appears for every unused program below the highest in use, and
  that pushing a song whose slot occupant changed removes the previous module's
  sidecar files.
- `--dry-run` leaves both card and repo byte-identical.

## Done when

Every bullet above has a passing test and an interrupted-journal fixture
recovers deterministically.
