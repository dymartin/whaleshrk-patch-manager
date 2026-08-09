"""`rig.push.push()` end to end, against `InMemoryTransport`.

Covers every refusal path in Prompt/05-push.md and the seeded-card cases
(rename, delete, currentPreset repair) that need recorded state to exercise
at all -- see that brief's "Verification" section.
"""

from __future__ import annotations

import json

import pytest

from rig.catalog.entry import CatalogEntry
from rig.push.errors import PushError
from rig.push.modules import ModuleSourceUnavailable
from rig.push.runner import push
from rig.push import state as state_io
from rig.push.transact import plan_write_op, stage_files, write_journal
from rig.song.bindings import read_bindings
from rig.song.kits import KitsConfig
from rig.song.model import Chain, ModuleSlot, Song
from rig.transport.memory import InMemoryTransport

from tests.compile_helpers import make_entry, param, system_catalog
from tests.fixture_card import load_fixture_card

PRESETS_ROOT = "data/orhack/presets"


def _bare_card() -> InMemoryTransport:
    """The minimum an ORHACK card needs for push's structural checks to
    pass, built by hand rather than the full fixture -- keeps each test's
    starting state legible and independent of the (large, real) fixture."""
    t = InMemoryTransport()
    t.write("Patches/0RHACK/manifest.txt", b"")
    t.write("data/orhack/rack.json", json.dumps({"currentPreset": "Init"}).encode("utf-8"))
    t.write(f"{PRESETS_ROOT}/Init/params.json", b"{}")
    return t


def _catalog(*entries: CatalogEntry) -> list[CatalogEntry]:
    return [*entries, *system_catalog()]


def _synth_entry() -> CatalogEntry:
    return make_entry(
        "synth@orhack", "orhack", "Synth", "instruments/synth/synth",
        [param("level", id_="lvl", default=50)],
    )


def _song(name: str, program: int, chain_name: str = "lead") -> Song:
    return Song(
        name=name,
        program=program,
        chains=[Chain(name=chain_name, modules=[ModuleSlot(key="synth@orhack")])],
    )


class _NoModuleSource:
    def fetch(self, entry):
        raise ModuleSourceUnavailable("not needed by this test")


def _push(**kwargs):
    kwargs.setdefault("catalog", _catalog(_synth_entry()))
    kwargs.setdefault("lock", {"modules": {}})
    kwargs.setdefault("kits", KitsConfig({}))
    kwargs.setdefault("module_source", _NoModuleSource())
    kwargs.setdefault("verify_manifest", False)
    return push(**kwargs)


def test_first_push_of_one_song_writes_its_preset_and_state(tmp_path):
    transport = _bare_card()
    media_root = tmp_path / "media"
    state_dir = tmp_path / ".rig" / "state"
    song = _song("Vellichor", program=3)

    result = _push(
        songs={"vellichor": song}, selected=None, transport=transport,
        media_root=media_root, state_dir=state_dir,
    )

    assert result.written == ["vellichor"]
    assert transport.exists(f"{PRESETS_ROOT}/003-vellichor/params.json")
    assert state_io.read_meta(state_dir, "vellichor").directory == "003-vellichor"
    assert state_io.read_meta(state_dir, "vellichor").program == 3
    assert state_io.read_params(state_dir, "vellichor") == transport.read(f"{PRESETS_ROOT}/003-vellichor/params.json")
    assert read_bindings(state_dir / "chains", "vellichor") == {"lead": "A"}


def test_recompiling_an_unchanged_song_is_idempotent(tmp_path):
    transport = _bare_card()
    media_root = tmp_path / "media"
    state_dir = tmp_path / ".rig" / "state"
    song = _song("Vellichor", program=3)

    _push(songs={"vellichor": song}, selected=None, transport=transport, media_root=media_root, state_dir=state_dir)
    before = transport.read(f"{PRESETS_ROOT}/003-vellichor/params.json")
    _push(songs={"vellichor": song}, selected=None, transport=transport, media_root=media_root, state_dir=state_dir)
    after = transport.read(f"{PRESETS_ROOT}/003-vellichor/params.json")
    assert before == after


def test_renaming_a_song_renames_its_card_directory(tmp_path):
    transport = _bare_card()
    media_root = tmp_path / "media"
    state_dir = tmp_path / ".rig" / "state"
    song = _song("Vellichor", program=3)
    _push(songs={"vellichor": song}, selected=None, transport=transport, media_root=media_root, state_dir=state_dir)

    renamed_song = _song("Vellichor Reprise", program=3)
    result = _push(
        songs={"vellichor": renamed_song}, selected=None, transport=transport,
        media_root=media_root, state_dir=state_dir,
    )

    assert result.renamed == {"vellichor": ("003-vellichor", "003-vellichor-reprise")}
    assert not transport.exists(f"{PRESETS_ROOT}/003-vellichor")
    assert transport.exists(f"{PRESETS_ROOT}/003-vellichor-reprise/params.json")
    assert state_io.read_meta(state_dir, "vellichor").directory == "003-vellichor-reprise"


def test_retiring_a_song_deletes_its_preset_without_force(tmp_path):
    transport = _bare_card()
    media_root = tmp_path / "media"
    state_dir = tmp_path / ".rig" / "state"
    song = _song("Vellichor", program=3)
    _push(songs={"vellichor": song}, selected=None, transport=transport, media_root=media_root, state_dir=state_dir)

    result = _push(songs={}, selected=None, transport=transport, media_root=media_root, state_dir=state_dir)

    assert result.retired == ["003-vellichor"]
    assert not transport.exists(f"{PRESETS_ROOT}/003-vellichor")
    assert state_io.read_meta(state_dir, "vellichor") is None


def test_retiring_a_song_also_drops_its_chain_bindings(tmp_path):
    # Without this, a later song reusing the same YAML filename stem
    # silently inherits the retired song's name -> letter binding.
    transport = _bare_card()
    media_root = tmp_path / "media"
    state_dir = tmp_path / ".rig" / "state"
    song = _song("Vellichor", program=3)
    _push(songs={"vellichor": song}, selected=None, transport=transport, media_root=media_root, state_dir=state_dir)
    assert read_bindings(state_dir / "chains", "vellichor") == {"lead": "A"}

    _push(songs={}, selected=None, transport=transport, media_root=media_root, state_dir=state_dir)

    assert read_bindings(state_dir / "chains", "vellichor") == {}


def test_unrecorded_preset_refuses_without_force(tmp_path):
    transport = _bare_card()
    transport.write(f"{PRESETS_ROOT}/099-mystery/params.json", b"{}")
    media_root = tmp_path / "media"
    state_dir = tmp_path / ".rig" / "state"

    with pytest.raises(PushError) as exc:
        _push(songs={}, selected=None, transport=transport, media_root=media_root, state_dir=state_dir)
    assert exc.value.code == "UNRECORDED_PRESET"
    assert transport.exists(f"{PRESETS_ROOT}/099-mystery")  # refusal touches nothing


def test_unrecorded_preset_deleted_with_force(tmp_path):
    transport = _bare_card()
    transport.write(f"{PRESETS_ROOT}/099-mystery/params.json", b"{}")
    media_root = tmp_path / "media"
    state_dir = tmp_path / ".rig" / "state"

    result = _push(songs={}, selected=None, transport=transport, media_root=media_root, state_dir=state_dir, force=True)

    assert result.force_deleted == ["099-mystery"]
    assert not transport.exists(f"{PRESETS_ROOT}/099-mystery")


def test_init_is_never_touched_even_with_force(tmp_path):
    transport = _bare_card()
    transport.write(f"{PRESETS_ROOT}/099-mystery/params.json", b"{}")
    media_root = tmp_path / "media"
    state_dir = tmp_path / ".rig" / "state"

    _push(songs={}, selected=None, transport=transport, media_root=media_root, state_dir=state_dir, force=True)

    assert transport.exists(f"{PRESETS_ROOT}/Init/params.json")


def test_gap_placeholders_fill_between_programs_and_shrink_as_gaps_close(tmp_path):
    transport = _bare_card()
    media_root = tmp_path / "media"
    state_dir = tmp_path / ".rig" / "state"
    songs = {"a": _song("A", program=0), "b": _song("B", program=3)}

    result = _push(songs=songs, selected=None, transport=transport, media_root=media_root, state_dir=state_dir)
    assert result.placeholders_added == [1, 2]
    assert transport.exists(f"{PRESETS_ROOT}/001/params.json")
    assert transport.exists(f"{PRESETS_ROOT}/002/params.json")

    songs["c"] = _song("C", program=1, chain_name="pad")
    result2 = _push(songs=songs, selected=None, transport=transport, media_root=media_root, state_dir=state_dir)
    assert result2.placeholders_removed == [1]
    assert not transport.exists(f"{PRESETS_ROOT}/001")
    assert transport.exists(f"{PRESETS_ROOT}/002/params.json")


def test_selective_push_refuses_when_lock_changed_since_last_push(tmp_path):
    transport = _bare_card()
    media_root = tmp_path / "media"
    state_dir = tmp_path / ".rig" / "state"
    song = _song("Vellichor", program=3)
    lock_v1 = {"modules": {}}
    lock_v2 = {"modules": {"warble@warble": {"updated_at": "x", "file_id": 1, "archive_sha256": "y"}}}

    _push(songs={"vellichor": song}, selected=None, transport=transport, media_root=media_root, state_dir=state_dir, lock=lock_v1)

    with pytest.raises(PushError) as exc:
        _push(
            songs={"vellichor": song}, selected={"vellichor"}, transport=transport,
            media_root=media_root, state_dir=state_dir, lock=lock_v2,
        )
    assert exc.value.code == "LOCK_CHANGED_SELECTIVE_PUSH"


def test_full_push_is_not_refused_by_a_lock_change(tmp_path):
    transport = _bare_card()
    media_root = tmp_path / "media"
    state_dir = tmp_path / ".rig" / "state"
    song = _song("Vellichor", program=3)
    lock_v1 = {"modules": {}}
    lock_v2 = {"modules": {}}  # different object, same content -- also fine

    _push(songs={"vellichor": song}, selected=None, transport=transport, media_root=media_root, state_dir=state_dir, lock=lock_v1)
    # A full (non-selective) push is never refused for this reason.
    _push(songs={"vellichor": song}, selected=None, transport=transport, media_root=media_root, state_dir=state_dir, lock=lock_v2)


def test_module_unavailable_and_uninstalled_is_a_hard_error(tmp_path):
    transport = _bare_card()
    media_root = tmp_path / "media"
    state_dir = tmp_path / ".rig" / "state"
    community = make_entry("warble@warble", "warble", "Warble", "effects/mod/warble@warble", [])
    lock = {"modules": {"warble@warble": {"updated_at": "x", "file_id": 1, "archive_sha256": "y"}}}

    with pytest.raises(PushError) as exc:
        _push(
            songs={}, selected=None, transport=transport, media_root=media_root, state_dir=state_dir,
            catalog=_catalog(_synth_entry(), community), lock=lock,
        )
    assert exc.value.code == "MODULE_UNAVAILABLE"


def test_missing_community_module_is_actually_installed_on_the_card(tmp_path):
    transport = _bare_card()
    media_root = tmp_path / "media"
    state_dir = tmp_path / ".rig" / "state"
    community = make_entry("warble@warble", "warble", "Warble", "effects/mod/warble@warble", [])
    lock = {"modules": {"warble@warble": {"updated_at": "x", "file_id": 1, "archive_sha256": "y"}}}

    class _WorkingModuleSource:
        def fetch(self, entry):
            return {"module.json": b"{}", "module.pd": b"patch"}

    result = _push(
        songs={}, selected=None, transport=transport, media_root=media_root, state_dir=state_dir,
        catalog=_catalog(_synth_entry(), community), lock=lock, module_source=_WorkingModuleSource(),
    )

    assert result.modules_installed == ["warble@warble"]
    install_dir = "media/orhack/user-modules/effects/mod/warble@warble"
    assert transport.read(f"{install_dir}/module.json") == b"{}"
    assert transport.read(f"{install_dir}/module.pd") == b"patch"


def test_mismatched_community_module_is_actually_replaced_on_the_card(tmp_path):
    transport = _bare_card()
    install_dir = "media/orhack/user-modules/effects/mod/warble@warble"
    transport.write(f"{install_dir}/module.json", b"{OLD}")
    media_root = tmp_path / "media"
    state_dir = tmp_path / ".rig" / "state"
    community = make_entry("warble@warble", "warble", "Warble", "effects/mod/warble@warble", [])
    lock = {"modules": {"warble@warble": {"updated_at": "x", "file_id": 1, "archive_sha256": "y"}}}

    class _WorkingModuleSource:
        def fetch(self, entry):
            return {"module.json": b"{NEW}"}

    result = _push(
        songs={}, selected=None, transport=transport, media_root=media_root, state_dir=state_dir,
        catalog=_catalog(_synth_entry(), community), lock=lock, module_source=_WorkingModuleSource(),
    )

    assert result.modules_replaced == ["warble@warble"]
    assert transport.read(f"{install_dir}/module.json") == b"{NEW}"


def test_uncommanded_chain_rename_refuses(tmp_path):
    transport = _bare_card()
    media_root = tmp_path / "media"
    state_dir = tmp_path / ".rig" / "state"
    song = _song("Vellichor", program=3, chain_name="lead")
    _push(songs={"vellichor": song}, selected=None, transport=transport, media_root=media_root, state_dir=state_dir)

    hand_renamed = _song("Vellichor", program=3, chain_name="lead2")
    with pytest.raises(PushError) as exc:
        _push(songs={"vellichor": hand_renamed}, selected=None, transport=transport, media_root=media_root, state_dir=state_dir)
    assert exc.value.code == "UNCOMMANDED_CHAIN_RENAME"
    assert "rig rename-chain vellichor lead lead2" in str(exc.value)


def test_dry_run_leaves_card_and_state_untouched(tmp_path):
    transport = _bare_card()
    media_root = tmp_path / "media"
    state_dir = tmp_path / ".rig" / "state"
    song = _song("Vellichor", program=3)
    before = dict(transport._files)  # snapshot

    result = _push(songs={"vellichor": song}, selected=None, transport=transport, media_root=media_root, state_dir=state_dir, dry_run=True)

    assert result.dry_run is True
    assert result.written == ["vellichor"]
    assert transport._files == before
    assert not state_dir.exists()


def test_dry_run_refuses_rather_than_recover_a_pending_transaction(tmp_path):
    # recover_pending_transaction performs real renames/deletes/flushes --
    # --dry-run must never trigger it (Prompt/05-push.md "--dry-run",
    # decision #59: "touches nothing").
    transport = _bare_card()
    media_root = tmp_path / "media"
    state_dir = tmp_path / ".rig" / "state"
    op = plan_write_op(0, f"{PRESETS_ROOT}/003-vellichor", {"params.json": b"{NEW}"})
    stage_files(transport, op.staged, {"params.json": b"{NEW}"})
    write_journal(transport, [op])
    before = dict(transport._files)

    song = _song("Vellichor", program=3)
    with pytest.raises(PushError) as exc:
        _push(
            songs={"vellichor": song}, selected=None, transport=transport, media_root=media_root,
            state_dir=state_dir, dry_run=True,
        )

    assert exc.value.code == "PENDING_TRANSACTION_DRY_RUN"
    assert transport._files == before  # untouched -- the journal is still exactly as seeded


def test_current_preset_repaired_when_it_pointed_at_a_retired_preset(tmp_path):
    transport = _bare_card()
    media_root = tmp_path / "media"
    state_dir = tmp_path / ".rig" / "state"
    songs = {"a": _song("A", program=0), "b": _song("B", program=1)}
    _push(songs=songs, selected=None, transport=transport, media_root=media_root, state_dir=state_dir)
    transport.write("data/orhack/rack.json", json.dumps({"currentPreset": "000-a"}).encode("utf-8"))

    result = _push(songs={"b": songs["b"]}, selected=None, transport=transport, media_root=media_root, state_dir=state_dir)

    assert result.current_preset_repaired == "001-b"
    rack = json.loads(transport.read("data/orhack/rack.json").decode("utf-8"))
    assert rack["currentPreset"] == "001-b"


def test_current_preset_repaired_to_init_when_no_managed_preset_survives(tmp_path):
    transport = _bare_card()
    media_root = tmp_path / "media"
    state_dir = tmp_path / ".rig" / "state"
    songs = {"a": _song("A", program=0)}
    _push(songs=songs, selected=None, transport=transport, media_root=media_root, state_dir=state_dir)
    transport.write("data/orhack/rack.json", json.dumps({"currentPreset": "000-a"}).encode("utf-8"))

    result = _push(songs={}, selected=None, transport=transport, media_root=media_root, state_dir=state_dir)

    assert result.current_preset_repaired == "Init"


def test_current_preset_left_alone_when_it_still_resolves(tmp_path):
    transport = _bare_card()
    media_root = tmp_path / "media"
    state_dir = tmp_path / ".rig" / "state"
    songs = {"a": _song("A", program=0), "b": _song("B", program=1)}
    _push(songs=songs, selected=None, transport=transport, media_root=media_root, state_dir=state_dir)
    transport.write("data/orhack/rack.json", json.dumps({"currentPreset": "000-a"}).encode("utf-8"))

    result = _push(songs={"a": songs["a"]}, selected={"a"}, transport=transport, media_root=media_root, state_dir=state_dir)

    assert result.current_preset_repaired is None
    rack = json.loads(transport.read("data/orhack/rack.json").decode("utf-8"))
    assert rack["currentPreset"] == "000-a"


def test_full_manifest_verification_and_orphan_cleanup_against_the_real_fixture_card(tmp_path):
    # The frozen, SHA-256-verified ORHACK 0.52b tree (docs/platform/README.md)
    # -- exercises verify_orhack_manifest's real 2,353-entry walk inside the
    # orchestrator, not just the standalone function, and the fixture's own
    # shipped "jam" preset as a genuine unrecorded-on-device preset.
    transport = InMemoryTransport()
    load_fixture_card(transport)
    media_root = tmp_path / "media"
    state_dir = tmp_path / ".rig" / "state"

    with pytest.raises(PushError) as exc:
        _push(
            songs={}, selected=None, transport=transport, media_root=media_root,
            state_dir=state_dir, verify_manifest=True,
        )
    assert exc.value.code == "UNRECORDED_PRESET"
    assert "jam" in str(exc.value)

    result = _push(
        songs={}, selected=None, transport=transport, media_root=media_root,
        state_dir=state_dir, verify_manifest=True, force=True,
    )
    assert result.force_deleted == ["jam"]
    assert transport.exists(f"{PRESETS_ROOT}/Init/params.json")
    assert not transport.exists(f"{PRESETS_ROOT}/jam")
