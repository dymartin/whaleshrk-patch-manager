"""Finding a specific live Patchstorage upload again, after ingest.

`rig catalog update` walks the whole discovery list once and keeps what it
finds. Everything afterwards -- `rig push` installing a locked module, `rig
upgrade` refreshing one -- starts from a catalog entry and has to locate that
upload's *current* candidate id, which the API cannot be asked directly.
See `find_sources_by_slug` for why that costs a full walk.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable

import httpx

from .archive import ZipCandidateArchive
from .ingest import CandidateSource
from .patchstorage import discover_union, fetch_archive_bytes, fetch_detail


def live_httpx_client() -> httpx.Client:
    return httpx.Client(headers={"User-Agent": "whaleshrk-rig/0.1"}, timeout=30.0)


def discover_sources(
    client: httpx.Client, patch_ids: Iterable[int] | None = None
) -> dict[str, CandidateSource]:
    """Download every ORAC platform/tag upload, keyed by its stable slug."""
    found: dict[str, CandidateSource] = {}
    for patch_id in discover_union(client) if patch_ids is None else patch_ids:
        detail = fetch_detail(client, patch_id)
        files = detail.get("files") or []
        if not files:
            continue
        archive_bytes = fetch_archive_bytes(client, files[0]["url"])
        slug = detail["slug"]
        found[slug] = CandidateSource(
            id=patch_id,
            archive=ZipCandidateArchive(archive_bytes),
            detail=detail,
            archive_sha256=hashlib.sha256(archive_bytes).hexdigest(),
        )
    return found


def find_sources_by_slug(client: httpx.Client, wanted_slugs: set[str]) -> dict[str, CandidateSource]:
    """Every live Patchstorage candidate whose upload slug is in
    `wanted_slugs`, fully fetched (detail + archive bytes).

    Patchstorage's API (docs/platform/patchstorage.md) has no lookup-by-slug
    filter -- only platform, tag, category, author and a fuzzy `search`, none
    an exact identifier match -- so finding one upload's current candidate id
    means walking the same full discovery list `rig catalog update` already
    walks. Stops early once every wanted slug is found.
    """
    if not wanted_slugs:
        return {}
    found: dict[str, CandidateSource] = {}
    ids = discover_union(client)
    for patch_id in ids:
        if len(found) == len(wanted_slugs):
            break
        detail = fetch_detail(client, patch_id)
        detail_slug = detail.get("slug")
        if detail_slug not in wanted_slugs or detail_slug in found:
            continue
        files = detail.get("files") or []
        if not files:
            continue
        archive_bytes = fetch_archive_bytes(client, files[0]["url"])
        found[detail_slug] = CandidateSource(
            id=patch_id,
            archive=ZipCandidateArchive(archive_bytes),
            detail=detail,
            archive_sha256=hashlib.sha256(archive_bytes).hexdigest(),
        )
    return found
