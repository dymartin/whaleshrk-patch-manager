"""Module catalog ingestion, validation, storage, and discovery."""

from .archive import CandidateArchive, ZipCandidateArchive
from .builtins import ingest_pinned_builtins
from .discovery import discover_sources, find_sources_by_slug, live_httpx_client
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
    discover_union_items,
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
    read_archive,
    write_archive,
)
