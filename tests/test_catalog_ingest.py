"""`build_catalog` composition: built-ins plus whatever community uploads the
repo has actually added.

The catalog is a shopping list, not a mirror of Patchstorage (docs/catalog.md),
so there is no fixed entry count to assert. What must hold for any shopping
list is tested here: built-ins always present, community entries keyed without
collision, and no community module shadowing a built-in's runtime path.
"""

from __future__ import annotations

from rig.catalog.archive import ZipCandidateArchive
from rig.catalog.builtins import ingest_pinned_builtins
from rig.catalog.gate import RejectReason
from rig.catalog.ingest import CandidateSource, build_catalog

from .catalog_helpers import build_zip

BUILTIN_COUNT = 65


def _module(display: str) -> dict[str, bytes]:
    return {
        "module.json": f'{{"display": "{display}", "parameters": []}}'.encode("utf-8"),
        "module.pd": b"#N canvas 0 0 100 100 10;\n",
    }


def _source(slug: str, files: dict[str, bytes], patch_id: int = 1) -> CandidateSource:
    return CandidateSource(
        id=patch_id,
        archive=ZipCandidateArchive(build_zip(files)),
        detail={
            "slug": slug,
            "updated_at": "2020-01-01",
            "revision": "1.0",
            "categories": [{"slug": "effect"}],
        },
        archive_sha256=f"sha-{slug}",
    )


def test_built_ins_are_always_present_with_no_community_modules():
    result = build_catalog(ingest_pinned_builtins(), [])
    assert len(result.entries) == BUILTIN_COUNT
    assert {e.source for e in result.entries} == {"orhack"}


def test_an_added_upload_contributes_its_modules():
    result = build_catalog(ingest_pinned_builtins(), [_source("warble", _module("Warble"))])
    community = [e for e in result.entries if e.source != "orhack"]
    assert [e.key for e in community] == ["warble@warble"]
    assert result.rejects == []


def test_a_multi_module_upload_contributes_one_entry_per_module():
    files = {f"{name}/{k}": v for name in ("one", "two") for k, v in _module(name.title()).items()}
    result = build_catalog(ingest_pinned_builtins(), [_source("pack", files)])
    community = sorted(e.key for e in result.entries if e.source != "orhack")
    assert community == ["one@pack", "two@pack"]


def test_keys_stay_unique_when_two_uploads_ship_the_same_display_name():
    # The key is slug(display)@upload-slug precisely so this is not a
    # collision (docs/catalog.md "Keys").
    result = build_catalog(
        ingest_pinned_builtins(),
        [_source("first", _module("Warble"), 1), _source("second", _module("Warble"), 2)],
    )
    keys = [e.key for e in result.entries]
    assert len(keys) == len(set(keys))
    assert {"warble@first", "warble@second"} <= set(keys)


def test_no_community_module_shadows_a_built_in_runtime_path():
    result = build_catalog(ingest_pinned_builtins(), [_source("warble", _module("Warble"))])
    builtin_paths = {e.module_type for e in result.entries if e.source == "orhack"}
    community_paths = {e.module_type for e in result.entries if e.source != "orhack"}
    assert builtin_paths & community_paths == set()


def test_an_upload_that_is_not_a_module_is_rejected_not_ingested():
    result = build_catalog(ingest_pinned_builtins(), [_source("notamodule", {"readme.txt": b"hello"})])
    assert [e.source for e in result.entries] == ["orhack"] * BUILTIN_COUNT
    assert [r.reason for r in result.rejects] == [RejectReason.NOT_A_MODULE]
