"""`rig`'s CLI surface end to end, via `CliRunner` against the real app.

`catalog add`/`catalog update` are exercised only through `--help`: they are
the only commands that reach Patchstorage, and `tests/conftest.py` blocks
every socket for the whole session.

Every other command is exercised for real: `push`/`pull` against
`InMemoryTransport` (never a real card) and, for `pull`, a throwaway local
git repo plus `FakeGhClient` (never the real `gh` on this machine -- see
`tests/pull_helpers.py`). `rig.cli` exposes `_transport`/`_card_roots`/
`_git`/`_gh`/`_upgrade_fetcher` as the seams tests reach with `monkeypatch`,
so the command bodies under test are the real ones, not a stand-in.

`StoredArchiveModuleSource` (push's on-disk `ModuleSource`) is tested
directly against real archives written into a tmp `modules/`, since nothing
about it needs the network.
"""

from __future__ import annotations

import dataclasses
import hashlib
import io
import json
import zipfile
from pathlib import Path

import pytest
from typer.main import get_command
from typer.testing import CliRunner

import rig.cli as cli
from rig.catalog.builtins import ingest_pinned_builtins
from rig.catalog.entry import CatalogEntry, VersionInfo
from rig.catalog.io import write_catalog, write_lock
from rig.catalog.params import ParamSpec
from rig.catalog.slugs import module_key
from rig.catalog.store import archive_path, write_archive
from rig.cli import app
from rig.hardware import CpuStats, DeviceUnavailable, SongMeasurement, Subject
from rig.push.archive_source import StoredArchiveModuleSource
from rig.push.modules import ModuleSourceUnavailable
from rig.song.bindings import write_bindings
from rig.transport.memory import InMemoryTransport

from tests.compile_helpers import system_catalog
from tests.pull_helpers import FakeGhClient, make_git_repo

runner = CliRunner()

PRESETS_ROOT = "data/orhack/presets"

# --- shared fixtures/helpers -------------------------------------------------


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """An empty repo working directory -- `rig` resolves every path (songs/,
    system/data/, system/media/) against the current working directory."""
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


class _HardwareDevice:
    def __init__(self, hashes=("same", "same")):
        self.hashes = iter(hashes)

    def card_hash(self):
        return next(self.hashes)


class _MidiOutput:
    name = "fake"

    def close(self):
        pass


def _hardware_repo(repo):
    _seed_catalog([_synth_entry(), *system_catalog()])
    _write_song(repo / "songs", "Vellichor", 3)


def _measurement():
    return SongMeasurement("vellichor", 100, CpuStats(10, 12), CpuStats(20, 24), (), 0)


def _subject():
    return Subject("commit", "lock", "device", "Organelle OS 5.1", "Pd", "ORHACK 0.52b", "fake")


def test_hardware_check_writes_a_new_baseline_after_card_identity(repo, monkeypatch):
    _hardware_repo(repo)
    monkeypatch.setattr(cli, "_hardware_device", _HardwareDevice())
    monkeypatch.setattr(cli, "_midi_output", _MidiOutput())
    monkeypatch.setattr(cli, "make_subject", lambda *args: _subject())
    monkeypatch.setattr(cli, "measure_song", lambda *args, **kwargs: _measurement())

    result = runner.invoke(app, ["hardware-check", "--midi-port", "fake"])

    assert result.exit_code == 0, result.output
    assert "vellichor: pass" in result.output
    assert "baseline written: vellichor" in result.output
    assert (repo / "system/data/state/hardware/vellichor.json").is_file()


def test_hardware_check_changed_card_fails_without_writing_baseline(repo, monkeypatch):
    _hardware_repo(repo)
    monkeypatch.setattr(cli, "_hardware_device", _HardwareDevice(("before", "after")))
    monkeypatch.setattr(cli, "_midi_output", _MidiOutput())
    monkeypatch.setattr(cli, "make_subject", lambda *args: _subject())
    monkeypatch.setattr(cli, "measure_song", lambda *args, **kwargs: _measurement())

    result = runner.invoke(app, ["hardware-check", "--midi-port", "fake"])

    assert result.exit_code != 0
    assert "CARD_CHANGED" in result.output
    assert not (repo / "system/data/state/hardware/vellichor.json").exists()


def test_hardware_check_unreachable_is_unavailable_and_writes_nothing(repo, monkeypatch):
    _hardware_repo(repo)
    monkeypatch.setattr(cli, "_hardware_device", _HardwareDevice())
    monkeypatch.setattr(cli, "_midi_output", _MidiOutput())
    monkeypatch.setattr(cli, "make_subject", lambda *args: (_ for _ in ()).throw(DeviceUnavailable("offline")))

    result = runner.invoke(app, ["hardware-check", "--midi-port", "fake"])

    assert result.exit_code == 0, result.output
    assert "unavailable: offline" in result.output
    assert not (repo / "system/data/state/hardware/vellichor.json").exists()


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
    write_catalog(entries, Path("system/data/catalog"))
    write_lock(entries, Path("system/data/modules.lock"))


# --- help / command surface --------------------------------------------------


def test_help_lists_every_command():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for name in ["push", "pull", "lint", "catalog", "upgrade", "rename-chain"]:
        assert name in result.output


def test_catalog_add_help_documents_the_command():
    # `catalog add` and `catalog update` are the only commands that reach
    # Patchstorage, and tests/conftest.py blocks every socket for the whole
    # session -- so both are only confirmed to be wired up and documented.
    result = runner.invoke(app, ["catalog", "add", "--help"])
    assert result.exit_code == 0
    assert "slug" in result.output.lower()


def test_catalog_update_help_documents_the_command():
    catalog = get_command(app).commands["catalog"]
    update = catalog.commands["update"]
    assert any("--dry-run" in param.opts for param in update.params)



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
    _seed_catalog([_synth_entry(), *system_catalog()])
    _write_song(repo / "songs", "Vellichor", 3)
    result = runner.invoke(app, ["lint"])
    assert result.exit_code == 0, result.output
    assert "lint: ok" in result.output


def test_lint_refuses_a_locked_module_whose_archive_is_not_committed(repo):
    # The repo's reproducibility check: a module pinned in the lock with no
    # archive in modules/ would compile a preset naming a moduleType that
    # never resolves.
    _seed_catalog([_synth_entry(), _community_entry(), *system_catalog()])
    result = runner.invoke(app, ["lint"])
    assert result.exit_code != 0
    assert "MODULE_ARCHIVE" in result.output
    assert "warble@warble" in result.output


def test_lint_accepts_a_locked_module_whose_archive_is_committed(repo):
    archive_bytes = _make_zip(
        {
            "module.json": b'{"display": "Warble", "parameters": [{"name": "Amount", "id": "amt"}]}',
            "module.pd": b"#N canvas;",
        }
    )
    entry = dataclasses.replace(
        _community_entry(),
        version=VersionInfo(
            updated_at="2020-01-01", file_id=1,
            archive_sha256=hashlib.sha256(archive_bytes).hexdigest(), revision="1.0",
        ),
    )
    _seed_catalog([_synth_entry(), entry, *system_catalog()])
    write_archive(repo / "system/modules", "warble", "1.0", archive_bytes)

    result = runner.invoke(app, ["lint"])

    assert result.exit_code == 0, result.output
    assert "lint: ok" in result.output


def test_lint_reports_errors_and_exits_nonzero(repo):
    _seed_catalog([_synth_entry(), *system_catalog()])
    (repo / "songs").mkdir()
    (repo / "songs" / "bad.yaml").write_text(
        "song: Bad\nprogram: 3\nchains:\n  - name: pads\n    modules:\n      - nope@orhack: {}\n",
        encoding="utf-8",
    )
    result = runner.invoke(app, ["lint"])
    assert result.exit_code != 0
    assert "UNKNOWN_MODULE" in result.output


def test_lint_reports_warnings_without_failing(repo):
    _seed_catalog([_synth_entry(), *system_catalog()])
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
    _seed_catalog([_synth_entry(), *system_catalog()])
    _write_song(repo / "songs", "Vellichor", 3)
    transport = _bare_card()
    monkeypatch.setattr(cli, "_transport", transport)

    result = runner.invoke(app, ["push"])

    assert result.exit_code == 0, result.output
    assert "wrote: vellichor" in result.output
    assert transport.exists(f"{PRESETS_ROOT}/003-vellichor/params.json")


def test_push_uses_ssh_by_default(repo, monkeypatch):
    _seed_catalog([_synth_entry(), *system_catalog()])
    _write_song(repo / "songs", "Vellichor", 3)
    transport = _bare_card()
    monkeypatch.setattr(cli, "SshTransport", lambda host: transport)

    result = runner.invoke(app, ["push", "--dry-run"])

    assert result.exit_code == 0, result.output


def test_push_usb_fallback_must_be_explicit(repo, monkeypatch):
    _seed_catalog([_synth_entry(), *system_catalog()])
    _write_song(repo / "songs", "Vellichor", 3)
    monkeypatch.setattr(cli, "_card_roots", [])

    result = runner.invoke(app, ["push", "--transport", "usb"])

    assert result.exit_code != 0
    assert "NO_CARD_FOUND" in result.output


def test_push_refuses_when_a_song_fails_validation(repo, monkeypatch):
    _seed_catalog([_synth_entry(), *system_catalog()])
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
    _seed_catalog([_synth_entry(), *system_catalog()])
    _write_song(repo / "songs", "Vellichor", 3)
    transport = _bare_card()
    before = dict(transport._files)
    monkeypatch.setattr(cli, "_transport", transport)

    result = runner.invoke(app, ["push", "--dry-run"])

    assert result.exit_code == 0, result.output
    assert "dry run" in result.output
    assert transport._files == before
    assert not (repo / "system/data/state").exists()


def test_push_reports_orhack_integrity_error_cleanly(repo, monkeypatch):
    # verify_orhack_structure raises rig.push.modules.OrhackIntegrityError,
    # a distinct type from PushError -- must not leak as an uncaught
    # traceback (Ruling #2).
    _seed_catalog([_synth_entry(), *system_catalog()])
    _write_song(repo / "songs", "Vellichor", 3)
    transport = InMemoryTransport()  # no Patches/0RHACK/manifest.txt at all
    monkeypatch.setattr(cli, "_transport", transport)

    result = runner.invoke(app, ["push"])

    assert result.exit_code != 0
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert "ORHACK_NOT_INSTALLED" in result.output


def test_push_no_card_found_is_a_clean_refusal(repo, monkeypatch):
    _seed_catalog([_synth_entry(), *system_catalog()])
    _write_song(repo / "songs", "Vellichor", 3)
    monkeypatch.setattr(cli, "_card_roots", [])  # empty, not None -- never a live OS scan in a test

    result = runner.invoke(app, ["push"])

    assert result.exit_code != 0
    assert "NO_CARD_FOUND" in result.output


def test_push_refuses_hand_renamed_chain_and_names_rename_chain(repo, monkeypatch):
    songs_dir = repo / "songs"
    _seed_catalog([_synth_entry(), *system_catalog()])
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
    _seed_catalog([_synth_entry(), *system_catalog()])
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
    _seed_catalog([_synth_entry(), *system_catalog()])
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
    _seed_catalog([_synth_entry(), *system_catalog()])
    monkeypatch.setattr(cli, "_card_roots", [])

    result = runner.invoke(app, ["pull"])

    assert result.exit_code != 0
    assert "NO_CARD_FOUND" in result.output


def test_pull_ignores_a_card_preset_no_song_claims(repo, monkeypatch):
    # Ruling #1: the repo is authoritative for whether a song exists.
    _seed_catalog([_synth_entry(), *system_catalog()])
    transport = _bare_card()
    transport.write(f"{PRESETS_ROOT}/005-stranger/params.json", b"{}")
    monkeypatch.setattr(cli, "_transport", transport)
    git, _repo_dir = make_git_repo(repo, initial_files={"README.md": b"x\n"})
    gh = FakeGhClient()
    monkeypatch.setattr(cli, "_git", git)
    monkeypatch.setattr(cli, "_gh", gh)

    result = runner.invoke(app, ["pull"])

    assert result.exit_code == 0, result.output
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
    catalog_before = {p: p.read_bytes() for p in Path("system/data/catalog").glob("*.json")}
    lock_before = Path("system/data/modules.lock").read_bytes()

    monkeypatch.setattr(
        cli, "_upgrade_fetcher", lambda requested: ({"warble@warble": _community_entry(param_id="different_amt")}, {})
    )

    result = runner.invoke(app, ["upgrade", "warble@warble"])

    assert result.exit_code != 0
    assert "amount" in result.output
    assert "vellichor" in result.output
    assert {p: p.read_bytes() for p in Path("system/data/catalog").glob("*.json")} == catalog_before
    assert Path("system/data/modules.lock").read_bytes() == lock_before


def test_upgrade_writes_new_catalog_and_lock_when_no_song_is_affected(repo, monkeypatch):
    _seed_catalog([_community_entry(param_id="amt", updated_at="2020-01-01")])
    monkeypatch.setattr(
        cli,
        "_upgrade_fetcher",
        lambda requested: (
            {"warble@warble": _community_entry(param_id="different_amt", updated_at="2021-01-01")},
            {},
        ),
    )

    result = runner.invoke(app, ["upgrade", "warble@warble"])

    assert result.exit_code == 0, result.output
    assert "upgraded: warble@warble" in result.output
    lock = json.loads(Path("system/data/modules.lock").read_text(encoding="utf-8"))
    assert lock["modules"]["warble@warble"]["updated_at"] == "2021-01-01"


def test_upgrade_dry_run_leaves_catalog_and_lock_untouched(repo, monkeypatch):
    _seed_catalog([_community_entry(param_id="amt", updated_at="2020-01-01")])
    catalog_before = {p: p.read_bytes() for p in Path("system/data/catalog").glob("*.json")}
    lock_before = Path("system/data/modules.lock").read_bytes()
    monkeypatch.setattr(
        cli,
        "_upgrade_fetcher",
        lambda requested: (
            {"warble@warble": _community_entry(param_id="different_amt", updated_at="2021-01-01")},
            {},
        ),
    )

    result = runner.invoke(app, ["upgrade", "warble@warble", "--dry-run"])

    assert result.exit_code == 0, result.output
    assert "would upgrade: warble@warble" in result.output
    assert {p: p.read_bytes() for p in Path("system/data/catalog").glob("*.json")} == catalog_before
    assert Path("system/data/modules.lock").read_bytes() == lock_before


def test_upgrade_unknown_module_is_a_clean_refusal(repo):
    _seed_catalog([_community_entry()])
    result = runner.invoke(app, ["upgrade", "nope@nowhere"])
    assert result.exit_code != 0
    assert "UNKNOWN_MODULE" in result.output


def test_upgrade_refuses_a_builtin_module(repo):
    _seed_catalog([_synth_entry(), *system_catalog()])
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
    write_bindings(Path("system/data/state/chains"), "vellichor", {"lead": "A"})

    result = runner.invoke(app, ["rename-chain", "vellichor", "lead", "pads"])

    assert result.exit_code == 0, result.output
    text = (songs_dir / "vellichor.yaml").read_text(encoding="utf-8")
    assert "name: pads" in text
    assert "name: lead" not in text
    bindings = json.loads((Path("system/data/state/chains") / "vellichor.json").read_text(encoding="utf-8"))
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


# --- StoredArchiveModuleSource (push's on-disk ModuleSource) ---------------


def _make_zip(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    return buf.getvalue()


def _stored_module_source(
    modules_dir, archive_bytes: bytes, *, slug: str = "warble", display: str = "Warble", revision: str = "1.0"
):
    """A `StoredArchiveModuleSource` over a real archive written to
    `modules_dir`, with a lock pinning its digest. Returns
    `(module_source, entry)` where `entry.key` is exactly what a real ingest
    of this archive would have produced."""
    entry_key = module_key(display, slug)
    digest = hashlib.sha256(archive_bytes).hexdigest()
    write_archive(modules_dir, slug, revision, archive_bytes)
    lock = {"modules": {entry_key: {"source": slug, "revision": revision, "archive_sha256": digest}}}
    entry = CatalogEntry(
        key=entry_key, source=slug, display=display,
        module_type=f"effects/mod/{entry_key}", category="effects/mod", category_override=None,
        tags=[], params=[],
        version=VersionInfo(updated_at="2019-01-01", file_id=1, archive_sha256=digest, revision=revision),
    )
    return StoredArchiveModuleSource(modules_dir, lock), entry


def test_module_source_fetch_strips_junk_and_keeps_real_files(tmp_path):
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
    module_source, entry = _stored_module_source(tmp_path / "modules", archive_bytes)

    files = module_source.fetch(entry)

    assert files["module.json"] == b'{"display": "Warble", "parameters": []}'
    assert files["module.pd"] == b"#N canvas;"
    assert files["README.md"] == b"hello"
    for junk in ("__MACOSX/somefile.txt", "._module.pd", ".DS_Store", "notes.txt~", "scratch.swp", "lib.dll"):
        assert junk not in files, f"{junk!r} should have been stripped"


def test_module_source_fetch_refuses_a_module_needing_abl_link(tmp_path):
    archive_bytes = _make_zip(
        {
            "module.json": b'{"display": "Warble", "parameters": []}',
            "module.pd": b"#N canvas;",
            "abl_link~.pd_linux": b"binary",
        }
    )
    module_source, entry = _stored_module_source(tmp_path / "modules", archive_bytes)

    with pytest.raises(ModuleSourceUnavailable) as exc_info:
        module_source.fetch(entry)

    assert "abl_link~.pd_linux" in str(exc_info.value)
    assert entry.key in str(exc_info.value)


def test_module_source_fetch_raises_when_the_archive_is_missing(tmp_path):
    modules_dir = tmp_path / "modules"
    modules_dir.mkdir()
    lock = {"modules": {"warble@warble": {"source": "warble", "revision": "1.0", "archive_sha256": "abc"}}}
    entry = CatalogEntry(
        key="warble@warble", source="warble", display="Warble",
        module_type="effects/mod/warble@warble", category="effects/mod", category_override=None,
        tags=[], params=[], version=VersionInfo(revision="1.0"),
    )

    with pytest.raises(ModuleSourceUnavailable) as exc_info:
        StoredArchiveModuleSource(modules_dir, lock).fetch(entry)

    assert "is missing" in str(exc_info.value)
    assert "rig catalog add warble" in str(exc_info.value)


def test_module_source_fetch_refuses_an_archive_that_fails_its_pinned_digest(tmp_path):
    modules_dir = tmp_path / "modules"
    archive_bytes = _make_zip(
        {"module.json": b'{"display": "Warble", "parameters": []}', "module.pd": b"#N canvas;"}
    )
    module_source, entry = _stored_module_source(modules_dir, archive_bytes)
    # A truncated clone or a hand-edited archive: the bytes on disk no longer
    # match what the lock pins, and must never reach the card.
    archive_path(modules_dir, entry.source, "1.0").write_bytes(_make_zip({"module.json": b"{}"}))

    with pytest.raises(ModuleSourceUnavailable) as exc_info:
        module_source.fetch(entry)

    assert "does not match the digest pinned" in str(exc_info.value)
