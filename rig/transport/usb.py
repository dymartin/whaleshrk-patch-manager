"""Filesystem-backed Transport for a card mounted as a USB mass storage volume.

`root` is the mount point; every path passed to the interface is
card-relative ("data/orhack/rack.json"), never an absolute filesystem path --
see docs/transport.md. Behaviour matches `InMemoryTransport` (error types,
path validation, "missing directory lists empty") so the same conformance
suite can run against both.

Writes go through the host OS's ordinary buffered file I/O -- nothing here
imposes extra buffering. `mount.sh` mounts the card with `-o async,noatime`,
so on-device durability depends entirely on `flush()` actually forcing
buffered data out; see `flush` below for what that does and does not
guarantee.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from .base import TransportPathError, normalize_path


class UsbMassStorage:
    """Transport backed by a real directory tree -- the card's mount point.

    Tracks every path written since the last `flush()` and fsyncs exactly
    those files on flush, rather than fsyncing on every write -- this
    mirrors the "buffered until flushed" model `docs/platform/card.md`
    describes for the card's own mount options.
    """

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root).resolve()
        if not self._root.is_dir():
            raise TransportPathError(f"card root {str(root)!r} is not a directory")
        self._dirty: set[Path] = set()

    def _resolve(self, path: str) -> tuple[str, Path]:
        rel = normalize_path(path)
        return rel, self._root.joinpath(*rel.split("/"))

    def _check_ancestors_not_files(self, rel: str) -> None:
        """Refuse instead of corrupting the tree if a path component up to
        the target is already a file -- the filesystem would otherwise raise
        an OS-specific error (NotADirectoryError, PermissionError, ...)
        instead of the shared TransportPathError callers expect."""
        node = self._root
        for part in rel.split("/")[:-1]:
            node = node / part
            if node.is_file():
                raise TransportPathError(
                    f"{rel!r} passes through {node.relative_to(self._root).as_posix()!r}, "
                    "which is a file"
                )

    def exists(self, path: str) -> bool:
        _, p = self._resolve(path)
        return p.exists()

    def list(self, path: str) -> list[str]:
        rel = normalize_path(path) if path else ""
        p = self._root.joinpath(*rel.split("/")) if rel else self._root
        if not p.is_dir():
            return []
        return sorted(entry.name for entry in p.iterdir())

    def read(self, path: str) -> bytes:
        _, p = self._resolve(path)
        if not p.is_file():
            raise FileNotFoundError(path)
        return p.read_bytes()

    def write(self, path: str, data: bytes) -> None:
        rel, p = self._resolve(path)
        if p.is_dir():
            raise TransportPathError(f"{rel!r} is a directory")
        self._check_ancestors_not_files(rel)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        self._dirty.add(p)

    def delete(self, path: str) -> None:
        _, p = self._resolve(path)
        if p.is_file():
            p.unlink()
            self._dirty.discard(p)
            return
        if p.is_dir():
            shutil.rmtree(p)
            self._dirty = {d for d in self._dirty if p != d and p not in d.parents}
            return
        raise FileNotFoundError(path)

    def mkdir(self, path: str) -> None:
        rel, p = self._resolve(path)
        if p.is_file():
            raise TransportPathError(f"{rel!r} is a file")
        self._check_ancestors_not_files(rel)
        p.mkdir(parents=True, exist_ok=True)

    def rename(self, source: str, target: str) -> None:
        src_rel, src = self._resolve(source)
        tgt_rel, tgt = self._resolve(target)
        if not src.exists():
            raise FileNotFoundError(source)
        if tgt.is_file():
            tgt.unlink()
        elif tgt.is_dir():
            shutil.rmtree(tgt)
        else:
            self._check_ancestors_not_files(tgt_rel)
        tgt.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(tgt))

        moved = set()
        for d in self._dirty:
            if d == src:
                moved.add(tgt)
            elif src in d.parents:
                moved.add(tgt / d.relative_to(src))
        self._dirty = {d for d in self._dirty if d != src and src not in d.parents}
        self._dirty |= moved

    def flush(self) -> None:
        """Fsync every file written since the last flush.

        `os.fsync` maps to `FlushFileBuffers` on Windows and to `fsync(2)` on
        POSIX -- both are documented to force a file's buffered writes
        through to the storage device, which is what makes this a real
        flush rather than a no-op. Two things it cannot do, verified against
        no more than the Win32/POSIX contract (there is no hardware feedback
        channel to check further, per Prompt/04-transport.md's global
        constraints):

        - It flushes file *data*, not directory *metadata* -- a `mkdir`,
          `delete` or `rename` with no accompanying `write` is not covered.
          Portable Python has no directory-handle fsync on Windows.
        - It cannot see or flush any write cache internal to the USB
          card's own controller firmware; the host OS has no visibility
          into that. This is why the operator guidance stays "eject, don't
          yank" even after a successful flush.
        """
        for p in list(self._dirty):
            try:
                fd = os.open(str(p), os.O_RDWR)
            except FileNotFoundError:
                self._dirty.discard(p)
                continue
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
            self._dirty.discard(p)
