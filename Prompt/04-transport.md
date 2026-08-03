# Phase 4 — Transport

## Goal

The narrow file protocol, its USB implementation, and structural card detection.

## Read first

`../docs/transport.md` (owns this phase), `../docs/platform/card.md`,
`../docs/platform/state.md`, `../docs/decisions.md` #19, #44.

## Protocol

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

Nothing more. Sync, mirroring, diff and compile logic lives **above** this
layer — per-backend differences in deletion or exclusion rules are exactly where
a subtle bug eats samples.

- `rename` powers temporary-file replacement and transaction directory swaps.
- **`flush` must not return until buffered writes reach the storage device.**
  `mount.sh` mounts with `-o async,noatime`; pulling the card without ejecting
  loses whatever is still in the page cache, on either the device or the host.

## Implementations

- **`UsbMassStorage(root)`** — the card mounted as a filesystem. Paths are
  **card-relative**: `data/orhack/rack.json`, never an absolute mount path.
- **`InMemory`** — from Phase 0, promoted to a first-class implementation.
- **`Ssh(host, root)`** — not implemented. Requires no changes above this layer.

The `/tmp/...` paths throughout ORHACK's Pure Data source are runtime symlinks
the Organelle firmware creates at patch launch. They never exist on the card.
Translate: `/tmp/data/orhack` is `data/orhack`, `/tmp/media` is `media`.

## Card identification

By **structure**, not drive letter or volume label. A candidate root must
contain both:

```
data/orhack/
Patches/0RHACK/
```

**Refuse rather than guess on zero or multiple candidates.** Push does
mirror-with-deletions; writing it to the wrong volume is unrecoverable.

## Verification

One **shared conformance suite** that both `InMemory` and `UsbMassStorage`
pass — same tests, same assertions, no per-backend variants. Cover at minimum:

- write/read round-trip, byte-identical;
- `list` on a missing directory, and after `mkdir`, `write`, `delete`, `rename`;
- `rename` over an existing target;
- `mkdir` of nested paths;
- `flush` returns only after data is durable;
- path handling stays card-relative and rejects traversal outside the root.

Plus card detection: a fixture root with both markers is found; a root missing
either is not a candidate; two candidate roots refuse; zero candidates refuse.

## Done when

The single conformance suite passes against both implementations and the four
card-detection cases each have a test.
