"""`rig`'s CLI surface end to end, via `CliRunner` against the real app.

`catalog update` is exercised only through `--help` (Phase 1's own tests
cover its behaviour; it reaches the network, and `tests/conftest.py` blocks
every socket for the whole session). `validate` stays a documented stub --
Phase 8 owns the command surface and the lint policy (`rig lint`), not the
report schema or the tiers themselves (`docs/validation.md` "Implementation
order": Phases 9/10).

Every other command is exercised for real: `push`/`pull` against
`InMemoryTransport` (never a real card) and, for `pull`, a throwaway local
git repo plus `FakeGhClient` (never the real `gh` on this machine -- see
`tests/pull_helpers.py`). `rig.cli` exposes `_transport`/`_card_roots`/
`_git`/`_gh`/`_upgrade_fetcher` as the seams tests reach with `monkeypatch`,
so the command bodies under test are the real ones, not a stand-in.

`_PatchstorageModuleSource` (push's live `ModuleSource`/`UpdateChecker`) is
tested directly, without going through a CLI invocation or the network:
`_resolve()` only populates `self._sources` lazily, so a test can construct
the object and set that dict itself from an in-memory zip built with the
stdlib `zipfile` module -- the same seam-injection idea `_upgrade_fetcher`
already uses, one level lower.
"""

from __future__ import annotations

import dataclasses
import io
import json
import zipfile
from pathlib import Path

import pytest
from typer.testing import CliRunner

import rig.cli as cli
from rig.catalog.archive import ZipCandidateArchive
from rig.catalog.builtins import ingest_pinned_builtins
from rig.catalog.entry import CatalogEntry, VersionInfo
from rig.catalog.ingest import CandidateSource
from rig.catalog.io import write_catalog, write_lock
from rig.catalog.params import ParamSpec
from rig.catalog.slugs import module_key
from rig.cli import app
from rig.push.modules import ModuleSourceUnavailable
from rig.song.bindings import write_bindings
from rig.transport.memory import InMemoryTransport

from .pull_helpers import FakeGhClient, make_git_repo

runner = CliRunner()

PRESETS_ROOT = "data/orhack/presets"

# routers/hybrid and clocks/transport (s1/s2) are compiled into every song
# regardless of its own modules (docs/schema.md "System slots") -- any test
# that pushes a real preset needs them in the seeded catalog, same as
# tests/compile_helpers.py's system_catalog().
_SYSTEM_MODULE_TYPES = {"routers/hybrid", "clocks/transport"}
_system_entries_cache: list[CatalogEntry] | None = None


def _system_entries() -> list[CatalogEntry]:
    global _system_entries_cache
    if _system_entries_cache is None:
        _system_entries_cache = [e for e in ingest_pinned_builtins() if e.module_type in _SYSTEM_MODULE_TYPES]
    return list(_system_entries_cache)


# --- shared fixtures/helpers -------------------------------------------------


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """An empty repo working directory -- `rig` resolves every path (songs/,
    .rig/, media/) against the current working directory."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _synth_entry() -> CatalogEntry:
    """A built-in-shaped entry: same shape `tests/test_push_runner.py` uses,
    so a compiled preset here is directly comparable to that suite's."""
    return CatalogEntry(
        key="synth@orhack", source="orhack", display="Synth",
        module_type="instruments/synth/synth", category=None, category_override=None,
        tags=[], params=[ParamSpec(name="level", id="lvl", label="Level", type="pct", min=0, max=100, default=50)],
        version=VersionInfo(),
    )


def _community_entry(param_id: str = "amt", updated_at: str = "2020-01-01") -> CatalogEntry:
    return CatalogEntry(
        key="warble@warble", source="warble", display="Warble",
        module_type="effects/mod/warble@warble", category="effects/mod", category_override=None,
        tags=[],
        params=[ParamSpec(name="amount", id=param_id, label="Amount", type="pct", min=0, max=100, default=50)],
        version=VersionInfo(updated_at=updated_at, file_id=1, archive_sha256="abc"),
    )


def _write_song(songs_dir: Path, name: str, program: int, *, chain_name: str = "lead", level: float = 50) -> str:
    songs_dir.mkdir(parents=True, exist_ok=True)
    song_id = name.lower()
    (songs_dir / f"{song_id}.yaml").write_text(
        f"song: {name}\nprogram: {program}\n\n"
        f"chains:\n  - name: {chain_name}\n    modules:\n      - synth@orhack:\n          level: {level}\n",
        encoding="utf-8",
    )
    return song_id


def _bare_card() -> InMemoryTransport:
    """The minimum an ORHACK card needs for push's structural checks to
    pass -- mirrors `tests/test_push_runner.py`'s own `_bare_card`."""
    t = InMemoryTransport()
    t.write("Patches/0RHACK/manifest.txt", b"")
    t.write("data/orhack/rack.json", json.dumps({"currentPreset": "Init"}).encode("utf-8"))
    t.write(f"{PRESETS_ROOT}/Init/params.json", b"{}")
    return t


def _seed_catalog(entries: list[CatalogEntry]) -> None:
    write_catalog(entries, Path(".rig/catalog"))
    write_lock(entries, Path(".rig/modules.lock"))


# --- help / command surface --------------------------------------------------


def test_help_lists_all_seven_commands():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for name in ["push", "pull", "lint", "catalog", "upgrade", "rename-chain", "validate"]:
        assert name in result.output


def test_catalog_update_help_documents_the_command():
    # `catalog update` is implemented (Phase 1) and reaches the network for
    # its live discovery path, so it is not exercised end-to-end here --
    # tests/conftest.py blocks every socket for the whole session. Just
    # confirm the command is wired up and documented.
    result = runner.invoke(app, ["catalog", "update", "--help"])
    assert result.exit_code == 0
    assert "--dry-run" in result.output


def test_validate_tier_form_not_implemented():
    result = runner.invoke(app, ["validate", "--tier", "static", "song1", "song2"])
    assert result.exit_code != 0
    assert "not implemented" in result.output


def test_validate_hardware_tier_with_no_songs():
    result = runner.invoke(app, ["validate", "--tier", "hardware"])
    assert result.exit_code != 0
    assert "not implemented" in result.output


def test_validate_verify_report_not_implemented():
    result = runner.invoke(app, ["validate", "verify-report", "report.json"])
    assert result.exit_code != 0
    assert "not implemented" in result.output


def test_validate_help_documents_both_invocation_forms():
    # `validate` is a flat command, not a subcommand group (see the comment
    # above it in rig/cli.py), so `verify-report` isn't a discoverable
    # subcommand on its own -- the help text is the only place a caller
    # learns it exists.
    result = runner.invoke(app, ["validate", "--help"])
    assert result.exit_code == 0
    assert "rig validate --tier static|hardware [SONG...]" in result.output
    assert "rig validate verify-report REPORT" in result.output
    assert "verify-report" in result.output


def test_unknown_song_selection_is_a_clean_refusal(repo):
    result = runner.invoke(app, ["lint", "nosuch"])
    assert result.exit_code != 0
    # Same "rig <command>: <CODE>: <message>" shape as every other refusal
    # (_fail) -- this used to be an ad hoc, unprefixed message.
    assert "rig lint: UNKNOWN_SONG: unknown song(s): nosuch" in result.output


def test_unknown_song_selection_on_push_uses_the_same_refusal_shape(repo):
    result = runner.invoke(app, ["push", "nosuch"])
    assert result.exit_code != 0
    assert "rig push: UNKNOWN_SONG: unknown song(s): nosuch" in result.output


# --- lint ---------------------------------------------------------------


def test_lint_ok_for_a_valid_song_exits_zero(repo):
    _seed_catalog([_synth_entry(), *_system_entries()])
    _write_song(repo / "songs", "Vellichor", 3)
    result = runner.invoke(app, ["lint"])
    assert result.exit_code == 0, result.output
    assert "lint: ok" in result.output


def test_lint_reports_errors_and_exits_nonzero(repo):
    _seed_catalog([_synth_entry(), *_system_entries()])
    (repo / "songs").mkdir()
    (repo / "songs" / "bad.yaml").write_text(
        "song: Bad\nprogram: 3\nchains:\n  - name: pads\n    modules:\n      - nope@orhack: {}\n",
        encoding="utf-8",
    )
    result = runner.invoke(app, ["lint"])
    assert result.exit_code != 0
    assert "UNKNOWN_MODULE" in result.output


def test_lint_reports_warnings_without_failing(repo):
    _seed_catalog([_synth_entry(), *_system_entries()])
    (repo / "songs").mkdir()
    (repo / "songs" / "vellichor.yaml").write_text(
        "song: Vellichor\nprogram: 3\n\n"
        "chains:\n  - name: lead\n    modules:\n      - synth@orhack:\n"
        "          level: 50\n          note-thru: true\n",
        encoding="utf-8",
    )
    result = runner.invoke(app, ["lint"])
    assert result.exit_code == 0, result.output
    assert "FINAL_NOTE_THRU" in result.output


# --- push -----------------------------------------------------------------


def test_push_writes_selected_songs_and_exits_zero(repo, monkeypatch):
    _seed_catalog([_synth_entry(), *_system_entries()])
    _write_song(repo / "songs", "Vellichor", 3)
    transport = _bare_card()
    monkeypatch.setattr(cli, "_transport", transport)

    result = runner.invoke(app, ["push"])

    assert result.exit_code == 0, result.output
    assert "wrote: vellichor" in result.output
    assert transport.exists(f"{PRESETS_ROOT}/003-vellichor/params.json")


def test_push_refuses_when_a_song_fails_validation(repo, monkeypatch):
    _seed_catalog([_synth_entry(), *_system_entries()])
    (repo / "songs").mkdir()
    (repo / "songs" / "bad.yaml").write_text(
        "song: Bad\nprogram: 3\nchains:\n  - name: pads\n    modules:\n      - nope@orhack: {}\n",
        encoding="utf-8",
    )
    transport = _bare_card()
    monkeypatch.setattr(cli, "_transport", transport)

    result = runner.invoke(app, ["push"])

    assert result.exit_code != 0
    assert "UNKNOWN_MODULE" in result.output
    assert not transport.exists(f"{PRESETS_ROOT}/003-bad/params.json")


def test_push_dry_run_leaves_card_and_repo_untouched(repo, monkeypatch):
    _seed_catalog([_synth_entry(), *_system_entries()])
    _write_song(repo / "songs", "Vellichor", 3)
    transport = _bare_card()
    before = dict(transport._files)
    monkeypatch.setattr(cli, "_transport", transport)

    result = runner.invoke(app, ["push", "--dry-run"])

    assert result.exit_code == 0, result.output
    assert "dry run" in result.output
    assert transport._files == before
    assert not (repo / ".rig" / "state").exists()


def test_push_reports_orhack_integrity_error_cleanly(repo, monkeypatch):
    # verify_orhack_structure raises rig.push.modules.OrhackIntegrityError,
    # a distinct type from PushError -- must not leak as an uncaught
    # traceback (Ruling #2).
    _seed_catalog([_synth_entry(), *_system_entries()])
    _write_song(repo / "songs", "Vellichor", 3)
    transport = InMemoryTransport()  # no Patches/0RHACK/manifest.txt at all
    monkeypatch.setattr(cli, "_transport", transport)

    result = runner.invoke(app, ["push"])

    assert result.exit_code != 0
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert "ORHACK_NOT_INSTALLED" in result.output


def test_push_no_card_found_is_a_clean_refusal(repo, monkeypatch):
    _seed_catalog([_synth_entry(), *_system_entries()])
    _write_song(repo / "songs", "Vellichor", 3)
    monkeypatch.setattr(cli, "_card_roots", [])  # empty, not None -- never a live OS scan in a test

    result = runner.invoke(app, ["push"])

    assert result.exit_code != 0
    assert "NO_CARD_FOUND" in result.output


def test_push_refuses_hand_renamed_chain_and_names_rename_chain(repo, monkeypatch):
    songs_dir = repo / "songs"
    _seed_catalog([_synth_entry(), *_system_entries()])
    _write_song(songs_dir, "Vellichor", 3, chain_name="lead")
    transport = _bare_card()
    monkeypatch.setattr(cli, "_transport", transport)
    first = runner.invoke(app, ["push"])
    assert first.exit_code == 0, first.output

    # Hand-edit the chain name in place, bypassing `rig rename-chain` --
    # push must detect the orphaned binding and refuse (Prompt/05-push.md
    # step 5, decision #58).
    text = (songs_dir / "vellichor.yaml").read_text(encoding="utf-8")
    (songs_dir / "vellichor.yaml").write_text(text.replace("name: lead", "name: lead2"), encoding="utf-8")

    result = runner.invoke(app, ["push"])

    assert result.exit_code != 0
    assert "UNCOMMANDED_CHAIN_RENAME" in result.output
    assert "rig rename-chain vellichor lead lead2" in result.output


# --- pull -----------------------------------------------------------------


def _drift_level(transport: InMemoryTransport, directory: str, new_level: float) -> None:
    observed = json.loads(transport.read(f"{PRESETS_ROOT}/{directory}/params.json"))
    slot_id = next(
        sid for sid, slot in observed.items()
        if isinstance(slot, dict) and slot.get("moduleType") == "instruments/synth/synth"
    )
    observed[slot_id]["params"]["lvl"] = new_level
    transport.write(f"{PRESETS_ROOT}/{directory}/params.json", json.dumps(observed).encode("utf-8"))


def test_pull_reports_drift_and_opens_a_pr(repo, monkeypatch):
    _seed_catalog([_synth_entry(), *_system_entries()])
    _write_song(repo / "songs", "Vellichor", 3)
    transport = _bare_card()
    monkeypatch.setattr(cli, "_transport", transport)
    assert runner.invoke(app, ["push"]).exit_code == 0

    _drift_level(transport, "003-vellichor", 75)
    git, _repo_dir = make_git_repo(repo, initial_files={"README.md": b"x\n"})
    gh = FakeGhClient()
    monkeypatch.setattr(cli, "_git", git)
    monkeypatch.setattr(cli, "_gh", gh)

    result = runner.invoke(app, ["pull"])

    assert result.exit_code == 0, result.output
    assert "drifted: vellichor" in result.output
    assert git.branch_exists("pull/vellichor")
    new_yaml = git.read_blob("pull/vellichor", "songs/vellichor.yaml").decode("utf-8")
    assert "level: 75" in new_yaml


def test_pull_dry_run_leaves_card_and_repo_untouched(repo, monkeypatch):
    _seed_catalog([_synth_entry(), *_system_entries()])
    _write_song(repo / "songs", "Vellichor", 3)
    transport = _bare_card()
    monkeypatch.setattr(cli, "_transport", transport)
    assert runner.invoke(app, ["push"]).exit_code == 0

    _drift_level(transport, "003-vellichor", 75)
    card_before = dict(transport._files)
    git, _repo_dir = make_git_repo(repo, initial_files={"README.md": b"x\n"})
    gh = FakeGhClient()
    monkeypatch.setattr(cli, "_git", git)
    monkeypatch.setattr(cli, "_gh", gh)

    result = runner.invoke(app, ["pull", "--dry-run"])

    assert result.exit_code == 0, result.output
    assert "drifted: vellichor" in result.output
    assert transport._files == card_before
    assert not git.branch_exists("pull/vellichor")
    assert gh.create_calls == []


def test_pull_no_card_found_is_a_clean_refusal(repo, monkeypatch):
    _seed_catalog([_synth_entry(), *_system_entries()])
    monkeypatch.setattr(cli, "_card_roots", [])

    result = runner.invoke(app, ["pull"])

    assert result.exit_code != 0
    assert "NO_CARD_FOUND" in result.output


def test_pull_without_adopt_flag_never_adopts(repo, monkeypatch):
    # Ruling #1: adoption is off by default.
    _seed_catalog([_synth_entry(), *_system_entries()])
    transport = _bare_card()
    transport.write(f"{PRESETS_ROOT}/005-stranger/params.json", b"{}")
    monkeypatch.setattr(cli, "_transport", transport)
    git, _repo_dir = make_git_repo(repo, initial_files={"README.md": b"x\n"})
    gh = FakeGhClient()
    monkeypatch.setattr(cli, "_git", git)
    monkeypatch.setattr(cli, "_gh", gh)

    result = runner.invoke(app, ["pull"])

    assert result.exit_code == 0, result.output
    assert "adopted" not in result.output
    assert gh.create_calls == []


# --- upgrade ----------------------------------------------------------------


def test_upgrade_refuses_a_slug_id_reorder_used_by_a_song(repo, monkeypatch):
    _seed_catalog([_community_entry(param_id="amt")])
    (repo / "songs").mkdir()
    (repo / "songs" / "vellichor.yaml").write_text(
        "song: Vellichor\nprogram: 3\n\n"
        "chains:\n  - name: lead\n    modules:\n      - warble@warble:\n          amount: 40\n",
        encoding="utf-8",
    )
    catalog_before = {p: p.read_bytes() for p in Path(".rig/catalog").glob("*.json")}
    lock_before = Path(".rig/modules.lock").read_bytes()

    monkeypatch.setattr(
        cli, "_upgrade_fetcher", lambda requested: {"warble@warble": _community_entry(param_id="different_amt")}
    )

    result = runner.invoke(app, ["upgrade", "warble@warble"])

    assert result.exit_code != 0
    assert "amount" in result.output
    assert "vellichor" in result.output
    assert {p: p.read_bytes() for p in Path(".rig/catalog").glob("*.json")} == catalog_before
    assert Path(".rig/modules.lock").read_bytes() == lock_before


def test_upgrade_writes_new_catalog_and_lock_when_no_song_is_affected(repo, monkeypatch):
    _seed_catalog([_community_entry(param_id="amt", updated_at="2020-01-01")])
    monkeypatch.setattr(
        cli,
        "_upgrade_fetcher",
        lambda requested: {"warble@warble": _community_entry(param_id="different_amt", updated_at="2021-01-01")},
    )

    result = runner.invoke(app, ["upgrade", "warble@warble"])

    assert result.exit_code == 0, result.output
    assert "upgraded: warble@warble" in result.output
    lock = json.loads(Path(".rig/modules.lock").read_text(encoding="utf-8"))
    assert lock["modules"]["warble@warble"]["updated_at"] == "2021-01-01"


def test_upgrade_dry_run_leaves_catalog_and_lock_untouched(repo, monkeypatch):
    _seed_catalog([_community_entry(param_id="amt", updated_at="2020-01-01")])
    catalog_before = {p: p.read_bytes() for p in Path(".rig/catalog").glob("*.json")}
    lock_before = Path(".rig/modules.lock").read_bytes()
    monkeypatch.setattr(
        cli,
        "_upgrade_fetcher",
        lambda requested: {"warble@warble": _community_entry(param_id="different_amt", updated_at="2021-01-01")},
    )

    result = runner.invoke(app, ["upgrade", "warble@warble", "--dry-run"])

    assert result.exit_code == 0, result.output
    assert "would upgrade: warble@warble" in result.output
    assert {p: p.read_bytes() for p in Path(".rig/catalog").glob("*.json")} == catalog_before
    assert Path(".rig/modules.lock").read_bytes() == lock_before


def test_upgrade_unknown_module_is_a_clean_refusal(repo):
    _seed_catalog([_community_entry()])
    result = runner.invoke(app, ["upgrade", "nope@nowhere"])
    assert result.exit_code != 0
    assert "UNKNOWN_MODULE" in result.output


def test_upgrade_refuses_a_builtin_module(repo):
    _seed_catalog([_synth_entry(), *_system_entries()])
    result = runner.invoke(app, ["upgrade", "synth@orhack"])
    assert result.exit_code != 0
    assert "BUILTIN_NOT_UPGRADABLE" in result.output


# --- rename-chain -----------------------------------------------------------


def test_rename_chain_rewrites_song_and_binding(repo):
    songs_dir = repo / "songs"
    songs_dir.mkdir()
    (songs_dir / "vellichor.yaml").write_text(
        "song: Vellichor\nprogram: 3\n\n"
        "chains:\n  - name: lead\n    modules:\n      - synth@orhack:\n          level: 50\n",
        encoding="utf-8",
    )
    write_bindings(Path(".rig/state/chains"), "vellichor", {"lead": "A"})

    result = runner.invoke(app, ["rename-chain", "vellichor", "lead", "pads"])

    assert result.exit_code == 0, result.output
    text = (songs_dir / "vellichor.yaml").read_text(encoding="utf-8")
    assert "name: pads" in text
    assert "name: lead" not in text
    bindings = json.loads((Path(".rig/state/chains") / "vellichor.json").read_text(encoding="utf-8"))
    assert bindings == {"pads": "A"}


def test_rename_chain_refuses_unknown_old_name(repo):
    songs_dir = repo / "songs"
    songs_dir.mkdir()
    (songs_dir / "vellichor.yaml").write_text(
        "song: Vellichor\nprogram: 3\n\nchains:\n  - name: lead\n    modules: []\n", encoding="utf-8"
    )
    result = runner.invoke(app, ["rename-chain", "vellichor", "nope", "pads"])
    assert result.exit_code != 0
    assert "CHAIN_NOT_FOUND" in result.output


def test_rename_chain_refuses_a_colliding_new_name(repo):
    songs_dir = repo / "songs"
    songs_dir.mkdir()
    (songs_dir / "vellichor.yaml").write_text(
        "song: Vellichor\nprogram: 3\n\n"
        "chains:\n  - name: lead\n    modules: []\n  - name: pads\n    modules: []\n",
        encoding="utf-8",
    )
    result = runner.invoke(app, ["rename-chain", "vellichor", "lead", "pads"])
    assert result.exit_code != 0
    assert "CHAIN_NAME_COLLISION" in result.output


def test_rename_chain_unknown_song_is_a_clean_refusal(repo):
    result = runner.invoke(app, ["rename-chain", "nosuch", "lead", "pads"])
    assert result.exit_code != 0
    assert "UNKNOWN_SONG" in result.output


# --- _PatchstorageModuleSource (push's live ModuleSource/UpdateChecker) -----


def _make_zip(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    return buf.getvalue()


def _seeded_module_source(archive_bytes: bytes, *, slug: str = "warble", display: str = "Warble"):
    """A `_PatchstorageModuleSource` with `_sources` pre-populated -- skips
    `_resolve()`'s network call entirely, same seam `_upgrade_fetcher` uses
    one level up. Returns `(module_source, entry)` where `entry.key` is
    exactly what a real ingest of this archive would have produced."""
    entry_key = module_key(display, slug)
    source = CandidateSource(
        id=1,
        archive=ZipCandidateArchive(archive_bytes),
        detail={"slug": slug, "updated_at": "2020-01-01", "files": [{"url": "https://example.invalid/x.zip"}]},
        archive_sha256="deadbeef",
    )
    module_source = cli._PatchstorageModuleSource({slug})
    module_source._sources = {slug: source}
    entry = CatalogEntry(
        key=entry_key, source=slug, display=display,
        module_type=f"effects/mod/{entry_key}", category="effects/mod", category_override=None,
        tags=[], params=[], version=VersionInfo(updated_at="2019-01-01", file_id=1, archive_sha256="old"),
    )
    return module_source, entry


def test_module_source_fetch_strips_junk_and_keeps_real_files():
    archive_bytes = _make_zip(
        {
            "module.json": b'{"display": "Warble", "parameters": []}',
            "module.pd": b"#N canvas;",
            "README.md": b"hello",
            "__MACOSX/somefile.txt": b"junk",  # Mac zip-export sibling directory
            "._module.pd": b"junk",  # AppleDouble resource-fork twin
            ".DS_Store": b"junk",
            "notes.txt~": b"junk",  # editor backup
            "scratch.swp": b"junk",  # vim swap
            "lib.dll": b"junk",  # Windows binary, never runs on the S2
        }
    )
    module_source, entry = _seeded_module_source(archive_bytes)

    files = module_source.fetch(entry)

    assert files["module.json"] == b'{"display": "Warble", "parameters": []}'
    assert files["module.pd"] == b"#N canvas;"
    assert files["README.md"] == b"hello"
    for junk in ("__MACOSX/somefile.txt", "._module.pd", ".DS_Store", "notes.txt~", "scratch.swp", "lib.dll"):
        assert junk not in files, f"{junk!r} should have been stripped"


def test_module_source_fetch_refuses_a_module_needing_abl_link():
    archive_bytes = _make_zip(
        {
            "module.json": b'{"display": "Warble", "parameters": []}',
            "module.pd": b"#N canvas;",
            "abl_link~.pd_linux": b"binary",
        }
    )
    module_source, entry = _seeded_module_source(archive_bytes)

    with pytest.raises(ModuleSourceUnavailable) as exc_info:
        module_source.fetch(entry)

    assert "abl_link~.pd_linux" in str(exc_info.value)
    assert entry.key in str(exc_info.value)


def test_module_source_fetch_raises_when_slug_not_found():
    module_source = cli._PatchstorageModuleSource({"warble"})
    module_source._sources = {}
    entry = CatalogEntry(
        key="warble@warble", source="warble", display="Warble",
        module_type="effects/mod/warble@warble", category="effects/mod", category_override=None,
        tags=[], params=[], version=VersionInfo(),
    )

    with pytest.raises(ModuleSourceUnavailable):
        module_source.fetch(entry)


def test_module_source_check_update_reports_a_changed_updated_at():
    archive_bytes = _make_zip(
        {"module.json": b'{"display": "Warble", "parameters": []}', "module.pd": b"#N canvas;"}
    )
    module_source, entry = _seeded_module_source(archive_bytes)

    description = module_source.check_update(entry)

    assert description is not None
    assert entry.key in description


def test_module_source_check_update_is_none_when_updated_at_matches():
    archive_bytes = _make_zip(
        {"module.json": b'{"display": "Warble", "parameters": []}', "module.pd": b"#N canvas;"}
    )
    module_source, entry = _seeded_module_source(archive_bytes)
    # Match the seeded source's own detail['updated_at'] (see _seeded_module_source).
    entry = dataclasses.replace(entry, version=VersionInfo(updated_at="2020-01-01", file_id=1, archive_sha256="old"))

    assert module_source.check_update(entry) is None
