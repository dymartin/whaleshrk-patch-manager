"""Steps 3-5 of push: gap placeholders, classify card presets, detect an
un-commanded chain rename.

Pure functions over already-collected data (a listing of what's on the
card, recorded state, parsed songs) -- rig.push (the orchestrator) is the
only thing that talks to a Transport. `Init` is excluded here, once, by
rule (Ruling #3, docs/platform/card.md): it never appears in any bucket
this module returns, under any input, so no caller can accidentally
schedule a write to it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, Optional

from rig.song.model import Song

PROTECTED_PRESET_NAMES = {"Init"}
_PLACEHOLDER_NAME_RE = re.compile(r"^\d{3}$")


def is_placeholder_directory(name: str) -> bool:
    """A push-managed gap placeholder's directory is the bare zero-padded
    program number -- no slug suffix. A real song's compiled directory
    always carries one (`CompiledPreset.directory` is never empty for a
    song), so this pattern cannot collide with real song output; see
    `rig.compile.compiler.build_placeholder`'s docstring."""
    return bool(_PLACEHOLDER_NAME_RE.match(name))


def gap_programs(programs_in_use: Iterable[int]) -> list[int]:
    """Every unused program value below the highest one in use (decision
    #49/#50) -- computed across every song in the repo, not just a
    selective push's chosen subset, so a selective push never removes a
    placeholder an unselected song's range still needs."""
    used = set(programs_in_use)
    if not used:
        return []
    highest = max(used)
    return [p for p in range(highest) if p not in used]


@dataclass(frozen=True)
class Classification:
    """Every non-`Init`, non-placeholder directory on the card, sorted into
    the three buckets `docs/workflows/push.md` "Classify" describes."""

    # song_id -> its currently-recorded card directory name, for a song
    # whose file still exists in the repo.
    managed: dict[str, str] = field(default_factory=dict)
    # Directory names to delete unconditionally: recorded, song file gone.
    deletions: list[str] = field(default_factory=list)
    # Directory names with no recorded owner: refuse, or --force deletes.
    unrecorded: list[str] = field(default_factory=list)


def classify_card_presets(
    card_dirs: Iterable[str],
    last_pushed_directories: dict[str, str],  # song_id -> recorded directory name
    repo_song_ids: set[str],
) -> Classification:
    by_directory = {directory: song_id for song_id, directory in last_pushed_directories.items()}

    managed: dict[str, str] = {}
    deletions: list[str] = []
    unrecorded: list[str] = []

    for name in card_dirs:
        if name in PROTECTED_PRESET_NAMES or is_placeholder_directory(name):
            continue
        song_id = by_directory.get(name)
        if song_id is None:
            unrecorded.append(name)
        elif song_id in repo_song_ids:
            managed[song_id] = name
        else:
            deletions.append(name)

    return Classification(managed=managed, deletions=sorted_dedup(deletions), unrecorded=sorted_dedup(unrecorded))


def sorted_dedup(items: list[str]) -> list[str]:
    return sorted(set(items))


@dataclass(frozen=True)
class ChainRenameSuspect:
    old_names: list[str]  # recorded bindings with no matching chain in the song
    new_names: list[str]  # chains in the song with no recorded binding


def detect_chain_rename(song: Song, recorded_bindings: dict[str, str]) -> Optional[ChainRenameSuspect]:
    """An un-commanded hand rename of `name:` (docs/workflows/push.md step
    5, decision #58): a chain name recorded in the bindings store that no
    longer appears in the song, at the same time as a chain name in the
    song with no recorded binding. Either alone is ordinary (a chain was
    simply added, or simply removed) -- only the combination is ambiguous
    enough to refuse."""
    current_names = {c.name for c in song.chains}
    recorded_names = set(recorded_bindings)
    orphaned = sorted(recorded_names - current_names)
    unbound = sorted(current_names - recorded_names)
    if orphaned and unbound:
        return ChainRenameSuspect(old_names=orphaned, new_names=unbound)
    return None


def chain_rename_message(song_id: str, suspect: ChainRenameSuspect) -> str:
    if len(suspect.old_names) == 1 and len(suspect.new_names) == 1:
        old, new = suspect.old_names[0], suspect.new_names[0]
        return (
            f"song {song_id!r}: chain {old!r} lost its binding and {new!r} has none -- looks "
            f"like a hand-edited rename. Run `rig rename-chain {song_id} {old} {new}` if that's "
            "right, or restore the old name."
        )
    candidates = ", ".join(f"{old!r} -> {new!r}" for old in suspect.old_names for new in suspect.new_names)
    return (
        f"song {song_id!r}: {len(suspect.old_names)} orphaned chain binding(s) "
        f"({', '.join(repr(n) for n in suspect.old_names)}) and {len(suspect.new_names)} unbound "
        f"chain(s) ({', '.join(repr(n) for n in suspect.new_names)}) -- ambiguous, refusing to "
        f"guess. Candidates: {candidates}. Run `rig rename-chain {song_id} OLD NEW` to resolve."
    )
