"""Writing `.rig/catalog/` and `.rig/modules.lock` to the repo working tree.

Both live in the git repo, not on the card -- plain filesystem I/O, not the
Transport abstraction (docs/repo-layout.md).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from rig.atomicio import write_text_atomic

from .entry import CatalogEntry, entry_filename

GENERATOR = "rig catalog update"
LOCK_SCHEMA_VERSION = 1


def write_catalog(entries: list[CatalogEntry], catalog_dir: Path) -> None:
    """Overwrite `catalog_dir` with exactly the given entries -- no stale leftovers."""
    catalog_dir.mkdir(parents=True, exist_ok=True)
    for existing in catalog_dir.glob("*.json"):
        existing.unlink()
    for entry in entries:
        path = catalog_dir / entry_filename(entry.key)
        write_text_atomic(path, json.dumps(entry.to_dict(), indent=2, sort_keys=True) + "\n")


def read_catalog(catalog_dir: Path) -> list[CatalogEntry]:
    if not catalog_dir.exists():
        return []
    entries = []
    for path in sorted(catalog_dir.glob("*.json")):
        entries.append(CatalogEntry.from_dict(json.loads(path.read_text(encoding="utf-8"))))
    return entries


def write_lock(entries: list[CatalogEntry], lock_path: Path) -> None:
    """Pin every community module's version and content hash.

    Built-ins are not recorded here -- their version is pinned by ORHACK's
    own build, not by this tool (docs/catalog.md "Versioning").
    """
    modules = {}
    for entry in entries:
        if entry.source == "orhack":
            continue
        modules[entry.key] = {
            "updated_at": entry.version.updated_at,
            "file_id": entry.version.file_id,
            "archive_sha256": entry.version.archive_sha256,
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
