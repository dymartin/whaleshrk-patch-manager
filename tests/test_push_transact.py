"""Staged journal, backups, verify, and interrupted-transaction recovery.

See rig/push/transact.py and docs/workflows/push.md "Transact". The
interrupted-recovery tests build the on-card state an interruption would
leave directly (a fixture), rather than asserting on a narrative about what
"should" happen mid-run -- see Prompt/05-push.md "Method".
"""

from __future__ import annotations

import pytest

from rig.push.transact import (
    JOURNAL_PATH,
    PushTransactionError,
    RootOp,
    _ensure_swapped,
    plan_delete_op,
    plan_write_op,
    recover_pending_transaction,
    run_transaction,
    stage_files,
    write_journal,
)
from rig.transport.memory import InMemoryTransport

PRESETS_ROOT = "data/orhack/presets"


def _staged_write(transport, op_id, live_path, files):
    op = plan_write_op(op_id, live_path, files)
    stage_files(transport, op.staged, files)
    return op


def test_write_op_installs_staged_content_and_cleans_up():
    transport = InMemoryTransport()
    op = _staged_write(transport, 0, "presets/song", {"params.json": b"{}"})
    result = run_transaction(transport, [op])
    assert result.completed == ["presets/song"]
    assert transport.read("presets/song/params.json") == b"{}"
    assert not transport.exists(op.backup)
    assert not transport.exists(op.staged)
    assert not transport.exists(JOURNAL_PATH)


def test_write_op_replaces_existing_live_content():
    transport = InMemoryTransport()
    transport.write("presets/song/params.json", b"{OLD}")
    transport.write("presets/song/extra-sidecar.txt", b"stale")
    op = _staged_write(transport, 0, "presets/song", {"params.json": b"{NEW}"})
    run_transaction(transport, [op])
    assert transport.read("presets/song/params.json") == b"{NEW}"
    # Mirrored, deletions included: the old sidecar the new content didn't
    # carry forward must not survive the swap.
    assert not transport.exists("presets/song/extra-sidecar.txt")


def test_delete_op_removes_the_live_directory():
    transport = InMemoryTransport()
    transport.write("presets/gone/params.json", b"{}")
    op = plan_delete_op(0, "presets/gone")
    result = run_transaction(transport, [op])
    assert result.completed == ["presets/gone"]
    assert not transport.exists("presets/gone")
    assert not transport.exists(op.backup)


def test_multiple_roots_all_swap_together():
    transport = InMemoryTransport()
    transport.write("presets/keep-old/params.json", b"{OLD}")
    op_write = _staged_write(transport, 0, "presets/a", {"params.json": b"{A}"})
    op_delete = plan_delete_op(1, "presets/keep-old")
    run_transaction(transport, [op_write, op_delete])
    assert transport.read("presets/a/params.json") == b"{A}"
    assert not transport.exists("presets/keep-old")


def test_failed_verification_restores_the_backup_and_raises():
    transport = InMemoryTransport()
    transport.write("presets/song/params.json", b"{OLD}")
    op = _staged_write(transport, 0, "presets/song", {"params.json": b"{NEW}"})
    # Corrupt the manifest so post-swap verification cannot pass -- stands
    # in for the "a directory rename left corrupted content" case, since
    # InMemoryTransport's own renames cannot actually corrupt anything.
    tampered = RootOp(
        id=op.id, kind=op.kind, live=op.live, backup=op.backup, staged=op.staged,
        manifest={"params.json": "0" * 64},
    )
    with pytest.raises(PushTransactionError) as exc:
        run_transaction(transport, [tampered])
    assert exc.value.code == "TRANSACTION_VERIFY_FAILED"
    assert transport.read("presets/song/params.json") == b"{OLD}"
    assert not transport.exists(JOURNAL_PATH)
    assert not transport.exists(op.backup)


def test_failed_verification_of_one_root_rolls_back_every_healthy_sibling_too():
    # run_transaction restores every op when any op fails verification -- a
    # real push always has several roots (several songs, placeholders,
    # media groups), so a single-op test can't actually exercise that
    # "every", only "the one op that failed".
    transport = InMemoryTransport()
    transport.write("presets/a/params.json", b"{A-OLD}")
    transport.write("presets/b/params.json", b"{B-OLD}")
    transport.write("presets/c/params.json", b"{C-OLD}")
    op_a = _staged_write(transport, 0, "presets/a", {"params.json": b"{A-NEW}"})
    op_b = _staged_write(transport, 1, "presets/b", {"params.json": b"{B-NEW}"})
    op_c_delete = plan_delete_op(2, "presets/c")

    # Corrupt only op_b's manifest -- a and c-delete are otherwise healthy.
    tampered_b = RootOp(
        id=op_b.id, kind=op_b.kind, live=op_b.live, backup=op_b.backup, staged=op_b.staged,
        manifest={"params.json": "0" * 64},
    )

    with pytest.raises(PushTransactionError) as exc:
        run_transaction(transport, [op_a, tampered_b, op_c_delete])
    assert exc.value.code == "TRANSACTION_VERIFY_FAILED"

    # Every root restored, not just the one that failed.
    assert transport.read("presets/a/params.json") == b"{A-OLD}"
    assert transport.read("presets/b/params.json") == b"{B-OLD}"
    assert transport.read("presets/c/params.json") == b"{C-OLD}"
    assert not transport.exists(op_a.backup)
    assert not transport.exists(op_b.backup)
    assert not transport.exists(op_c_delete.backup)
    assert not transport.exists(JOURNAL_PATH)


def test_no_extraneous_params_json_ever_appears_under_presets_during_a_swap():
    # mec admits any presets/ subdirectory holding a params.json
    # (docs/platform/state.md) as a real, indexed preset. A backup or
    # staging artifact left there during an interrupted swap would be an
    # admissible extra preset and shift every later Program Change index --
    # assert the invariant directly against a mid-swap snapshot (the exact
    # state an interruption would leave), not just where `op.backup`
    # happens to point.
    transport = InMemoryTransport()
    transport.write(f"{PRESETS_ROOT}/003-vellichor/params.json", b"{OLD}")
    transport.write(f"{PRESETS_ROOT}/004-retiring/params.json", b"{GONE}")
    write_op = _staged_write(transport, 0, f"{PRESETS_ROOT}/003-vellichor", {"params.json": b"{NEW}"})
    delete_op = plan_delete_op(1, f"{PRESETS_ROOT}/004-retiring")

    for op in (write_op, delete_op):
        _ensure_swapped(transport, op)  # mid-swap: what an interruption right here leaves behind

    real_presets = {"003-vellichor"}
    for name in transport.list(PRESETS_ROOT):
        if name in real_presets:
            continue
        assert not transport.exists(f"{PRESETS_ROOT}/{name}/params.json"), (
            f"{PRESETS_ROOT}/{name} holds params.json but is not a real preset -- would be "
            "an admissible extra Program Change vector slot"
        )


def test_no_ops_is_a_no_op():
    transport = InMemoryTransport()
    result = run_transaction(transport, [])
    assert result.completed == []


def test_recover_with_no_journal_present_returns_none():
    transport = InMemoryTransport()
    assert recover_pending_transaction(transport) is None


def test_recover_interrupted_between_backup_and_install_completes_forward():
    # Fixture: a previous run got as far as "rename live -> backup" for one
    # root and was killed before "rename staged -> live". State: live
    # missing, backup holds the old content, staged holds the new content,
    # journal still on the card.
    transport = InMemoryTransport()
    op = plan_write_op(0, "presets/song", {"params.json": b"{NEW}"})
    stage_files(transport, op.staged, {"params.json": b"{NEW}"})
    transport.write(op.backup + "/params.json", b"{OLD}")
    write_journal(transport, [op])

    result = recover_pending_transaction(transport)

    assert result.completed == ["presets/song"]
    assert transport.read("presets/song/params.json") == b"{NEW}"
    assert not transport.exists(op.backup)
    assert not transport.exists(op.staged)
    assert not transport.exists(JOURNAL_PATH)


def test_recover_before_any_rename_happened_completes_forward():
    # Fixture: journal was written (staging finished and flushed) but the
    # process died before the first rename -- live still at its original
    # name, no backup yet, staged content sitting ready.
    transport = InMemoryTransport()
    transport.write("presets/song/params.json", b"{OLD}")
    op = plan_write_op(0, "presets/song", {"params.json": b"{NEW}"})
    stage_files(transport, op.staged, {"params.json": b"{NEW}"})
    write_journal(transport, [op])

    result = recover_pending_transaction(transport)

    assert result.completed == ["presets/song"]
    assert transport.read("presets/song/params.json") == b"{NEW}"
    assert not transport.exists(op.backup)


def test_recover_after_swap_but_before_cleanup_finishes_cleanup():
    # Fixture: both renames completed (live now holds new content) but the
    # process died before deleting the backup and the journal.
    transport = InMemoryTransport()
    op = plan_write_op(0, "presets/song", {"params.json": b"{NEW}"})
    transport.write("presets/song/params.json", b"{NEW}")
    transport.write(op.backup + "/params.json", b"{OLD}")
    write_journal(transport, [op])

    result = recover_pending_transaction(transport)

    assert result.completed == ["presets/song"]
    assert transport.read("presets/song/params.json") == b"{NEW}"
    assert not transport.exists(op.backup)
    assert not transport.exists(JOURNAL_PATH)


def test_recover_interrupted_delete_completes_forward():
    transport = InMemoryTransport()
    op = plan_delete_op(0, "presets/gone")
    transport.write(op.backup + "/params.json", b"{}")  # already moved aside
    write_journal(transport, [op])

    result = recover_pending_transaction(transport)

    assert result.completed == ["presets/gone"]
    assert not transport.exists("presets/gone")
    assert not transport.exists(op.backup)


def test_recover_leaves_an_unrelated_root_untouched():
    transport = InMemoryTransport()
    transport.write("presets/untouched/params.json", b"{SAFE}")
    op = plan_write_op(0, "presets/song", {"params.json": b"{NEW}"})
    stage_files(transport, op.staged, {"params.json": b"{NEW}"})
    transport.write(op.backup + "/params.json", b"{OLD}")
    write_journal(transport, [op])

    recover_pending_transaction(transport)

    assert transport.read("presets/untouched/params.json") == b"{SAFE}"
