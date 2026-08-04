"""Frozen catalog fixture replays offline (Phase 0 verification #3).

Phase 1 builds the ingest gate against this data; Phase 0 only has to prove
the freeze is complete and self-consistent -- every candidate the list
endpoints named has a detail response and an archive record, and the trimmed
extraction actually captured module.json/.pd content, with the network never
touched. See docs/decisions.md #42 and Prompt/01-catalog.md "Validation gate".
"""

import json
from pathlib import Path

CATALOG_ROOT = Path(__file__).resolve().parent.parent / "fixtures" / "catalog"


def _union_ids() -> list[int]:
    return json.loads((CATALOG_ROOT / "union_ids.json").read_text())


def test_union_of_platform_and_tag_is_145_candidates():
    ids = _union_ids()
    assert len(ids) == len(set(ids))
    # Measured count per docs/catalog.md; Prompt/00-skeleton.md says report,
    # never silently adjust, if a re-fetch ever produces a different number.
    assert len(ids) == 145


def test_list_pages_cover_the_union():
    platform_ids = set()
    for page in sorted(CATALOG_ROOT.glob("list/platforms-3371-page-*.json")):
        platform_ids |= {item["id"] for item in json.loads(page.read_text())}
    tag_ids = set()
    for page in sorted(CATALOG_ROOT.glob("list/tags-1483-page-*.json")):
        tag_ids |= {item["id"] for item in json.loads(page.read_text())}
    assert (platform_ids | tag_ids) == set(_union_ids())


def test_every_candidate_has_a_detail_response():
    for pid in _union_ids():
        detail_path = CATALOG_ROOT / "detail" / f"{pid}.json"
        assert detail_path.exists(), f"missing detail response for {pid}"
        detail = json.loads(detail_path.read_text(encoding="utf-8"))
        assert detail["id"] == pid


def test_every_candidate_has_an_archive_record_with_verified_hash():
    for pid in _union_ids():
        archive_path = CATALOG_ROOT / "candidates" / str(pid) / "archive.json"
        assert archive_path.exists(), f"missing archive record for {pid}"
        record = json.loads(archive_path.read_text())
        assert record["id"] == pid
        assert "error" not in record, f"{pid}: {record.get('error')}"
        assert len(record["archive_sha256"]) == 64
        assert record["archive_size"] > 0


def test_every_candidate_has_a_zip_entry_listing():
    for pid in _union_ids():
        entries_path = CATALOG_ROOT / "candidates" / str(pid) / "entries.json"
        assert entries_path.exists(), f"missing entry listing for {pid}"
        entries = json.loads(entries_path.read_text())
        assert isinstance(entries, list)
        assert len(entries) > 0


def test_trimmed_extraction_captured_module_json_or_pd_files():
    # Not every candidate passes the gate (14 of 145 are mistagged plain
    # patches with no module.json/.pd at all -- see Prompt/01-catalog.md), so
    # this checks the fixture as a whole extracted real content, not that
    # every single candidate did.
    total_module_json = 0
    total_pd = 0
    for pid in _union_ids():
        extracted = CATALOG_ROOT / "candidates" / str(pid) / "extracted"
        if not extracted.exists():
            continue
        for p in extracted.rglob("*"):
            if not p.is_file():
                continue
            if p.name == "module.json":
                total_module_json += 1
            elif p.suffix.lower() == ".pd":
                total_pd += 1
    assert total_module_json > 50
    assert total_pd > 50
