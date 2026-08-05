# Push

Push makes the card match the source-of-truth repo.

1. Resolve the card via the transport layer.

2. **Reconcile modules.** Verify ORHACK structure, optionally its 2,353-entry
   manifest; never install or repair ORHACK. Reconcile installed modules
   against `.rig/modules.lock` **by content hash** — install what is missing,
   replace what does not match, since an upgraded module is present at the
   wrong version rather than absent. Report available updates; never install
   them.

   Modules are repo-wide: one card holds one copy, so reconciliation cannot be
   scoped to a song selection without leaving the card matching no commit. **A
   selective push is therefore refused when the lock has changed since the last
   push** — rerun with no selection. This triggers only after `rig upgrade` or
   `rig catalog update`.

   Two offline cases, deliberately different:

   | Situation | Behaviour |
   |---|---|
   | Cannot reach a source to *check* for updates | Silent skip. Never blocks push |
   | A module named in the lock is absent from the card and its source is unreachable | **Hard error, push aborts** |

   The second cannot be skipped: the preset would reference a `moduleType` that
   does not resolve, producing a silently broken slot.

3. **Compile** each selected song to a preset directory, per
   [../schema.md](../schema.md) and [../platform/](../platform/README.md). Two
   points that are push's own rather than the compiler's:

   - Preset directories carry a zero-padded 3-digit `program` prefix, with
     silent gap placeholders below the highest program in use, so the device's
     directory sort keeps every index aligned.
   - Sidecar `.txt` files inside the preset directory are **mirrored, deletions
     included** — not merely added. Sidecars are slot-keyed, so a slot whose
     occupant changed must have the previous module's files removed, or the new
     module loads the old one's arrays. Adding-only reproduces the staleness
     bug decision #1 exists to prevent, from the compiler side.

4. **Classify** every preset directory on the card against
   `.rig/state/last-pushed/*.meta.json`:

   | Card preset | Meaning | Action |
   |---|---|---|
   | Recorded, song file present | Managed song, possibly renamed | Write it; rename the directory if the recorded name differs |
   | Recorded, song file gone | Deliberate deletion | **Delete on a plain push**, named in the output |
   | Not recorded | Made on the device | Refuse. `--force` deletes |

   `--force` bypasses only the third refusal; all validation still applies, and
   `Init` is never touched. Retiring a song therefore does not require the flag
   that destroys unmerged device experiments.

5. **Mirror** the media playback folders, deletions included, excluding the two
   device-owned paths.

6. **Stage** the complete target on-card with a hash manifest. Flush, rename
   live directories to backups, install staged directories, flush, verify
   hashes. Each file also uses temporary-file-plus-rename.

7. **Repair `currentPreset`** in `data/orhack/rack.json` only if this push left
   it naming a directory that no longer exists — repoint to the lowest-numbered
   managed preset, or `Init` if none survive. Otherwise leave it alone: it is
   the device's performance cursor, not repo state.

8. **Record state.** Update `.rig/state/last-pushed/` — params snapshot and
   `.meta.json` — only after card verification, then remove backups and the
   transaction marker.

I/O failure restores backups. Physical removal may interrupt multiple directory
swaps; the next push reads the journal and completes or restores
deterministically. Do not insert an interrupted card into the device —
reconnect it and rerun push. Global atomicity is impossible because presets and
positional media use separate fixed roots.

## Implementation notes

`.rig-push/` is a card path this tool reserves for its own journal and
staging area (`.rig-push/journal.json`, `.rig-push/staging/`), plus a
`<name>.rig-push-backup` sibling next to any directory mid-swap. Never a
preset or media directory; other tooling (pull, a future hardware check)
must not treat it as content and must not need to know its internal shape,
only that it exists and is push's alone.

A gap placeholder is identified by its directory name alone — three bare
digits, no slug suffix, a shape a real song's compiled directory can never
produce (`rig.compile.compiler.build_placeholder`'s `directory` is always
`""`). That is what lets push reconcile placeholders unconditionally, with
no `--force` and no `.rig/state/` record of its own: the pattern is
self-verifying, so there is nothing to look up.
