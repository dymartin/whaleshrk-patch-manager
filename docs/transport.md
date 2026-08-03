# Transport Layer

Pluggable; USB mass storage is today's only implementation. SSH can be added
without rewriting sync logic.

The hardware check's network session is separate and read-only. It drives a test
run over MIDI and the device's web API; it moves no files and implements none of
this.

## Interface

```
exists(path) -> bool
list(path)   -> list[str]
read(path)   -> bytes
write(path, data)
delete(path)
mkdir(path)
rename(source, target)
flush()
```

Sync, mirroring, diff and compile logic lives **above** this shared layer.
Per-backend differences in deletion or exclusion rules are where a subtle
difference eats samples.

Chattiness over SSH is acceptable. Presets are kilobytes; media sync batches
above this layer.

`rename` powers temporary-file replacement and transaction directory swaps.
`flush` must not return until buffered writes reach the storage device.

## Implementations

- **`UsbMassStorage(root)`** — the card mounted as a filesystem. Paths are
  card-relative: `data/orhack/rack.json`, not an absolute mount path.
- **`Ssh(host, root)`** — not implemented; needs no changes above this layer.
- An in-memory implementation tests sync and mirroring without a card.

## Card identification

By structure, not drive letter or label: a candidate root must contain
`data/orhack/` and `Patches/0RHACK/`. Refuse rather than guess on zero or
multiple candidates — writing a mirror-with-deletions to the wrong volume is
unrecoverable.

## Paths

The transport works in card-relative paths. The `/tmp/...` paths throughout
ORHACK's Pure Data source are runtime symlinks created by the Organelle
firmware and never exist on the card — see [platform/state.md](platform/state.md).
