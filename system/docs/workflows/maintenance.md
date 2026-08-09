# Renaming chains, upgrading modules

## `rig rename-chain SONG OLD NEW`

Rewrites `name:` in the song file and matching `system/data/state/chains/` binding
together. The binding is name-keyed, so the two must move as one.

Editing `name:` by hand orphans the binding. The compiler would then assign a
fresh letter and the next pull would report drift on a song nobody musically
touched. Push detects this — a binding whose chain is gone, plus a chain with no
binding — and refuses, naming the likely rename and the command that performs
it. Ambiguous cases list every candidate and refuse.

Chains cannot be renamed on the device; it stores no chain names at all.

## `rig upgrade MODULE... [--dry-run]`

Repo-only: rewrites `system/data/modules.lock` and `system/data/catalog/`, touches no card and
needs none. It **never** rewrites `system/data/state/last-pushed/` — the card is
unchanged by an upgrade, so doing so would fabricate a drift baseline and hide
real device edits on the next pull.

**An upgrade is refused when a parameter slug used by any song changes the
parameter id behind it.** Parameter names are `slug(label)` with an index suffix
following declaration order, so an upstream reorder leaves `amount-3` resolving
happily to a different parameter — no error, no song-file diff, different sound.
The catalog stores the real id beside each slug, which makes the break
detectable while it is still cheap to fix. Slugs no song uses remap freely.

The report names every affected slug, song and module. Proceeding means editing
the affected songs by hand.

Changed *defaults* need no special handling: decision #13 pins them per module
version, so they surface as a reviewable `system/data/catalog/` diff.
