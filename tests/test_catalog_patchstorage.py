"""Live Patchstorage client -- exercised entirely offline via httpx.MockTransport.

`MockTransport` is part of httpx itself (already a sanctioned dependency):
it intercepts requests inside the same process and never touches
`socket.socket`, so this stays compatible with tests/conftest.py's
whole-session network block while still exercising the real client code
against realistic responses -- see docs/platform/patchstorage.md.
"""

from __future__ import annotations

import httpx
import pytest

from rig.catalog.patchstorage import (
    PatchstorageError,
    discover_union,
    fetch_archive_bytes,
    fetch_detail,
    list_patches,
)


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_list_patches_single_page():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["platforms"] == "3371"
        page = int(request.url.params["page"])
        items = [{"id": 1}, {"id": 2}] if page == 1 else []
        return httpx.Response(
            200, headers={"X-WP-Total": "2", "X-WP-TotalPages": "1"}, json=items
        )

    with _client(handler) as client:
        items = list_patches(client, platform=3371)
    assert [i["id"] for i in items] == [1, 2]


def test_list_patches_paginates_until_empty_page():
    pages = {1: [{"id": 1}, {"id": 2}], 2: [{"id": 3}]}

    def handler(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params["page"])
        items = pages.get(page, [])
        return httpx.Response(200, headers={"X-WP-Total": "3"}, json=items)

    with _client(handler) as client:
        items = list_patches(client, tag=1483)
    assert [i["id"] for i in items] == [1, 2, 3]


def test_list_patches_raises_when_total_header_missing():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[{"id": 1}])

    with _client(handler) as client, pytest.raises(PatchstorageError):
        list_patches(client, platform=3371)


def test_list_patches_raises_on_count_mismatch():
    # Catches exactly the bug docs/platform/patchstorage.md warns about:
    # a filter silently doing nothing must be caught by a count assertion.
    # X-WP-Total claims 9999 but only one item is ever actually returned.
    def handler(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params["page"])
        items = [{"id": 1}] if page == 1 else []
        return httpx.Response(200, headers={"X-WP-Total": "9999"}, json=items)

    with _client(handler) as client, pytest.raises(PatchstorageError):
        list_patches(client, platform=3371)


def test_list_patches_stops_and_raises_if_pages_never_empty_out():
    # A misbehaving API that keeps returning non-empty pages forever must
    # not hang the client -- it stops once it has strictly more items than
    # X-WP-Total claimed, and reports the mismatch instead of looping.
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"X-WP-Total": "1"}, json=[{"id": 1}])

    with _client(handler) as client, pytest.raises(PatchstorageError):
        list_patches(client, platform=3371)


def test_discover_union_dedupes_across_platform_and_tag():
    def handler(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params["page"])
        if page > 1:
            return httpx.Response(200, headers={"X-WP-Total": "2"}, json=[])
        if "platforms" in request.url.params:
            items = [{"id": 1}, {"id": 2}]
        else:
            items = [{"id": 2}, {"id": 3}]
        return httpx.Response(200, headers={"X-WP-Total": "2"}, json=items)

    with _client(handler) as client:
        ids = discover_union(client)
    assert ids == [1, 2, 3]


def test_fetch_detail_validates_returned_id():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": 999, "slug": "wrong-one"})

    with _client(handler) as client, pytest.raises(PatchstorageError):
        fetch_detail(client, 123)


def test_fetch_detail_returns_matching_payload():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": 123, "slug": "a-patch"})

    with _client(handler) as client:
        detail = fetch_detail(client, 123)
    assert detail["slug"] == "a-patch"


def test_fetch_archive_bytes_returns_body():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"PK\x03\x04fake-zip-bytes")

    with _client(handler) as client:
        data = fetch_archive_bytes(client, "https://patchstorage.com/fake.zop")
    assert data == b"PK\x03\x04fake-zip-bytes"
