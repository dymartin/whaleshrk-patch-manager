"""`push()` -- the orchestrator that composes every other module in this
package into the sequence `docs/workflows/push.md` describes.

See that doc and `Prompt/05-push.md` for the numbered steps this function's
body follows in order. Every refusal raises `rig.push.errors.PushError` (or,
for card detection, the existing `rig.transport.CardDetectionError`; for a
failed swap, `rig.push.transact.PushTransactionError`; for ORHACK itself
missing or not matching its manifest, `rig.push.modules.OrhackIntegrityError`,
raised by step 2a's `verify_orhack_structure`/`verify_orhack_manifest` on
every push) -- never a downgrade to a warning (Ruling #3).

Precondition this function does not re-check: every song in `songs` is
already schema- and catalog-valid (`rig.song.validate.validate_songs` has
run, so capacity limits and the "one song per program" rule already hold).
Push's own job starts where validation ends -- comparing repo state against
the card.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

from rig.catalog.entry import CatalogEntry
from rig.compile import (
    CompileError,
    build_placeholder,
    compile_song,
    format_program_prefix,
)
from rig.push.errors import PushError
from rig.push.media import build_media_plan
from rig.push.modules import (
    ModuleSource,
    module_install_dir,
    plan_module_reconciliation,
    verify_orhack_manifest,
    verify_orhack_structure,
)
from rig.push.plan import (
    Classification,
    classify_card_presets,
    detect_chain_rename,
    chain_rename_message,
    gap_programs,
    is_placeholder_directory,
)
from rig.push.state import (
    LastPushedMeta,
    hash_lock,
    read_all_meta,
    read_recorded_lock_hash,
    remove_last_pushed,
    write_last_pushed,
    write_recorded_lock_hash,
)
from rig.push.transact import (
    RootOp,
    plan_delete_op,
    plan_write_op,
    read_journal,
    recover_pending_transaction,
    run_transaction,
    stage_files,
)
from rig.song.bindings import read_bindings, remove_bindings, write_bindings
from rig.song.kits import KitsConfig
from rig.song.letters import ChainSlots, LetterAssignmentError, assign_letters
from rig.song.model import Song
from rig.transport.base import Transport
from rig.transport.card import INIT_PRESET_NAME, PRESETS_ROOT, resolve_card

RACK_JSON_PATH = "data/orhack/rack.json"


@dataclass(frozen=True)
class PushResult:
    dry_run: bool
    written: list[str] = field(default_factory=list)  # song ids
    renamed: dict[str, tuple[str, str]] = field(default_factory=dict)  # song id -> (old dir, new dir)
    retired: list[str] = field(default_factory=list)  # directory names deleted: song file gone
    force_deleted: list[str] = field(default_factory=list)  # directory names deleted by --force
    placeholders_added: list[int] = field(default_factory=list)
    placeholders_removed: list[int] = field(default_factory=list)
    modules_installed: list[str] = field(default_factory=list)  # catalog keys
    modules_replaced: list[str] = field(default_factory=list)
    media_groups_written: list[str] = field(default_factory=list)
    current_preset_repaired: Optional[str] = None


def _song_id_by_directory(last_pushed_directories: dict[str, str]) -> dict[str, str]:
    return {directory: song_id for song_id, directory in last_pushed_directories.items()}


def _program_of(directory: str) -> Optional[int]:
    if len(directory) < 3 or not directory[:3].isdigit():
        return None
    return int(directory[:3])


def push(
    *,
    songs: dict[str, Song],
    selected: Optional[set[str]],
    catalog: list[CatalogEntry],
    lock: dict,
    kits: KitsConfig,
    media_root: Path,
    state_dir: Path,
    module_source: ModuleSource,
    transport: Optional[Transport] = None,
    roots: Optional[Iterable[Path]] = None,
    force: bool = False,
    dry_run: bool = False,
    verify_manifest: bool = True,
) -> PushResult:
    # Step 1: resolve the card.
    if transport is None:
        transport = resolve_card(roots)  # raises CardDetectionError -- never picks silently

    # `--dry-run` must touch nothing (Prompt/05-push.md "--dry-run", decision
    # #59) -- recovering an interrupted transaction performs real renames,
    # deletes and flushes, so a dry-run cannot be allowed to trigger it.
    # Refuse instead of reporting a "planned" change set the run never
    # actually computed against a settled card.
    if dry_run and read_journal(transport) is not None:
        raise PushError(
            "PENDING_TRANSACTION_DRY_RUN",
            "a previous push was interrupted and left a pending transaction on this card -- "
            "--dry-run cannot safely inspect it without completing or restoring it first. "
            "Run `rig push` without --dry-run to recover, then retry.",
        )

    # Recover any interrupted transaction before doing anything else.
    recover_pending_transaction(transport)  # raises PushTransactionError if a swap cannot be verified

    # Step 2a: verify ORHACK itself. Never installed or repaired (decision
    # #45). Structure is cheap and always checked; the full 2,353-entry
    # sha1 manifest walk is the "optionally" the brief describes.
    verify_orhack_structure(transport)
    if verify_manifest:
        verify_orhack_manifest(transport)

    selected_ids = set(songs) if selected is None else set(selected)
    is_selective = selected is not None

    # Step 2b: reconcile community modules against the lock, repo-wide --
    # never scoped to `selected_ids` (decision #57).
    current_lock_hash = hash_lock(lock)
    recorded_lock_hash = read_recorded_lock_hash(state_dir)
    if is_selective and recorded_lock_hash is not None and recorded_lock_hash != current_lock_hash:
        raise PushError(
            "LOCK_CHANGED_SELECTIVE_PUSH",
            "`system/data/modules.lock` changed since the last push -- module reconciliation is "
            "repo-wide and cannot be scoped to a song selection. Rerun `rig push` with no "
            "song arguments.",
        )

    locked_keys = set(lock.get("modules", {}))
    community_entries = [e for e in catalog if e.source != "orhack" and e.key in locked_keys]
    reconcile = plan_module_reconciliation(transport, community_entries, module_source)
    if reconcile.unavailable:
        names = ", ".join(sorted(e.key for e in reconcile.unavailable))
        raise PushError(
            "MODULE_UNAVAILABLE",
            f"module(s) {names} are named in `system/data/modules.lock` but their archive in "
            "`system/modules/` is missing, fails its pinned digest, or no longer holds the module -- "
            "the compiled preset would reference a moduleType that never resolves",
        )

    # Step 3: compile every selected song. Chain-rename detection (step 5)
    # happens per song, before its letters are assigned, since a rename
    # would otherwise just get a fresh letter silently.
    chains_state_dir = state_dir / "chains"
    last_pushed_meta = read_all_meta(state_dir)
    last_pushed_directories = {sid: meta.directory for sid, meta in last_pushed_meta.items()}

    compiled_by_song: dict[str, tuple[Song, object]] = {}
    new_directory_by_song: dict[str, str] = {}
    letters_by_song: dict[str, dict[str, str]] = {}

    for song_id in sorted(selected_ids):
        song = songs[song_id]
        recorded_bindings = read_bindings(chains_state_dir, song_id)

        suspect = detect_chain_rename(song, recorded_bindings)
        if suspect is not None:
            raise PushError("UNCOMMANDED_CHAIN_RENAME", chain_rename_message(song_id, suspect))

        chain_slots = [ChainSlots(name=c.name, slot_count=len(c.modules)) for c in song.chains]
        try:
            letters = assign_letters(chain_slots, recorded_bindings)
        except LetterAssignmentError as exc:
            raise CompileError(exc.code, str(exc)) from exc
        letters_by_song[song_id] = letters

        compiled = compile_song(song, catalog=catalog, kits=kits, media_root=media_root, bindings=recorded_bindings)
        compiled_by_song[song_id] = (song, compiled)
        new_directory_by_song[song_id] = f"{format_program_prefix(song.program)}-{compiled.directory}"

    # Step 4: classify every card preset.
    card_dirs = transport.list(PRESETS_ROOT)
    classification = classify_card_presets(card_dirs, last_pushed_directories, set(songs))
    directory_to_song_id = _song_id_by_directory(last_pushed_directories)

    if classification.unrecorded and not force:
        names = ", ".join(classification.unrecorded)
        raise PushError(
            "UNRECORDED_PRESET",
            f"preset director{'y' if len(classification.unrecorded) == 1 else 'ies'} "
            f"{names} exist on the card but are not recorded as pushed by this tool -- "
            "made on the device. Refusing; pass --force to delete them.",
        )
    force_deleted = list(classification.unrecorded) if force else []

    ops: list[RootOp] = []
    files_by_op: dict[int, dict[str, bytes]] = {}
    op_id = 0

    def _add_write(live_path: str, files: dict[str, bytes]) -> None:
        nonlocal op_id
        op = plan_write_op(op_id, live_path, files)
        ops.append(op)
        files_by_op[op.id] = files
        op_id += 1

    def _add_delete(live_path: str) -> None:
        nonlocal op_id
        ops.append(plan_delete_op(op_id, live_path))
        op_id += 1

    # Community module install/replace (docs/workflows/push.md step 2):
    # "install what is missing, replace what does not match" is push's own
    # write, through the same staged transaction as everything else -- a
    # module that only *reconciled cleanly in memory* is not on the card.
    for install in reconcile.to_install:
        _add_write(module_install_dir(install.entry), install.files)
    for install in reconcile.to_replace:
        _add_write(module_install_dir(install.entry), install.files)

    written: list[str] = []
    renamed: dict[str, tuple[str, str]] = {}

    for song_id in sorted(selected_ids):
        song, compiled = compiled_by_song[song_id]
        new_directory = new_directory_by_song[song_id]
        _add_write(f"{PRESETS_ROOT}/{new_directory}", compiled.files)
        written.append(song_id)
        old_meta = last_pushed_meta.get(song_id)
        if old_meta is not None and old_meta.directory != new_directory:
            _add_delete(f"{PRESETS_ROOT}/{old_meta.directory}")
            renamed[song_id] = (old_meta.directory, new_directory)

    for directory in classification.deletions:
        _add_delete(f"{PRESETS_ROOT}/{directory}")
    for directory in force_deleted:
        _add_delete(f"{PRESETS_ROOT}/{directory}")

    # Placeholders: computed across every song in the repo, not just the
    # selected subset (docs/workflows/push.md step 3).
    all_programs = {s.program for s in songs.values()}
    needed_gaps = set(gap_programs(all_programs))
    existing_placeholder_programs = {
        int(name) for name in card_dirs if is_placeholder_directory(name)
    }
    placeholders_added = sorted(needed_gaps - existing_placeholder_programs)
    placeholders_removed = sorted(existing_placeholder_programs - needed_gaps)
    for program in placeholders_added:
        placeholder = build_placeholder(program, catalog=catalog)
        _add_write(f"{PRESETS_ROOT}/{format_program_prefix(program)}", placeholder.files)
    for program in placeholders_removed:
        _add_delete(f"{PRESETS_ROOT}/{format_program_prefix(program)}")

    # Step 6: mirror media, deletions included.
    media_plan = build_media_plan(media_root, kits)
    for group in media_plan.groups:
        _add_write(group.card_path, group.files)

    result_common = dict(
        written=written,
        renamed=renamed,
        retired=list(classification.deletions),
        force_deleted=force_deleted,
        placeholders_added=placeholders_added,
        placeholders_removed=placeholders_removed,
        modules_installed=sorted(m.entry.key for m in reconcile.to_install),
        modules_replaced=sorted(m.entry.key for m in reconcile.to_replace),
        media_groups_written=[g.name for g in media_plan.groups],
    )

    if dry_run:
        projected = _project_current_preset(transport, classification, renamed, force_deleted)
        return PushResult(dry_run=True, current_preset_repaired=projected, **result_common)

    # Step 7: transact.
    for op in ops:
        if op.id in files_by_op:
            stage_files(transport, op.staged, files_by_op[op.id])
    run_transaction(transport, ops)  # raises PushTransactionError on verify failure, restores backups

    # Step 8: repair a dangling currentPreset, only if this push caused it.
    current_preset_repaired = _repair_current_preset(transport)

    # Step 9: record state, only after the card is verified (transact
    # already verified before returning).
    for song_id in written:
        song, compiled = compiled_by_song[song_id]
        write_last_pushed(
            state_dir,
            song_id,
            compiled.files["params.json"],
            LastPushedMeta(directory=new_directory_by_song[song_id], program=song.program),
        )
        write_bindings(chains_state_dir, song_id, letters_by_song[song_id])

    for directory in list(classification.deletions):
        song_id = directory_to_song_id.get(directory)
        if song_id is not None:
            remove_last_pushed(state_dir, song_id)
            remove_bindings(chains_state_dir, song_id)

    write_recorded_lock_hash(state_dir, current_lock_hash)

    return PushResult(dry_run=False, current_preset_repaired=current_preset_repaired, **result_common)


def _pick_current_preset(card_dirs: Iterable[str]) -> str:
    """The preset `currentPreset` should point at, given the directories that
    exist (or will exist): the lowest-numbered managed preset, falling back to
    `Init` when the card holds none. Placeholders and un-prefixed foreign
    directories are never a performance cursor target."""
    managed = sorted(
        (d for d in card_dirs if not is_placeholder_directory(d) and d != INIT_PRESET_NAME and _program_of(d) is not None),
        key=lambda d: (_program_of(d), d),
    )
    return managed[0] if managed else INIT_PRESET_NAME


def _repair_current_preset(transport: Transport) -> Optional[str]:
    """Docs/workflows/push.md step 8, decision #53: repoint `currentPreset`
    only when it names a directory this push just made vanish. Reads the
    post-transaction card directly rather than the in-memory plan, so it is
    correct regardless of exactly which op made the name disappear."""
    if not transport.exists(RACK_JSON_PATH):
        return None
    rack = json.loads(transport.read(RACK_JSON_PATH).decode("utf-8"))
    current = rack.get("currentPreset")
    if not current or current == INIT_PRESET_NAME:
        return None
    if transport.exists(f"{PRESETS_ROOT}/{current}/params.json"):
        return None  # still resolves -- leave the performance cursor alone

    new_current = _pick_current_preset(transport.list(PRESETS_ROOT))
    rack["currentPreset"] = new_current
    transport.write(RACK_JSON_PATH, json.dumps(rack, indent=2, sort_keys=True).encode("utf-8"))
    transport.flush()
    return new_current


def _project_current_preset(
    transport: Transport,
    classification: Classification,
    renamed: dict[str, tuple[str, str]],
    force_deleted: list[str],
) -> Optional[str]:
    """What `_repair_current_preset` would land on, computed from the plan
    instead of the (untouched) card, for `--dry-run`'s report. Both route the
    choice itself through `_pick_current_preset`; only the directory set they
    feed it differs."""
    if not transport.exists(RACK_JSON_PATH):
        return None
    rack = json.loads(transport.read(RACK_JSON_PATH).decode("utf-8"))
    current = rack.get("currentPreset")
    if not current or current == INIT_PRESET_NAME:
        return None

    removed_names = set(classification.deletions) | set(force_deleted) | {old for old, _ in renamed.values()}
    survives_untouched = current not in removed_names and transport.exists(f"{PRESETS_ROOT}/{current}/params.json")
    if survives_untouched:
        return None

    card_dirs = set(transport.list(PRESETS_ROOT)) - removed_names
    card_dirs |= {new for _, new in renamed.values()}
    return _pick_current_preset(card_dirs)
