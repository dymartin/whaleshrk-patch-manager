"""`pull()` -- the orchestrator that turns device drift into reviewable PRs.

See `docs/workflows/pull.md` and `Prompt/07-pull.md` for the sequence this
follows. Every whole-run refusal raises `rig.pull.errors.PullError`; a
single song's reverse-map or adoption failure never aborts the run (Ruling
#3: "must not block the other songs' PRs") -- it is recorded in the result
and the loop moves on.

Precondition this function does not re-check: every `SongDocument` in
`song_docs` was loaded from a song file that already parses and validates --
`rig.pull.reverse.reverse_map_song` shares that assumption with
`rig.compile.compiler.compile_song`.

**Adoption is opt-in** (`adopt=True`), not something a plain `rig pull` does
by default -- Ruling #2: "Adoption of an unrecorded card preset is a
separate, explicitly-requested path, not something a routine pull does
silently." `docs/workflows/pull.md` describes adoption as part of pull's
job; the two are reconciled here by keeping adoption fully implemented and
independently testable (`rig.pull.adopt`), wired into this same function so
one command still produces it, but never triggered unless the caller asks.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

from rig.catalog.entry import CatalogEntry
from rig.pull.adopt import AdoptedSong, adopt_preset
from rig.pull.errors import PullError
from rig.pull.gitio import GhClient, GitRepo, SubprocessGhClient
from rig.pull.reverse import FieldChange, ReverseMapError, reverse_map_song
from rig.push.plan import is_placeholder_directory
from rig.push.state import LastPushedMeta, read_all_meta, read_params
from rig.song.bindings import read_bindings
from rig.song.kits import KitsConfig
from rig.song.parser import SongDocument, dump_song
from rig.transport.base import Transport
from rig.transport.card import PRESETS_ROOT, PROTECTED_PRESET_NAMES, resolve_card


@dataclass(frozen=True)
class PullResult:
    dry_run: bool
    clean: list[str] = field(default_factory=list)
    drifted: dict[str, Optional[str]] = field(default_factory=dict)  # song id -> PR url (None in dry-run)
    missing: list[str] = field(default_factory=list)  # recorded song ids absent from the card
    aborted: dict[str, str] = field(default_factory=dict)  # song id -> reverse-map failure message
    adopted: dict[str, Optional[str]] = field(default_factory=dict)  # new song id -> PR url (None in dry-run)
    adoption_failed: dict[str, str] = field(default_factory=dict)  # card directory -> adoption failure message


def _song_path(repo_root: Path, doc: SongDocument, song_id: str) -> str:
    if doc.path is not None:
        try:
            return doc.path.resolve().relative_to(repo_root.resolve()).as_posix()
        except ValueError:
            pass
    return f"songs/{song_id}.yaml"


def _meta_bytes(directory: str, program: int) -> bytes:
    return (json.dumps({"directory": directory, "program": program}, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )


def _bindings_bytes(bindings: dict[str, str]) -> bytes:
    return (json.dumps(bindings, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _drift_pr_body(song_id: str, changes: list[FieldChange]) -> str:
    lines = [f"Device drift detected for `{song_id}`, reverse-mapped from the card:", ""]
    lines += [f"- `{c.field}` -> `{c.new!r}`" for c in changes]
    return "\n".join(lines)


def _adoption_pr_body(song_id: str, directory: str) -> str:
    return (
        f"Adopted from card preset `{directory}`, which had no matching song file.\n\n"
        "Names (song, chain, send) were derived from the preset's contents and are not "
        "guaranteed to be meaningful -- review before merging. Use `rig rename-chain` to "
        "rename a chain; its letter binding moves with it automatically."
    )


def _publish_branch(
    git: GitRepo,
    gh: GhClient,
    *,
    branch: str,
    files: dict[str, bytes],
    message: str,
    title: str,
    body: str,
    base_branch: str,
    remote: str,
) -> str:
    """One song's worth of output: commit the files onto `branch`, push it, and
    make sure a PR is open. One PR per song (docs/workflows/pull.md "Branches
    and PRs") -- drift and adoption differ only in what they put in the commit,
    so they share this tail."""
    git.commit_branch(base_ref=base_branch, branch=branch, files=files, message=message)
    git.push_branch(branch, remote=remote)
    return gh.ensure_pr(branch=branch, base=base_branch, title=title, body=body)


def _run_adoption(
    transport: Transport,
    git: GitRepo,
    gh: GhClient,
    *,
    card_dirs: set[str],
    all_meta: dict[str, LastPushedMeta],
    song_docs: dict[str, SongDocument],
    catalog: list[CatalogEntry],
    kits: KitsConfig,
    media_root: Path,
    dry_run: bool,
    base_branch: str,
    remote: str,
) -> tuple[dict[str, Optional[str]], dict[str, str]]:
    """`--adopt`'s own phase: mint a song for every card preset no recorded
    song claims. Independent of drift reconciliation -- it reads a disjoint set
    of presets and shares no state with it beyond the card listing -- and
    returns (adopted song id -> PR url, failed directory -> reason)."""
    adopted: dict[str, Optional[str]] = {}
    adoption_failed: dict[str, str] = {}

    recorded_directories = {meta.directory for meta in all_meta.values()}
    adoptable = sorted(
        d for d in card_dirs
        if d not in recorded_directories and d not in PROTECTED_PRESET_NAMES and not is_placeholder_directory(d)
    )
    existing_ids = set(song_docs) | set(all_meta)
    used_programs = {doc.song.program for doc in song_docs.values()}

    for directory in adoptable:
        observed_bytes = transport.read(f"{PRESETS_ROOT}/{directory}/params.json")
        observed = json.loads(observed_bytes)
        try:
            result: AdoptedSong = adopt_preset(
                directory, observed, catalog=catalog, kits=kits, media_root=media_root,
                existing_song_ids=existing_ids, used_programs=used_programs,
            )
        except ReverseMapError as exc:
            adoption_failed[directory] = f"{exc.code}: {exc}"
            continue

        existing_ids.add(result.song_id)
        used_programs.add(result.program)

        if dry_run:
            adopted[result.song_id] = None
            continue

        adopted[result.song_id] = _publish_branch(
            git, gh,
            branch=f"pull/{result.song_id}",
            files={
                f"songs/{result.song_id}.yaml": result.text.encode("utf-8"),
                f".rig/state/last-pushed/{result.song_id}.json": observed_bytes,
                f".rig/state/last-pushed/{result.song_id}.meta.json": _meta_bytes(directory, result.program),
                f".rig/state/chains/{result.song_id}.json": _bindings_bytes(result.bindings),
            },
            message=f"pull: adopt {result.song_id!r} from card preset {directory!r}",
            title=f"pull: adopt {result.song_id!r}",
            body=_adoption_pr_body(result.song_id, directory),
            base_branch=base_branch,
            remote=remote,
        )

    return adopted, adoption_failed


def pull(
    *,
    song_docs: dict[str, SongDocument],
    catalog: list[CatalogEntry],
    kits: KitsConfig,
    media_root: Path,
    state_dir: Path,
    repo_root: Path,
    selected: Optional[set[str]] = None,
    transport: Optional[Transport] = None,
    roots: Optional[Iterable[Path]] = None,
    git: Optional[GitRepo] = None,
    gh: Optional[GhClient] = None,
    base_branch: str = "main",
    remote: str = "origin",
    dry_run: bool = False,
    adopt: bool = False,
) -> PullResult:
    if transport is None:
        transport = resolve_card(roots)  # raises CardDetectionError -- never picks silently

    git = git or GitRepo(repo_root)
    gh = gh or SubprocessGhClient(repo_root)

    card_dirs = set(transport.list(PRESETS_ROOT))
    chains_state_dir = state_dir / "chains"

    all_meta = read_all_meta(state_dir)
    recorded_present = {sid: meta for sid, meta in all_meta.items() if meta.directory in card_dirs}
    recorded_missing = {sid: meta for sid, meta in all_meta.items() if meta.directory not in card_dirs}

    # A wiped or foreign card, not news about one song (docs/workflows/pull.md
    # step 3, decision #55) -- checked against every recorded song regardless
    # of `selected`, so a selective pull for one song is never misread as
    # "the whole card is gone" just because that one song happens to be
    # missing.
    if all_meta and not recorded_present:
        raise PullError(
            "ALL_PRESETS_MISSING",
            f"none of the {len(all_meta)} recorded preset(s) are present on this card -- "
            "wrong or wiped card. Refusing to touch any song.",
        )

    missing = sorted(recorded_missing)

    selected_ids = set(song_docs) if selected is None else set(selected)
    # Intersected with `song_docs` too, not just `recorded_present`: a song
    # can be recorded (a previous push happened) with its YAML already
    # deleted from the repo (retirement pending the next push) -- there is
    # nothing to reverse-map an edit into, and the repo staying authoritative
    # for song existence (Ruling #1) means pull must not touch it.
    process_ids = sorted(set(recorded_present) & selected_ids & set(song_docs))

    clean: list[str] = []
    drifted: dict[str, Optional[str]] = {}
    aborted: dict[str, str] = {}

    for song_id in process_ids:
        meta = recorded_present[song_id]
        baseline = json.loads(read_params(state_dir, song_id))
        observed_bytes = transport.read(f"{PRESETS_ROOT}/{meta.directory}/params.json")
        observed = json.loads(observed_bytes)

        if baseline == observed:
            clean.append(song_id)
            continue

        doc = song_docs[song_id]
        bindings = read_bindings(chains_state_dir, song_id)
        try:
            changes = reverse_map_song(
                doc, baseline=baseline, observed=observed, catalog=catalog, kits=kits, media_root=media_root,
                bindings=bindings,
            )
        except ReverseMapError as exc:
            aborted[song_id] = f"{exc.code}: {exc}"
            continue

        if dry_run:
            drifted[song_id] = None
            continue

        title = f"pull: {song_id} drifted from the device"
        drifted[song_id] = _publish_branch(
            git, gh,
            branch=f"pull/{song_id}",
            files={
                _song_path(repo_root, doc, song_id): dump_song(doc).encode("utf-8"),
                f".rig/state/last-pushed/{song_id}.json": observed_bytes,
            },
            message=f"{title}\n\n" + "\n".join(f"- {c.field} -> {c.new!r}" for c in changes),
            title=title,
            body=_drift_pr_body(song_id, changes),
            base_branch=base_branch,
            remote=remote,
        )

    if adopt:
        adopted, adoption_failed = _run_adoption(
            transport, git, gh,
            card_dirs=card_dirs,
            all_meta=all_meta,
            song_docs=song_docs,
            catalog=catalog,
            kits=kits,
            media_root=media_root,
            dry_run=dry_run,
            base_branch=base_branch,
            remote=remote,
        )
    else:
        adopted, adoption_failed = {}, {}

    return PullResult(
        dry_run=dry_run,
        clean=clean,
        drifted=drifted,
        missing=missing,
        aborted=aborted,
        adopted=adopted,
        adoption_failed=adoption_failed,
    )
