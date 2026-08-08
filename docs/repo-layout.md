# Repository Layout

```
.claude/skills/assemble-chain/   fuzzy-description chain assembly skill

songs/                      musician-facing
  vellichor.yaml
  low-tide.yaml

media/                      musician-facing
  samples/
  samples/loops/
  samples/synths/
  kits/warehouse/*.wav      alias-named, not kit-N
  kits/tape/*.wav

modules/                    vendored, committed
  <slug>@v<revision>.zip    the Patchstorage upload, byte-identical

.rig/                       machine-owned, committed
  catalog/                  generated module metadata
  state/
    last-pushed/
      <song>.json           compiled params.json per song, byte-exact
      <song>.meta.json      preset directory name + program as pushed
      .modules-lock-hash    hash of modules.lock as of the last push
    chains/
      <song>.json           chain name -> letter binding, this song only
    hardware/
      <song>.json           subject-scoped hardware baseline
  kits.yaml                 kit alias -> kit-N
  modules.lock              pinned versions + content hashes
```

`modules/` is top-level rather than under `.rig/` because these are vendored
inputs the repo owns, not state the CLI generates. Musicians never open it;
it is beside `songs/` and `media/` so the repo's dependencies are visible
rather than hidden in a dot-directory. See [catalog.md](catalog.md) "The
archive store".

`<song>` is the song's YAML filename stem (`songs/vellichor.yaml` -> `vellichor`),
never `slug(song's "name:")`. It has to be the stable one: a musician can
change `name:` — that is exactly the rename push's classify step detects by
comparing the recorded directory against what the song compiles to now — and
the state lookup key has to survive that change, or a rename reads as
delete-then-create instead.

`.modules-lock-hash` is a single hash, not per-song: reconciliation is
repo-wide (one card, one module set), so a selective push can refuse by
comparing it to the current lock's hash rather than re-deriving anything
(see [workflows/push.md](workflows/push.md)).

`state/hardware/<song>.json` records the first passing load-time and CPU
measurement for one complete hardware subject. A subject change replaces the
baseline on the next passing run; ordinary regressions warn against the existing
baseline rather than moving it.

Musicians edit `songs/` and `media/`; the CLI owns `.rig/` and `modules/`.

## Why `.rig/` is committed

`.rig/state/last-pushed/` is the drift baseline; `modules.lock` makes push
reproducible. Both must travel with the repo and stay reviewable.

`<song>.json` is a byte-exact copy of what was written to the card, so push
verification is a plain hash comparison and the drift diff needs no unwrapping.
The directory name push chose lives in a sidecar for that reason.

`state/chains/<song>.json` is a flat JSON object, chain name to letter
("A"-"D"), keys sorted, two-space indent, trailing newline -- the same
convention as every other `.rig/` JSON file. A recorded binding is
authoritative (see [schema.md](schema.md) "Chain letters"): push writes it,
pull uses it to attribute drift, `rename-chain` rewrites it, and the compiler
assigns letters only where no binding exists. Read and write it only through
`rig.song.bindings`, so those three call sites can't drift from one another.

`kits.yaml` is a flat YAML mapping, alias to kit number: `warehouse: 1`. The
value is the plain integer `deploy.sh` gave that slot (`1`-`24`), not the
`kit-N` string. Read and write it only through `rig.song.kits`.

**All state is keyed per song, never in a shared file.** A single manifest would
be edited by every song's PR, entangling reviews that must stay independent.

Some tools hide dotted directories locally; GitHub still shows their PR diffs.

## One file per song

One file per song enables one PR per drifted song. Each PR touches one `songs/`
file and its `.rig/state/last-pushed/` entry.

Module versions are pinned repo-wide, not per song. Two songs cannot expect
different versions of the same module — one card holds one installed copy.
