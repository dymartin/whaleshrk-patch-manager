"""`.rig/catalog/` and `.rig/modules.lock` I/O -- docs/repo-layout.md."""

from __future__ import annotations

from rig.catalog.entry import CatalogEntry, ParamSpec, VersionInfo
from rig.catalog.io import read_catalog, read_lock, write_catalog, write_lock

_BUILTIN = CatalogEntry(
    key="echo@orhack",
    source="orhack",
    display="Echo",
    module_type="effects/delay/echo",
    category=None,
    category_override=None,
    tags=[],
    params=[ParamSpec(name="mix", id="mix_p", label="Mix", type="pct", min=0, max=100, default=50)],
    version=VersionInfo(),
)

_COMMUNITY = CatalogEntry(
    key="polystep@polystep",
    source="polystep",
    display="Polystep",
    module_type="sequencers/polystep@polystep",
    category="sequencers",
    category_override=None,
    tags=["sequencer"],
    params=[],
    version=VersionInfo(updated_at="2020-01-01T00:00:00+00:00", file_id=42, archive_sha256="a" * 64),
)


def test_write_and_read_catalog_round_trips(tmp_path):
    catalog_dir = tmp_path / "catalog"
    write_catalog([_BUILTIN, _COMMUNITY], catalog_dir)
    entries = read_catalog(catalog_dir)
    assert {e.key for e in entries} == {"echo@orhack", "polystep@polystep"}
    by_key = {e.key: e for e in entries}
    assert by_key["echo@orhack"].params[0].id == "mix_p"
    assert by_key["polystep@polystep"].version.file_id == 42


def test_write_catalog_removes_stale_entries(tmp_path):
    catalog_dir = tmp_path / "catalog"
    write_catalog([_BUILTIN, _COMMUNITY], catalog_dir)
    write_catalog([_BUILTIN], catalog_dir)
    entries = read_catalog(catalog_dir)
    assert {e.key for e in entries} == {"echo@orhack"}


def test_read_catalog_on_missing_directory_is_empty(tmp_path):
    assert read_catalog(tmp_path / "does-not-exist") == []


def test_write_and_read_lock_round_trips(tmp_path):
    lock_path = tmp_path / "modules.lock"
    write_lock([_BUILTIN, _COMMUNITY], lock_path)
    lock = read_lock(lock_path)
    assert "polystep@polystep" in lock["modules"]
    assert lock["modules"]["polystep@polystep"]["archive_sha256"] == "a" * 64


def test_lock_excludes_built_ins(tmp_path):
    lock_path = tmp_path / "modules.lock"
    write_lock([_BUILTIN, _COMMUNITY], lock_path)
    lock = read_lock(lock_path)
    assert "echo@orhack" not in lock["modules"]


def test_read_lock_on_missing_file_is_empty_shell(tmp_path):
    lock = read_lock(tmp_path / "does-not-exist" / "modules.lock")
    assert lock["modules"] == {}
