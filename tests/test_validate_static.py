"""Static (Tier 1) validation -- Prompt/09-static-validation.md.

The "Verification" table's five fixture rows (broken ELF, wrong architecture,
unsafe archive, unmodelled sidecar, good fixture) are exercised directly
against `catalog_gate_checks`, which replays Task 1's already-tested
`build_community_catalog` and shapes its result into `CheckResult`s -- this
module does not reimplement the gate, only consumes it (Task 9 brief).
"""

from __future__ import annotations

from rig.catalog.archive import ZipCandidateArchive
from rig.catalog.entry import CatalogEntry, VersionInfo
from rig.catalog.gate import RejectReason
from rig.catalog.ingest import CandidateSource
from rig.catalog.params import ParamSpec
from rig.song.model import Chain, ModuleSlot, Song
from rig.validate.report import STATUS_FAIL, STATUS_PASS, STATUS_UNAVAILABLE
from rig.validate.static import (
    CATALOG_GATE_CHECK_ID,
    SCHEMA_LINT_CHECK_ID,
    catalog_gate_checks,
    locked_module_gate_checks,
    run_static,
)

from .catalog_helpers import MODULE_JSON, MODULE_PD, build_zip, elf32_header

_X86_ELF = elf32_header(e_machine=0x03, e_flags=0)


def _source(files: dict[str, bytes], *, slug: str = "test-mod", categories=("effect",)) -> CandidateSource:
    return CandidateSource(
        id=1,
        archive=ZipCandidateArchive(build_zip(files)),
        detail={
            "slug": slug,
            "updated_at": "2020-01-01",
            "files": [{"id": 1}],
            "categories": [{"slug": c} for c in categories],
            "tags": [],
        },
        archive_sha256="deadbeef",
    )


# --- the Verification table's five fixture rows ------------------------------


def test_broken_elf_fails_with_the_wrong_arch_check_id():
    # A file starting with the ELF magic but too short to carry a header at
    # all -- gate.py folds a `parse_elf_header` ElfError into the same
    # wrong-arch bucket as an ABI mismatch (rig/catalog/gate.py), since both
    # are "this external is not a shape the S2 can load".
    source = _source(
        {
            "mymod/module.json": MODULE_JSON,
            "mymod/module.pd": MODULE_PD,
            "mymod/broken~.pd_linux": b"\x7fELF\x01",
        }
    )
    results = catalog_gate_checks(source)
    assert any(c.id == RejectReason.WRONG_ARCH.value and c.status == STATUS_FAIL for c in results)


def test_wrong_architecture_fails_with_the_wrong_arch_check_id():
    source = _source(
        {
            "mymod/module.json": MODULE_JSON,
            "mymod/module.pd": MODULE_PD,
            "mymod/bad~.pd_linux": _X86_ELF,
        }
    )
    results = catalog_gate_checks(source)
    assert any(c.id == RejectReason.WRONG_ARCH.value and c.status == STATUS_FAIL for c in results)


def test_unsafe_archive_fails_with_the_archive_unsafe_check_id():
    source = _source(
        {
            "../escape/module.json": MODULE_JSON,
            "../escape/module.pd": MODULE_PD,
        }
    )
    results = catalog_gate_checks(source)
    assert any(c.id == RejectReason.ARCHIVE_UNSAFE.value and c.status == STATUS_FAIL for c in results)


def test_unmodelled_sidecar_fails_with_the_unmodelled_sidecar_check_id():
    pd_with_bad_sidecar = (
        b"#N canvas 0 0 100 100 10;\n"
        b"#X msg 10 10 read /weird/presets/nope.txt;\n"
    )
    source = _source(
        {
            "mymod/module.json": MODULE_JSON,
            "mymod/module.pd": pd_with_bad_sidecar,
        }
    )
    results = catalog_gate_checks(source)
    assert any(
        c.id == RejectReason.UNMODELLED_SIDECAR.value and c.status == STATUS_FAIL for c in results
    )


def test_good_fixture_passes():
    source = _source({"mymod/module.json": MODULE_JSON, "mymod/module.pd": MODULE_PD})
    results = catalog_gate_checks(source)
    assert all(c.status == STATUS_PASS for c in results)
    assert any(c.id == CATALOG_GATE_CHECK_ID for c in results)


# --- locked_module_gate_checks ------------------------------------------------


def _catalog_entry(key: str, source: str) -> CatalogEntry:
    return CatalogEntry(
        key=key, source=source, display=key, module_type=f"effects/mod/{key}",
        category="effects/mod", category_override=None, tags=[], params=[
            ParamSpec(name="amount", id="amt", label="Amount", type="pct", min=0, max=100, default=50)
        ],
        version=VersionInfo(updated_at="2020-01-01", file_id=1, archive_sha256="x"),
    )


def test_locked_module_gate_checks_runs_only_locked_community_modules():
    good = _source({"good/module.json": MODULE_JSON, "good/module.pd": MODULE_PD}, slug="good-mod")
    unlocked = _source({"skip/module.json": MODULE_JSON, "skip/module.pd": MODULE_PD}, slug="unlocked-mod")

    catalog = [_catalog_entry("mod@good-mod", "good-mod"), _catalog_entry("mod@unlocked-mod", "unlocked-mod")]
    lock = {"modules": {"mod@good-mod": {}}}  # only good-mod is locked

    results = locked_module_gate_checks(catalog=catalog, lock=lock, frozen_sources=[good, unlocked])

    assert any(c.status == STATUS_PASS for c in results)
    assert len(results) == 1  # unlocked-mod's candidate was never gated


def test_locked_module_gate_checks_reports_unavailable_when_not_in_the_fixture():
    catalog = [_catalog_entry("mod@missing-mod", "missing-mod")]
    lock = {"modules": {"mod@missing-mod": {}}}

    results = locked_module_gate_checks(catalog=catalog, lock=lock, frozen_sources=[])

    assert len(results) == 1
    assert results[0].status == STATUS_UNAVAILABLE
    assert results[0].id == CATALOG_GATE_CHECK_ID


def test_locked_module_gate_checks_skips_builtins():
    builtin = _catalog_entry("mod@orhack", "orhack")
    catalog = [builtin]
    lock = {"modules": {}}  # builtins are never recorded in the lock

    results = locked_module_gate_checks(catalog=catalog, lock=lock, frozen_sources=[])

    assert results == []


def test_locked_module_gate_checks_fails_a_genuine_duplicate_runtime_path():
    # A community module admitted from the gate replay whose derived
    # moduleType ("effects/mod/test-module@dup-mod" -- MODULE_JSON's
    # display "Test Module", slugified, at source "dup-mod", filed under
    # the "effect" category) collides with a built-in already claiming that
    # exact runtime path. docs/catalog.md: a community path shadowing a
    # built-in is a hard reject, not a warning.
    colliding_source = _source(
        {"mymod/module.json": MODULE_JSON, "mymod/module.pd": MODULE_PD}, slug="dup-mod"
    )
    builtin_claiming_the_path = CatalogEntry(
        key="incumbent@orhack", source="orhack", display="Incumbent",
        module_type="effects/mod/test-module@dup-mod", category=None, category_override=None,
        tags=[], params=[], version=VersionInfo(),
    )
    catalog = [builtin_claiming_the_path, _catalog_entry("mod@dup-mod", "dup-mod")]
    lock = {"modules": {"mod@dup-mod": {}}}

    results = locked_module_gate_checks(catalog=catalog, lock=lock, frozen_sources=[colliding_source])

    assert any(
        c.id == RejectReason.DUPLICATE_MODULE_PATH.value and c.status == STATUS_FAIL for c in results
    )


def test_locked_module_gate_checks_reports_no_duplicate_path_failure_for_a_clean_set():
    # Two locked community modules with genuinely distinct derived
    # moduleTypes (different display names -> different keys -> different
    # runtime paths) must not trip the duplicate-path check.
    first = _source(
        {"one/module.json": b'{"display": "One", "parameters": []}', "one/module.pd": MODULE_PD},
        slug="mod-one",
    )
    second = _source(
        {"two/module.json": b'{"display": "Two", "parameters": []}', "two/module.pd": MODULE_PD},
        slug="mod-two",
    )
    catalog = [_catalog_entry("mod@mod-one", "mod-one"), _catalog_entry("mod@mod-two", "mod-two")]
    lock = {"modules": {"mod@mod-one": {}, "mod@mod-two": {}}}

    results = locked_module_gate_checks(catalog=catalog, lock=lock, frozen_sources=[first, second])

    assert not any(c.id == RejectReason.DUPLICATE_MODULE_PATH.value for c in results)
    assert sum(1 for c in results if c.status == STATUS_PASS) == 2


# --- run_static orchestration -------------------------------------------------


def _synth_entry() -> CatalogEntry:
    return CatalogEntry(
        key="synth@orhack", source="orhack", display="Synth", module_type="instruments/synth/synth",
        category=None, category_override=None, tags=[],
        params=[ParamSpec(name="level", id="lvl", label="Level", type="pct", min=0, max=100, default=50)],
        version=VersionInfo(),
    )


def _song(name: str, program: int, *, level: float = 50.0) -> Song:
    return Song(
        name=name,
        program=program,
        sends=[],
        master=[],
        mod_sources=[],
        chains=[Chain(name="lead", modules=[ModuleSlot(key="synth@orhack", params={"level": level})])],
    )


def test_run_static_passes_for_a_clean_song_and_no_locked_modules(tmp_path):
    report = run_static(
        songs={"vellichor": _song("Vellichor", 3)},
        catalog=[_synth_entry()],
        lock={"modules": {}},
        bindings_dir=tmp_path / "chains",
        frozen_sources=[],
    )
    assert report.verdict == "pass"
    assert report.tier == "static"
    assert report.failures == []
    assert report.checks[0].song == "vellichor"
    assert report.checks[0].status == "pass"
    assert report.checks[0].checks[0].id == SCHEMA_LINT_CHECK_ID
    assert report.confidence == "static-only"
    assert "not evidence the rig is stage-ready" in report.scope_note


def test_run_static_fails_when_a_song_has_a_hard_error(tmp_path):
    bad_song = Song(
        name="Bad", program=3, sends=[], master=[], mod_sources=[],
        chains=[Chain(name="lead", modules=[ModuleSlot(key="nope@orhack", params={})])],
    )
    report = run_static(
        songs={"bad": bad_song},
        catalog=[_synth_entry()],
        lock={"modules": {}},
        bindings_dir=tmp_path / "chains",
        frozen_sources=[],
    )
    assert report.verdict == "fail"
    assert any(f.id == "UNKNOWN_MODULE" for f in report.failures)


def test_run_static_fails_when_a_locked_module_fails_the_gate(tmp_path):
    bad_source = _source(
        {"mymod/module.json": MODULE_JSON, "mymod/module.pd": MODULE_PD, "mymod/bad~.pd_linux": _X86_ELF},
        slug="bad-mod",
    )
    catalog = [_synth_entry(), _catalog_entry("mod@bad-mod", "bad-mod")]
    lock = {"modules": {"mod@bad-mod": {}}}

    report = run_static(
        songs={"vellichor": _song("Vellichor", 3)},
        catalog=catalog,
        lock=lock,
        bindings_dir=tmp_path / "chains",
        frozen_sources=[bad_source],
    )
    assert report.verdict == "fail"
    assert any(f.id == RejectReason.WRONG_ARCH.value for f in report.failures)
    assert report.metrics["catalog"]["modules_failed"] == 1


def test_run_static_selection_narrows_reported_songs_but_not_the_catalog_gate(tmp_path):
    songs = {"vellichor": _song("Vellichor", 3), "tide": _song("Tide", 4)}
    report = run_static(
        songs=songs,
        selected={"vellichor"},
        catalog=[_synth_entry()],
        lock={"modules": {}},
        bindings_dir=tmp_path / "chains",
        frozen_sources=[],
    )
    assert [g.song for g in report.checks] == ["vellichor"]


def test_run_static_cross_song_duplicate_program_is_a_top_level_failure(tmp_path):
    songs = {"vellichor": _song("Vellichor", 3), "tide": _song("Tide", 3)}
    report = run_static(
        songs=songs,
        catalog=[_synth_entry()],
        lock={"modules": {}},
        bindings_dir=tmp_path / "chains",
        frozen_sources=[],
    )
    assert report.verdict == "fail"
    assert any(f.id == "DUPLICATE_PROGRAM" for f in report.failures)
