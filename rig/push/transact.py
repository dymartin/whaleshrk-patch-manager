"""Step 7 of push: stage, swap, verify, recover.

A batch of "root ops" -- one per preset directory or media mirror group --
each independently staged, then swapped in two passes: every live directory
renamed to a backup, then every staged directory renamed into place. Global
atomicity is impossible (docs/decisions.md #44: presets and positional media
are separate fixed roots), so a journal plus idempotent per-root recovery is
the strongest available guarantee.

`_ensure_swapped` is the only place that mutates a root, and it is written
to be safe to call twice: given the state an interruption left a root in, it
either finishes the swap or discovers there is nothing left to do. That is
what lets `recover_pending_transaction` reuse the exact same code path as a
fresh push (docs/workflows/push.md: "read the journal and either complete
or restore, deterministically") instead of a separate, harder-to-trust
recovery implementation.

Journal and staging live under `.rig-push/`, a card-relative path this tool
reserves for itself -- never inside `data/orhack/presets/` or a mirrored
media directory, so a partially-written stage is never mistaken for real
content.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Optional

from rig.push.fsutil import list_files_recursive
from rig.push.hashing import hash_bytes, per_file_hashes
from rig.transport.base import Transport

JOURNAL_PATH = ".rig-push/journal.json"
STAGING_ROOT = ".rig-push/staging"
BACKUP_SUFFIX = ".rig-push-backup"


class PushTransactionError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class RootOp:
    """One directory this transaction will replace or remove.

    `staged` is None for a "delete" op -- there is no new content, only the
    live directory to move aside. `manifest` is the staged content's
    per-file sha256, empty for "delete" (a deletion verifies by absence,
    not by hash).
    """

    id: int
    kind: str  # "write" | "delete"
    live: str
    backup: str
    staged: Optional[str]
    manifest: dict[str, str]

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "live": self.live,
            "backup": self.backup,
            "staged": self.staged,
            "manifest": self.manifest,
        }

    @staticmethod
    def from_dict(data: dict) -> "RootOp":
        return RootOp(
            id=data["id"],
            kind=data["kind"],
            live=data["live"],
            backup=data["backup"],
            staged=data.get("staged"),
            manifest=data.get("manifest", {}),
        )


def plan_write_op(op_id: int, live_path: str, files: dict[str, bytes]) -> RootOp:
    return RootOp(
        id=op_id,
        kind="write",
        live=live_path,
        backup=f"{live_path}{BACKUP_SUFFIX}",
        staged=f"{STAGING_ROOT}/{op_id}",
        manifest=per_file_hashes(files),
    )


def plan_delete_op(op_id: int, live_path: str) -> RootOp:
    return RootOp(id=op_id, kind="delete", live=live_path, backup=f"{live_path}{BACKUP_SUFFIX}", staged=None, manifest={})


def stage_files(transport: Transport, staged_path: str, files: dict[str, bytes]) -> None:
    for rel, content in files.items():
        transport.write(f"{staged_path}/{rel}", content)


def write_journal(transport: Transport, ops: list[RootOp]) -> None:
    payload = json.dumps({"roots": [op.to_dict() for op in ops]}, indent=2, sort_keys=True)
    transport.write(JOURNAL_PATH, payload.encode("utf-8"))


def read_journal(transport: Transport) -> Optional[list[RootOp]]:
    if not transport.exists(JOURNAL_PATH):
        return None
    data = json.loads(transport.read(JOURNAL_PATH).decode("utf-8"))
    return [RootOp.from_dict(d) for d in data["roots"]]


def delete_journal(transport: Transport) -> None:
    if transport.exists(JOURNAL_PATH):
        transport.delete(JOURNAL_PATH)


def _ensure_swapped(transport: Transport, op: RootOp) -> None:
    """Bring one root to "swapped, pending verification" from whatever
    state an interruption left it in. Idempotent -- safe to call on a root
    that is already there."""
    live_exists = transport.exists(op.live)
    backup_exists = transport.exists(op.backup)
    staged_exists = op.staged is not None and transport.exists(op.staged)

    if op.kind == "write":
        # `staged_exists` cannot be trusted alone: an empty desired file map
        # (e.g. a media group whose repo folder currently has no files)
        # never materialises a staged directory at all -- `Transport.write`
        # is what creates a directory entry, and zero files means zero
        # calls to it. So "nothing to move in" is a legitimate target state
        # for a write op, not evidence the op never ran.
        if live_exists and backup_exists and staged_exists:
            raise PushTransactionError(
                "TRANSACTION_INCONSISTENT",
                f"{op.live}: live, backup and staged directories are all present at once -- "
                "cannot determine which is authoritative; card needs manual inspection",
            )
        if backup_exists and live_exists:
            # Both renames already completed; only cleanup (delete the
            # backup) is still pending -- not an inconsistency.
            return
        if backup_exists:  # implies not live_exists: interrupted after the first rename
            if staged_exists:
                transport.rename(op.staged, op.live)
            return
        if live_exists:  # implies not backup_exists: nothing touched yet
            transport.rename(op.live, op.backup)
            if staged_exists:
                transport.rename(op.staged, op.live)
            return
        # Neither live nor backup exists: either a brand-new root, or an
        # already-completed-and-cleaned prior run.
        if staged_exists:
            transport.rename(op.staged, op.live)
        return

    # kind == "delete"
    if live_exists and not backup_exists:
        transport.rename(op.live, op.backup)
    # else: already moved aside (or never existed) -- pending cleanup only.


def _verify(transport: Transport, op: RootOp) -> bool:
    if op.kind == "delete":
        return not transport.exists(op.live)
    # An empty manifest (the desired content is zero files) verifies
    # against an absent live directory too -- `list_files_recursive`
    # returns `[]` for both "empty" and "missing", the same equivalence
    # `Transport.list` documents everywhere else in this codebase.
    actual_paths = list_files_recursive(transport, op.live)
    if set(actual_paths) != set(op.manifest):
        return False
    return all(hash_bytes(transport.read(f"{op.live}/{rel}")) == digest for rel, digest in op.manifest.items())


def _restore(transport: Transport, op: RootOp) -> None:
    """Undo a swap that failed verification: discard the bad live content,
    if any, and put the backup back. Only reachable if a directory rename
    left corrupted content behind -- see `rig.transport.usb.flush`'s
    docstring for the same evidentiary limit on what this tool can verify
    without a hardware feedback channel."""
    if transport.exists(op.backup):
        if transport.exists(op.live):
            transport.delete(op.live)
        transport.rename(op.backup, op.live)


def _cleanup(transport: Transport, op: RootOp) -> None:
    if transport.exists(op.backup):
        transport.delete(op.backup)
    if op.staged is not None and transport.exists(op.staged):
        transport.delete(op.staged)


@dataclass(frozen=True)
class TransactionResult:
    completed: list[str]  # live paths successfully swapped and verified


def run_transaction(transport: Transport, ops: list[RootOp]) -> TransactionResult:
    """Execute every root op: journal, swap, flush, verify, cleanup.

    Also the recovery path -- `recover_pending_transaction` calls this with
    the ops read back from an existing journal, and `_ensure_swapped` being
    idempotent is what makes that safe to resume from any point.
    """
    if not ops:
        delete_journal(transport)
        return TransactionResult(completed=[])

    write_journal(transport, ops)
    transport.flush()

    for op in ops:
        _ensure_swapped(transport, op)
    transport.flush()

    failed = [op for op in ops if not _verify(transport, op)]
    if failed:
        for op in ops:
            _restore(transport, op)
        transport.flush()
        delete_journal(transport)
        names = ", ".join(op.live for op in failed)
        raise PushTransactionError(
            "TRANSACTION_VERIFY_FAILED",
            f"post-swap verification failed for: {names} -- backups restored, card unchanged",
        )

    for op in ops:
        _cleanup(transport, op)
    delete_journal(transport)
    transport.flush()
    return TransactionResult(completed=[op.live for op in ops])


def recover_pending_transaction(transport: Transport) -> Optional[TransactionResult]:
    """Call before any new push begins. If a previous run's journal is
    still on the card, finish or restore it deterministically first
    (docs/workflows/push.md "Transact") -- returns None if there was
    nothing to recover."""
    ops = read_journal(transport)
    if ops is None:
        return None
    return run_transaction(transport, ops)
