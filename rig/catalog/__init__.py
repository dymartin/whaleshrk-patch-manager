"""Module catalog: ingest, validation gate, and `.rig/catalog/` I/O.

See docs/catalog.md for what this package guarantees.
"""

from .entry import CatalogEntry, ParamSpec, VersionInfo
from .gate import GateAccept, GateReject, RejectReason, gate_candidate
from .ingest import (
    CandidateSource,
    CatalogBuildResult,
    IngestReject,
    KeyCollisionError,
    build_catalog,
)

__all__ = [
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
]
