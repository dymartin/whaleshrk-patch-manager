"""Catalog and module-lock JSON I/O."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from rig.atomicio import write_text_atomic

from .entry import CatalogEntry

GENERATOR = "rig catalog"
LOCK_SCHEMA_VERSION = 2


def write_catalog(entries: list[CatalogEntry], path: Path) -> None:
    write_text_atomic(path, json.dumps([e.to_dict() for e in entries], indent=2, sort_keys=True) + "\n")


def read_catalog(path: Path) -> list[CatalogEntry]:
    if not path.exists():
        return []
    return [CatalogEntry.from_dict(data) for data in json.loads(path.read_text(encoding="utf-8"))]


def write_lock(entries: list[CatalogEntry], lock_path: Path) -> None:
    """Pin every community module's version, content hash and stored archive.

    Built-ins are not recorded here; their version is pinned by ORHACK itself.

    `source` and `revision` together name the archive in `modules/`, and
    `archive_sha256` is what verifies it on every read
    (`rig.catalog.store`).
    """
    modules = {}
    for entry in entries:
        if entry.source == "orhack":
            continue
        modules[entry.key] = {
            "source": entry.source,
            "updated_at": entry.version.updated_at,
            "file_id": entry.version.file_id,
            "archive_sha256": entry.version.archive_sha256,
            "revision": entry.version.revision,
        }
    lock = {
        "schema_version": LOCK_SCHEMA_VERSION,
        "generator": GENERATOR,
        "modules": modules,
    }
    write_text_atomic(lock_path, json.dumps(lock, indent=2, sort_keys=True) + "\n")


def read_lock(lock_path: Path) -> dict[str, Any]:
    if not lock_path.exists():
        return {"schema_version": LOCK_SCHEMA_VERSION, "generator": GENERATOR, "modules": {}}
    return json.loads(lock_path.read_text(encoding="utf-8"))
