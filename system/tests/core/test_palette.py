"""`rig palette` -- installing the compatible community set to the card for
on-device auditioning, decoupled from songs.

Every card here is an `InMemoryTransport` seeded through `rig.cli._transport`;
no socket is opened (tests/conftest.py blocks them session-wide anyway).
"""

from __future__ import annotations

import hashlib
import json
import zipfile
from io import BytesIO
from pathlib import Path

import pytest
from typer.testing import CliRunner

import rig.cli as cli
from rig.catalog.entry import CatalogEntry, VersionInfo
from rig.catalog.io import write_catalog, write_lock
from rig.catalog.params import ParamSpec
from rig.catalog.store import write_archive
from rig.cli import app
from rig.palette import MANAGED_LEDGER_PATH, compatible_community_entries
from rig.push.modules import module_install_dir
from rig.transport.card import PRESETS_ROOT
from rig.transport.memory import InMemoryTransport

runner = CliRunner()


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """An empty repo working directory -- `rig` resolves every path against it."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


# --- fixtures ----------------------------------------------------------------


def _builtin(module_type: str, key: str = "synth@orhack") -> CatalogEntry:
    return CatalogEntry(
        key=key, source="orhack", display="Synth", module_type=module_type,
        category=None, category_override=None, tags=[],
        params=[ParamSpec(name="level", id="lvl", label="Level", type="pct", min=0, max=100, default=50)],
        version=VersionInfo(),
    )


def _community(display: str, source: str) -> tuple[CatalogEntry, bytes]:
    """A community entry plus the committed archive `fetch` will read for it.

    The archive is a bare `module.json`/`module.pd` module, so the catalog gate
    accepts it and its recomputed key matches the entry (`StoredArchiveModuleSource`
    walks the archive to find the module that produced the entry)."""
    archive = BytesIO()
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("module.json", json.dumps({"display": display, "parameters": []}))
        z.writestr("module.pd", "#N canvas;")
    data = archive.getvalue()
    key = f"{source}@{source}"
    entry = CatalogEntry(
        key=key, source=source, display=display,
        module_type=f"effects/mod/{source}@{source}", category="effects/mod",
        category_override=None, tags=[],
        params=[ParamSpec(name="amount", id="amt", label="Amount", type="pct", min=0, max=100, default=50)],
        version=VersionInfo(
            updated_at="2020-01-01", file_id=1,
            archive_sha256=hashlib.sha256(data).hexdigest(), revision="1.0",
        ),
    )
    return entry, data


def _seed(entries: list[CatalogEntry]) -> None:
    write_catalog(entries, Path("system/data/catalog.json"))
    write_lock(entries, Path("system/data/modules.lock"))


def _store(entry: CatalogEntry, data: bytes) -> None:
    write_archive(Path("system/modules"), entry.source, "1.0", data)


def _bare_card() -> InMemoryTransport:
    t = InMemoryTransport()
    t.write("Patches/0RHACK/manifest.txt", b"")
    t.write("data/orhack/rack.json", json.dumps({"currentPreset": "Init"}).encode("utf-8"))
    t.write(f"{PRESETS_ROOT}/Init/params.json", b"{}")
    return t


# --- the compatible set ------------------------------------------------------


def test_compatible_drops_builtin_shadowers_and_keeps_the_rest(repo):
    warble, _ = _community("Warble", "warble")   # native path effects/mod/warble
    converb, _ = _community("Converb", "converb")  # native path effects/mod/converb
    catalog = [
        _builtin("instruments/synth/synth"),
        _builtin("effects/mod/warble", key="warble@orhack"),  # shadows the ORAC warble
        warble,
        converb,
    ]
    lock = {"modules": {warble.key: {}, converb.key: {}}}

    kept = {e.key for e in compatible_community_entries(catalog, lock)}

    assert kept == {"converb@converb"}  # warble dropped: a built-in already owns its path


def test_compatible_skips_unlocked_modules(repo):
    warble, _ = _community("Warble", "warble")
    catalog = [_builtin("instruments/synth/synth"), warble]

    assert compatible_community_entries(catalog, {"modules": {}}) == []


# --- install -----------------------------------------------------------------


def test_install_writes_modules_without_touching_the_managed_ledger(repo, monkeypatch):
    warble, warble_zip = _community("Warble", "warble")
    _seed([_builtin("instruments/synth/synth"), warble])
    _store(warble, warble_zip)
    card = _bare_card()
    monkeypatch.setattr(cli, "_transport", card)

    result = runner.invoke(app, ["palette", "install"])

    assert result.exit_code == 0, result.output
    assert card.exists(f"{module_install_dir(warble)}/module.json")
    # The invariant that keeps palette off the source-of-truth path: push's GC
    # only deletes what this ledger records, so leaving it absent means a later
    # push cannot sweep the palette away.
    assert not card.exists(MANAGED_LEDGER_PATH)
    assert "1 module(s) installed" in result.output


def test_install_refuses_when_a_pinned_archive_is_missing(repo, monkeypatch):
    warble, _ = _community("Warble", "warble")
    _seed([_builtin("instruments/synth/synth"), warble])  # archive never stored
    card = _bare_card()
    monkeypatch.setattr(cli, "_transport", card)

    result = runner.invoke(app, ["palette", "install"])

    assert result.exit_code != 0
    assert "MODULE_UNAVAILABLE" in result.output
    assert not card.exists(module_install_dir(warble))  # nothing written


def test_install_refuses_a_card_without_orhack(repo, monkeypatch):
    warble, warble_zip = _community("Warble", "warble")
    _seed([_builtin("instruments/synth/synth"), warble])
    _store(warble, warble_zip)
    monkeypatch.setattr(cli, "_transport", InMemoryTransport())  # no manifest.txt

    result = runner.invoke(app, ["palette", "install"])

    assert result.exit_code != 0
    assert "ORHACK_NOT_INSTALLED" in result.output


# --- clear -------------------------------------------------------------------


def test_clear_removes_palette_modules_but_keeps_song_managed_ones(repo, monkeypatch):
    warble, warble_zip = _community("Warble", "warble")
    converb, converb_zip = _community("Converb", "converb")
    _seed([_builtin("instruments/synth/synth"), warble, converb])
    _store(warble, warble_zip)
    _store(converb, converb_zip)
    card = _bare_card()
    monkeypatch.setattr(cli, "_transport", card)
    assert runner.invoke(app, ["palette", "install"]).exit_code == 0

    # A song owns warble: push recorded it in the managed ledger.
    card.write(
        MANAGED_LEDGER_PATH,
        json.dumps({"modules": {warble.key: warble.module_type}}).encode("utf-8"),
    )

    result = runner.invoke(app, ["palette", "clear"])

    assert result.exit_code == 0, result.output
    assert card.exists(module_install_dir(warble))       # push-managed, left alone
    assert not card.exists(module_install_dir(converb))  # palette-only, removed
    assert "1 module(s) removed" in result.output


# --- surface -----------------------------------------------------------------


def test_palette_is_listed_and_documents_its_subcommands():
    top = runner.invoke(app, ["--help"])
    assert "palette" in top.output
    sub = runner.invoke(app, ["palette", "--help"])
    assert "install" in sub.output and "clear" in sub.output
