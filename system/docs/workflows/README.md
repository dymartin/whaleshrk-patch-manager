# Workflows

Run manually around rehearsals and gigs; no daemon.

```text
rig push [SONG...] [--dry-run] [--force]
rig pull [SONG...] [--dry-run]
rig lint [SONG...]
rig catalog add SLUG...
rig catalog update [--dry-run]
rig upgrade MODULE... [--dry-run]
rig rename-chain SONG OLD NEW
```

Empty song selection means all songs.

`catalog add` and `upgrade` are the only commands that reach the network.

| Doc | Covers |
|---|---|
| [push.md](push.md) | Card reconciliation, compile, preset classification, transaction |
| [pull.md](pull.md) | Drift detection, PRs, what drift covers |
| [maintenance.md](maintenance.md) | `rename-chain`, `upgrade` |

`lint` belongs to [../validation.md](../validation.md).

## Song identity

Push records the preset directory name and program it wrote, in
`system/data/state/last-pushed/<song>.meta.json`. Everything below follows from that
one record.

**Renaming a song, or changing its `program`,** changes the compiled directory
name. Push compares computed against recorded, recognises the rename, and moves
the directory inside the same transaction. No command, no `--force`.

**Deleting a song** is `git rm`. Push sees a record with no song file and
removes the directory. Because the ordering rule is pull-before-push, any
unmerged device drift on that song is already captured as a PR.

**A song exists because the repo says so.** Pull never mints one; a card
preset no record claims is reported and otherwise ignored.

State is per song by design. A single shared manifest would be edited by every
song's PR — the entanglement one-PR-per-song forbids.

## `--dry-run`

Reports the planned change set and writes nothing.

`push` and `pull` dry-runs **require the reachable SSH device**, or an explicitly
selected mounted USB card, and apply the real command's preconditions and
refusals. The destructive set — deletions, renames, module replacement — is a
comparison of device against repo, so a device-free dry-run could only report
the harmless part while appearing complete. `rig lint` is the offline check.

Push reaches no network at all, dry-run or not — it installs from `system/modules/`.
`pull --dry-run` creates no branch, commit or PR; read-only `gh` queries to
detect an existing open PR are fine.

## Ordering

**Pull before push.** Push refuses unknown presets by default; `push --force`
deliberately deletes them for disposable experimentation.

After `rig upgrade` or `rig catalog update`, the next push must be a full push.
