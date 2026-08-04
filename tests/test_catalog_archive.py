"""CandidateArchive implementations -- both must satisfy the same gate logic.

ZipCandidateArchive is exercised here with a synthetic, offline-built zip
(the live-ingest path is otherwise untestable without network).
FrozenCandidateArchive is exercised against one real fixture candidate.
"""

from __future__ import annotations

from pathlib import Path

from rig.catalog.archive import FrozenCandidateArchive, ZipCandidateArchive

from .catalog_helpers import MODULE_JSON, MODULE_PD, build_zip, elf32_header

FIXTURE_CATALOG_ROOT = Path(__file__).resolve().parent.parent / "fixtures" / "catalog"


def test_zip_candidate_archive_round_trips_entries_and_content():
    data = build_zip(
        {
            "mymod/module.json": MODULE_JSON,
            "mymod/module.pd": MODULE_PD,
            "mymod/ext.pd_linux": elf32_header(),
        }
    )
    archive = ZipCandidateArchive(data)
    names = {e.name for e in archive.entries()}
    assert "mymod/module.json" in names
    assert archive.read("mymod/module.json") == MODULE_JSON
    assert archive.read_header("mymod/ext.pd_linux", 64) == elf32_header()


def test_zip_candidate_archive_missing_file_raises():
    data = build_zip({"mymod/module.json": MODULE_JSON})
    archive = ZipCandidateArchive(data)
    try:
        archive.read("does/not/exist")
        assert False, "expected FileNotFoundError"
    except FileNotFoundError:
        pass


def test_frozen_candidate_archive_reads_real_fixture_candidate():
    # 105149 = "orac-2-0-for-organelle", a real rack redistribution with a
    # root main.pd -- used here only to exercise entries()/read().
    candidate_dir = FIXTURE_CATALOG_ROOT / "candidates" / "105149"
    archive = FrozenCandidateArchive(candidate_dir)
    entries = archive.entries()
    assert len(entries) > 0
    names = {e.name for e in entries}
    assert "orac/main.pd" in names
    module_json_entries = [e.name for e in entries if e.name.endswith("module.json")]
    assert module_json_entries
    content = archive.read(module_json_entries[0])
    assert b"display" in content


def test_frozen_candidate_archive_read_missing_extraction_raises():
    candidate_dir = FIXTURE_CATALOG_ROOT / "candidates" / "105149"
    archive = FrozenCandidateArchive(candidate_dir)
    try:
        archive.read("orac/data/orac/presets/Init/params.json")  # real entry, not extracted
        assert False, "expected FileNotFoundError"
    except FileNotFoundError:
        pass
