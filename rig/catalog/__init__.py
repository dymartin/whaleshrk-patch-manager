"""Module catalog: ingest, validation gate, and `.rig/catalog/` I/O.

See docs/catalog.md for what this package guarantees. This is the surface
`rig.cli` builds on, the same way it consumes `rig.push`/`rig.pull`/`rig.song`
-- everything a command needs to read, write, gate or refresh the catalog,
without naming a submodule. Library code inside `rig/` still imports the
submodule it needs directly.
"""

from .archive import CandidateArchive, ZipCandidateArchive
from .builtins import ingest_pinned_builtins
from .discovery import find_sources_by_slug, live_httpx_client
from .entry import CatalogEntry, ParamSpec, VersionInfo
from .gate import GateAccept, GateReject, RejectReason, gate_candidate
from .ingest import (
    CandidateSource,
    CatalogBuildResult,
    IngestReject,
    KeyCollisionError,
    build_catalog,
    build_community_catalog,
)
from .io import read_catalog, read_lock, write_catalog, write_lock
from .patchstorage import (
    PatchstorageError,
    discover_union,
    fetch_archive_bytes,
    fetch_detail,
)
from .slugs import module_key
from .store import (
    ARCHIVE_SIZE_WARN_BYTES,
    ArchiveStoreError,
    archive_filename,
    archive_path,
    read_archive,
    write_archive,
)

__all__ = [
    "CandidateArchive",
    "ZipCandidateArchive",
    "ingest_pinned_builtins",
    "find_sources_by_slug",
    "live_httpx_client",
    "CatalogEntry",
    "ParamSpec",
    "VersionInfo",
    "GateAccept",
    "GateReject",
    "RejectReason",
    "gate_candidate",
    "CandidateSource",
    "CatalogBuildResult",
    "IngestReject",
    "KeyCollisionError",
    "build_catalog",
    "build_community_catalog",
    "read_catalog",
    "read_lock",
    "write_catalog",
    "write_lock",
    "PatchstorageError",
    "discover_union",
    "fetch_archive_bytes",
    "fetch_detail",
    "module_key",
    "ARCHIVE_SIZE_WARN_BYTES",
    "ArchiveStoreError",
    "archive_filename",
    "archive_path",
    "read_archive",
    "write_archive",
]
