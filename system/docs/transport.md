# Transport Layer

Pluggable; SSH is the default for push and pull. USB mass storage is an explicit
fallback via `--transport usb`.

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

- **`SshTransport(host="organelle", root="/sdcard")`** — the default. Uses the
  system OpenSSH client with `BatchMode=yes`; host aliases, keys and host-key
  verification remain in the operator's SSH config. `flush()` runs remote
  `sync` before a transaction advances.
- **`UsbMassStorage(root)`** — explicit fallback when the card is mounted as a filesystem. Paths are
  card-relative: `data/orhack/rack.json`, not an absolute mount path. `root`
  must already exist (the caller resolves the mount point first — see "Card
  identification"). Tracks every path written since the last `flush()` and
  fsyncs exactly those files, rather than fsyncing on every write.
- **`InMemoryTransport`** — tests sync and mirroring without a card. Both
  implementations pass one shared conformance suite
  (`tests/test_transport_conformance.py`); backend-specific behaviour lives
  in its own test file.

### `flush()` platform limits

`flush()` calls `os.fsync` on every file this transport instance has
written since the last flush — `os.fsync` maps to `FlushFileBuffers` on
Windows and `fsync(2)` on POSIX, both documented to force that file's
buffered data through to the storage device. Two things it does not cover,
stated plainly because they are real gaps, not oversights:

- **Directory metadata.** A `mkdir`, `delete`, or `rename` with no
  accompanying `write` is not fsynced — Windows has no portable way to open
  a directory handle for `fsync`, so this transport does not attempt it on
  any platform, for the same behaviour on both.
- **The card's own controller cache.** The host OS has no visibility into
  a USB device's internal write cache. `flush()` empties what the *host*
  is buffering; whether the drive's firmware has also written it through is
  outside what any host-side call can observe. This is why the operator
  guidance stays "eject, don't yank" even after a successful flush — eject
  is the OS-level signal that also waits on the device's own completion.

The development machine for this project is Windows, where `-o
async,noatime` (a Linux mount option) does not apply literally; Windows'
own removable-drive write-caching policy is a separate, per-device,
OS-configurable setting this tool does not inspect. `flush()`'s guarantee
is therefore stated in terms of what `os.fsync` itself promises, not in
terms of any specific mount option.

## Card identification

Structural removable-volume detection applies only to `--transport usb`. SSH
uses the configured host alias and fixed `/sdcard` root; normal ORHACK
verification still refuses before mutation if the remote tree is not the card.

By structure, not drive letter or label: a candidate root must contain
`data/orhack/` and `Patches/0RHACK/`. Refuse rather than guess on zero or
multiple candidates — writing a mirror-with-deletions to the wrong volume is
unrecoverable.

`rig.transport.card.resolve_card(roots=None)` implements this: it filters
`roots` (default `list_mounted_roots()`, a best-effort OS-specific scan — real
removable drives on Windows via `GetDriveTypeW`, conventional auto-mount
parents on POSIX) down to candidates via `is_card_root`, and returns a
`UsbMassStorage` for the single match. Zero or multiple candidates raise
`CardDetectionError` with a distinct `code` (`NO_CARD_FOUND` /
`MULTIPLE_CARDS_FOUND`) and message per case. `list_mounted_roots()` is
unverified against real hardware — no removable drive is attached in the
development environment — so callers needing certainty pass an explicit
`roots` list instead of relying on the default scan.

## Paths

The transport works in card-relative paths. The `/tmp/...` paths throughout
ORHACK's Pure Data source are runtime symlinks created by the Organelle
firmware and never exist on the card — see [platform/state.md](platform/state.md).
