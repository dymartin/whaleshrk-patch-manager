"""Candidate archive access.

The gate (rig/catalog/gate.py) is written against the `CandidateArchive`
protocol so it can run over an archive freshly downloaded by `rig catalog
add` and over one already committed to `modules/` -- the same bytes either
way, since the store keeps uploads unmodified (docs/catalog.md).
"""

from __future__ import annotations

import io
import zipfile
from typing import Protocol, runtime_checkable

from .safety import ArchiveEntry


@runtime_checkable
class CandidateArchive(Protocol):
    """Read-only view of one candidate's zip contents."""

    def entries(self) -> list[ArchiveEntry]:
        """Every entry in the archive, safe to inspect before extracting anything."""
        ...

    def read(self, name: str) -> bytes:
        """Full content of one entry. Raises FileNotFoundError if unavailable."""
        ...

    def read_header(self, name: str, n: int = 64) -> bytes:
        """First `n` bytes of one entry -- all the ELF ABI check needs."""
        ...


class ZipCandidateArchive:
    """Backed by real zip bytes -- the live ingest path and synthetic test fixtures."""

    def __init__(self, data: bytes) -> None:
        self._zf = zipfile.ZipFile(io.BytesIO(data))
        # Kept so the exact upload bytes can be committed to `modules/`
        # unchanged -- a re-zip would not match the digest Patchstorage
        # published (rig.catalog.store).
        self.data = data

    def entries(self) -> list[ArchiveEntry]:
        result = []
        for info in self._zf.infolist():
            is_dir = info.is_dir()
            result.append(
                ArchiveEntry(
                    name=info.filename,
                    size=info.file_size,
                    compress_size=info.compress_size,
                    external_attr=info.external_attr,
                    is_dir=is_dir,
                )
            )
        return result

    def read(self, name: str) -> bytes:
        try:
            return self._zf.read(name)
        except KeyError as exc:
            raise FileNotFoundError(name) from exc

    def read_header(self, name: str, n: int = 64) -> bytes:
        try:
            with self._zf.open(name) as f:
                return f.read(n)
        except KeyError as exc:
            raise FileNotFoundError(name) from exc


