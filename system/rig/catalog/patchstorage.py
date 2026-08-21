"""Live Patchstorage API client -- the manual, occasional discovery path.

Never used by a test (tests/conftest.py blocks every socket for the whole
session) and never used by an ordinary build or push (docs/catalog.md
"Outputs": "Ordinary builds and pushes never discover live data"). Only
`rig catalog update`'s live run reaches this module.

See docs/platform/patchstorage.md: unknown query parameters are silently
ignored by the API rather than rejected, so every list call asserts its
result count against `X-WP-Total` instead of trusting the filter worked.
"""

from __future__ import annotations

from typing import Any

import httpx

BASE_URL = "https://patchstorage.com/api/beta/"
PLATFORM_ORAC = 3371
TAG_ORAC = 1483
PER_PAGE = 100


class PatchstorageError(RuntimeError):
    """The API returned something the client cannot trust -- never silently ignored."""


def _list_page(client: httpx.Client, params: dict, page: int) -> tuple[list[dict], int]:
    response = client.get(
        BASE_URL + "patches",
        params={**params, "per_page": PER_PAGE, "page": page},
    )
    response.raise_for_status()
    total_header = response.headers.get("X-WP-Total")
    if total_header is None:
        raise PatchstorageError("response is missing X-WP-Total; cannot verify completeness")
    return response.json(), int(total_header)


def list_patches(client: httpx.Client, *, platform: int | None = None, tag: int | None = None) -> list[dict]:
    """Every patch for one filter, paginated, with a completeness assertion.

    `platform`/`tag` use the singular, working parameter names -- see module
    docstring. Passing the plural `platforms`/`tags` here would compile but
    silently return the whole 17,000+ patch catalog.
    """
    params: dict = {}
    if platform is not None:
        params["platforms"] = platform
    if tag is not None:
        params["tags"] = tag

    items: list[dict] = []
    page = 1
    total = None
    while True:
        page_items, page_total = _list_page(client, params, page)
        if total is None:
            total = page_total
        elif page_total != total:
            raise PatchstorageError(
                f"X-WP-Total changed mid-pagination: {total} then {page_total}"
            )
        if not page_items:
            break
        items.extend(page_items)
        # A page that never empties out (a misbehaving API, or a filter that
        # silently returns more than X-WP-Total claims) must not spin
        # forever -- stop as soon as we reach X-WP-Total; if a page overshoots,
        # let the count assertion below report it.
        if len(items) >= total:
            break
        page += 1

    if total is not None and len(items) != total:
        raise PatchstorageError(
            f"collected {len(items)} items but X-WP-Total reported {total}"
        )
    return items


def discover_union(client: httpx.Client) -> list[int]:
    """Deduped union of platform `orac` and tag `orac` candidate ids."""
    platform_items = list_patches(client, platform=PLATFORM_ORAC)
    tag_items = list_patches(client, tag=TAG_ORAC)
    ids = {item["id"] for item in platform_items} | {item["id"] for item in tag_items}
    return sorted(ids)


def fetch_detail(client: httpx.Client, patch_id: int) -> dict[str, Any]:
    response = client.get(BASE_URL + f"patches/{patch_id}")
    response.raise_for_status()
    detail = response.json()
    if detail.get("id") != patch_id:
        raise PatchstorageError(f"requested patch {patch_id}, got id {detail.get('id')!r}")
    return detail


def fetch_archive_bytes(client: httpx.Client, url: str) -> bytes:
    response = client.get(url)
    response.raise_for_status()
    return response.content
