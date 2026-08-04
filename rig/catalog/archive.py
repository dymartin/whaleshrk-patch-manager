"""Candidate archive access, backed by either a real zip or the frozen fixture.

The gate (rig/catalog/gate.py) is written against the `CandidateArchive`
protocol only, so the same gate logic runs identically against a live-
downloaded zip (`ZipCandidateArchive`) and against Task 0's frozen,
pre-extracted fixture (`FrozenCandidateArchive`) -- required so CI can
replay the frozen fixture and fail on diff without ever touching the
network (docs/catalog.md "Outputs").
"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
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


class FrozenCandidateArchive:
    """Backed by Task 0's frozen fixture: entries.json plus the trimmed extracted/ tree.

    `read`/`read_header` only serve what Task 0 captured -- module.json,
    every .pd file, and the first 64 bytes of every ELF-magic file. Anything
    else raises FileNotFoundError, matching what a real offline replay can
    know.
    """

    def __init__(self, candidate_dir: Path) -> None:
        self._dir = candidate_dir
        self._extracted = candidate_dir / "extracted"
        self._entries: list[ArchiveEntry] | None = None

    def entries(self) -> list[ArchiveEntry]:
        if self._entries is None:
            raw = json.loads((self._dir / "entries.json").read_text(encoding="utf-8"))
            self._entries = [
                ArchiveEntry(
                    name=e["name"],
                    size=e["size"],
                    compress_size=e["compress_size"],
                    external_attr=e["external_attr"],
                    is_dir=e["is_dir"],
                )
                for e in raw
            ]
        return self._entries

    def _extracted_path(self, name: str) -> Path:
        return self._extracted / name

    def read(self, name: str) -> bytes:
        path = self._extracted_path(name)
        if not path.is_file():
            raise FileNotFoundError(name)
        return path.read_bytes()

    def read_header(self, name: str, n: int = 64) -> bytes:
        return self.read(name)[:n]

    def extracted_files(self) -> list[str]:
        """Every path Task 0 captured, relative to the archive root."""
        if not self._extracted.exists():
            return []
        return [
            str(p.relative_to(self._extracted).as_posix())
            for p in self._extracted.rglob("*")
            if p.is_file()
        ]
