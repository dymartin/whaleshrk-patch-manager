# Workflows

Run manually around rehearsals and gigs; no daemon.

```text
rig push [SONG...] [--dry-run] [--force]
rig pull [SONG...] [--dry-run] [--adopt]
rig lint [SONG...]
rig catalog update [--dry-run]
rig upgrade MODULE... [--dry-run]
rig rename-chain SONG OLD NEW
rig validate --tier static|hardware [SONG...]
rig validate verify-report REPORT
```

Empty song selection means all songs.

| Doc | Covers |
|---|---|
| [push.md](push.md) | Card reconciliation, compile, preset classification, transaction |
| [pull.md](pull.md) | Drift detection, PRs, adoption, what drift covers |
| [maintenance.md](maintenance.md) | `rename-chain`, `upgrade` |

`validate` belongs to [../validation.md](../validation.md).

## Song identity

Push records the preset directory name and program it wrote, in
`.rig/state/last-pushed/<song>.meta.json`. Everything below follows from that
one record.

**Renaming a song, or changing its `program`,** changes the compiled directory
name. Push compares computed against recorded, recognises the rename, and moves
the directory inside the same transaction. No command, no `--force`.

**Deleting a song** is `git rm`. Push sees a record with no song file and
removes the directory. Because the ordering rule is pull-before-push, any
unmerged device drift on that song is already captured as a PR.

**Adoption writes the record too**, so the preset a song was adopted from is
recognised as managed on the next push rather than refused as a stranger.

State is per song by design. A single shared manifest would be edited by every
song's PR — the entanglement one-PR-per-song forbids.

## `--dry-run`

Reports the planned change set and writes nothing.

`push` and `pull` dry-runs **require the mounted card** and apply the real
command's preconditions and refusals. The destructive set — deletions, renames,
module replacement — is a comparison of card against repo, so a cardless
dry-run could only report the harmless part while appearing complete. `rig lint`
is the offline check.

Dry-run still performs the same network update *check* as a real push, under the
same rule: unreachable source skips silently. `pull --dry-run` creates no branch,
commit or PR; read-only `gh` queries to detect an existing open PR are fine.

## Ordering

**Pull before push.** Push refuses unknown presets by default; `push --force`
deliberately deletes them for disposable experimentation.

After `rig upgrade` or `rig catalog update`, the next push must be a full push.
