"""Catalog JSON I/O.

`CatalogEntry.version` already carries every field a module needs pinned
(updated_at, file_id, archive_sha256, revision) -- a catalog entry *is* the
pin, for both built-ins and community modules. There is no second file.
"""

from __future__ import annotations

import json
from pathlib import Path

from rig.atomicio import write_text_atomic

from .entry import CatalogEntry


def write_catalog(entries: list[CatalogEntry], path: Path) -> None:
    write_text_atomic(path, json.dumps([e.to_dict() for e in entries], indent=2, sort_keys=True) + "\n")


def read_catalog(path: Path) -> list[CatalogEntry]:
    if not path.exists():
        return []
    return [CatalogEntry.from_dict(data) for data in json.loads(path.read_text(encoding="utf-8"))]
