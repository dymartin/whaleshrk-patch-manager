"""Loads Task 0's frozen catalog fixture into ingest-ready `CandidateSource`s.

This is the offline replay path: CI regenerates the catalog from here and
fails on diff (docs/catalog.md "Outputs"), and it is what proves the ingest
pipeline reproduces the measured counts without ever touching the network.
"""

from __future__ import annotations

import json
from pathlib import Path

from .archive import FrozenCandidateArchive
from .ingest import CandidateSource

FIXTURE_CATALOG_ROOT = Path(__file__).resolve().parent.parent.parent / "fixtures" / "catalog"


def union_ids(root: Path = FIXTURE_CATALOG_ROOT) -> list[int]:
    return json.loads((root / "union_ids.json").read_text(encoding="utf-8"))


def load_frozen_sources(root: Path = FIXTURE_CATALOG_ROOT) -> list[CandidateSource]:
    """One `CandidateSource` per frozen candidate, in ascending id order.

    Skips candidates whose archive download failed at fixture-build time
    (`archive.json` carrying an "error" key) -- there is no content to gate.
    """
    sources = []
    for pid in sorted(union_ids(root)):
        candidate_dir = root / "candidates" / str(pid)
        archive_record = json.loads((candidate_dir / "archive.json").read_text(encoding="utf-8"))
        if "error" in archive_record:
            continue
        detail = json.loads((root / "detail" / f"{pid}.json").read_text(encoding="utf-8"))
        sources.append(
            CandidateSource(
                id=pid,
                archive=FrozenCandidateArchive(candidate_dir),
                detail=detail,
                archive_sha256=archive_record["archive_sha256"],
            )
        )
    return sources
