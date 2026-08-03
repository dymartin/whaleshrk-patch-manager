# Media and Samples

## Positional-reference hazard

The device stores no sample filenames. `samplement` stores a folder selector and
a normalised position; the file is resolved by index into a sorted glob of that
folder. Formula in [platform/samples.md](platform/samples.md).

Therefore **any folder file-count change remaps every sample in it.** Add one
`.wav` to a kit and songs indexing into that kit play different sounds — with no
error and no drift signal, because `params.json` is unchanged.

Sample folders define `params.json` meaning and must be owned for
reproducibility.

## What the repo owns

Plain git versions band-authored samples as user content, outside
[overview.md](overview.md)'s catalog-binary ban.

Repo layout mirrors the device's fixed folders, but kits are named by **alias**:

```
media/
  samples/            -> media/orhack/samples/
  samples/loops/      -> media/orhack/samples/loops/
  samples/synths/     -> media/orhack/samples/synths/
  kits/warehouse/     -> media/orhack/kits/kit-N
  kits/tape/          -> media/orhack/kits/kit-N
```

`.rig/kits.yaml` maps alias to `kit-N`. Kits can be renamed or moved between
slot numbers without touching any song file.

The compiler emits `samp_source` using the encoding in
[platform/samples.md](platform/samples.md) — `1`-`24` for kits (value = kit
number), `25` loops, `26` synths, `27` samples root; `0` and `-1` select
nothing. This is not the ordering the parameter's declared range implies, and
getting it wrong plays from the wrong folder silently.

Songs reference `<alias>/<filename>`; the compiler computes the positional value
from the repo folder's contents at push time, which it can do exactly because
push owns those folders.

Playback files must use lowercase `.wav`, portable names, and no
case-insensitive collisions. Reject symlinks, duplicate `kit-N` assignments, and
more than 24 aliases — `deploy.sh` creates exactly `kit-1`…`kit-24` and
`samp_source` cannot address a 25th. Warn about ignored non-`.wav` files.

## Push mirrors, including deletions

The four playback paths above are mirrored exactly — files on the card that are
not in the repo are **deleted**. That is what makes positional references
trustworthy; an additive copy leaves stray files shifting every index.

Two paths are excluded and never touched, because the device writes them:

- `media/orhack/recordings/` — multitrack capture output
- `media/samples/` — shared Organelle directory, written by the sampler's own
  record function

## Pull ignores media

Media is push-only. A `.wav` dropped on the card by hand is destroyed by the
next push with no record — the same rule as an on-device knob tweak, but with
higher stakes since it is a file rather than a value.

Pull captures device *parameter* changes, not *media*. One new `.wav` shifts
ordinals for every song using its folder, incompatible with one PR per song.

## Samples are global state

Ordinals resolve within the device's fixed folders, so the layout cannot be
reorganised per song. Samples are a single shared pool across all songs — the
only global state in an otherwise strictly per-song design. Editing a kit
affects every song that indexes into it.
