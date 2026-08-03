# Phase 6 — Reverse mapper

## Goal

`params.json` → edits applied to an **existing** song file, preserving comments
and formatting. The inverse of Phase 3 for everything drift covers.

## Read first

`../docs/workflows/pull.md` ("What drift covers"), `../docs/schema.md`,
`../docs/platform/samples.md`, `../docs/platform/routing.md`,
`../docs/decisions.md` #17, #39.

## Scope

Edit **only what moved**. This is a patch applier, not a song emitter — minting
a new song file from a preset is Phase 7's separate adoption emitter, not a
special case here.

Drift covers: module placement, all module parameters, CC mappings, mod-bus
routing, and router settings including per-chain input gains and MIDI channels.

Invert, at minimum:

| Device | Song field |
|---|---|
| `samp_source` + `samp_select` | `sample: <alias>/<file>` |
| directory-name numeric prefix | `program` |
| `r-chin-l-gain-N` | `mix.input-gain` |
| `r-chout-gain-N` | `mix.output-gain` |
| `r-chout-l-pan-N`, `r-chout-r-pan-N` | `mix.balance`, `mix.width` |
| `r-notethru-<slot>` | `note-thru` |
| `r-chin-midich-N` | chain `midi: { channel: }` |
| `r-sendP1/P2-<slot>` | module `send:` |
| `midi-mapping.cc` keys | module `midi:` |
| `params.<paramId>` | parameter slug, via the catalog's slug↔id pairs |

## Inverses to get exactly right

**Balance and width.** With pans `l` and `r`:

```
balance = 100 × (l + r) / 2
width   = 100 × (r − l)
```

This preserves arbitrary pan pairs losslessly, which is why the pair exists.

**Samples.** Decode `samp_source` by the table in
`../docs/platform/samples.md` — `1`-`24` are `kit-N` (reverse-looked-up to an
alias through `.rig/kits.yaml`), `25` loops, `26` synths, `27` samples root.
Invert the position formula against the repo folder's **current** listing; safe
because push keeps the device and repo folders in lockstep.

`samp_source` of `0` or `-1` means nothing selected — emit no `sample:` field.

**Never leave a sample to the catalog default.** `samp_source`'s default is `0`,
which decodes to "nothing selected", so a dropped `sample:` field makes the next
push replace a working sampler chain with silence (#39).

**CC keys.** `key = channel * 128 + cc`. Emit the shorthand form only when the
decoded channel equals the chain's own note channel; otherwise emit the explicit
`{ channel:, cc: }` form. On an omni chain, always emit the explicit form.

## Baseline

Diff against the stored `.rig/state/last-pushed/<song>.json` snapshot, **never**
against a recompile. Recompiling would make a changed catalog default look like
device drift, burying real edits in phantom diffs (#17).

## Abort rule

A song that cannot be cleanly reverse-mapped — for example one referencing a
module absent from the catalog — **aborts for that song only, with no partial
write.** Every other drifted song still processes.

## Formatting

ruamel round-trip mode throughout. Comments, key order, quoting style and blank
lines survive. Only the changed scalars change.

## Verification

Property test: compile a song, mutate the preset, reverse-map, then confirm

1. only the mutated values changed in the song file, and
2. every comment survived.

Run it across the full field table above, including a negative `width`, an omni
chain, a `samp_source` of `0`, and a module whose parameter labels collide.

## Done when

The property test passes for every field in the table and the abort path leaves
the song file untouched.
