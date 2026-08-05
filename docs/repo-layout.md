# Repository Layout

```
songs/                      musician-facing
  vellichor.yaml
  low-tide.yaml

media/                      musician-facing
  samples/
  samples/loops/
  samples/synths/
  kits/warehouse/*.wav      alias-named, not kit-N
  kits/tape/*.wav

.rig/                       machine-owned, committed
  catalog/                  generated module metadata
  state/
    last-pushed/
      <song>.json           compiled params.json per song, byte-exact
      <song>.meta.json      preset directory name + program as pushed
    chains/
      <song>.json           chain name -> letter binding, this song only
    hardware/               <song>.json — load time + CPU baseline per subject
  kits.yaml                 kit alias -> kit-N
  modules.lock              pinned versions + content hashes
```

Musicians edit `songs/` and `media/`; the CLI owns `.rig/`.

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

**All state is keyed per song, never in a shared file.** A single manifest would
be edited by every song's PR, entangling reviews that must stay independent.

Some tools hide dotted directories locally; GitHub still shows their PR diffs.

## One file per song

One file per song enables one PR per drifted song. Each PR touches one `songs/`
file and its `.rig/state/last-pushed/` entry.

Module versions are pinned repo-wide, not per song. Two songs cannot expect
different versions of the same module — one card holds one installed copy.
