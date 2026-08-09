"""`ZipCandidateArchive` -- the archive view the gate and push both read.

Exercised with synthetic, offline-built zips; the same class reads what
`rig catalog add` downloads and what `modules/` stores.
"""

from __future__ import annotations

from rig.catalog.archive import ZipCandidateArchive

from tests.catalog_helpers import MODULE_JSON, MODULE_PD, build_zip, elf32_header


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


def test_zip_candidate_archive_keeps_the_original_bytes():
    # `modules/` commits the upload unmodified so its sha256 still matches
    # what Patchstorage published -- a re-zip would not.
    data = build_zip({"mymod/module.json": MODULE_JSON})
    assert ZipCandidateArchive(data).data == data
