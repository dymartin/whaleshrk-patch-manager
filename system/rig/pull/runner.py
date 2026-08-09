"""`pull()` -- the orchestrator that turns device drift into reviewable PRs.

Every whole-run refusal raises `rig.pull.errors.PullError`; a
single song's reverse-map failure never aborts the run (Ruling #3: "must not
block the other songs' PRs") -- it is recorded in the result and the loop
moves on.

Precondition this function does not re-check: every `SongDocument` in
`song_docs` was loaded from a song file that already parses and validates --
`rig.pull.reverse.reverse_map_song` shares that assumption with
`rig.compile.compiler.compile_song`.

Pull only ever edits songs the repo already declares. A card preset no
recorded song claims is reported, never turned into a song file: the repo is
authoritative for whether a song exists (Ruling #1), and the device is not.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

from rig.catalog.entry import CatalogEntry
from rig.pull.errors import PullError
from rig.pull.gitio import GhClient, GitRepo, SubprocessGhClient
from rig.pull.reverse import FieldChange, ReverseMapError, reverse_map_song
from rig.push.state import read_all_meta, read_params
from rig.song.bindings import read_bindings
from rig.song.kits import KitsConfig
from rig.song.parser import SongDocument, dump_song
from rig.transport.base import Transport
from rig.transport.card import PRESETS_ROOT, resolve_card


@dataclass(frozen=True)
class PullResult:
    dry_run: bool
    clean: list[str] = field(default_factory=list)
    drifted: dict[str, Optional[str]] = field(default_factory=dict)  # song id -> PR url (None in dry-run)
    missing: list[str] = field(default_factory=list)  # recorded song ids absent from the card
    aborted: dict[str, str] = field(default_factory=dict)  # song id -> reverse-map failure message


def _song_path(repo_root: Path, doc: SongDocument, song_id: str) -> str:
    if doc.path is not None:
        try:
            return doc.path.resolve().relative_to(repo_root.resolve()).as_posix()
        except ValueError:
            # `relative_to` raises when the song was loaded from outside the
            # repo (a test's tmp_path, a path on another drive). A commit can
            # only carry repo-relative paths, so fall back to the conventional
            # location for this song id rather than committing an absolute one.
            pass
    return f"songs/{song_id}.yaml"


def _drift_pr_body(song_id: str, changes: list[FieldChange]) -> str:
    lines = [f"Device drift detected for `{song_id}`, reverse-mapped from the card:", ""]
    lines += [f"- `{c.field}` -> `{c.new!r}`" for c in changes]
    return "\n".join(lines)


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
    and PRs")."""
    git.commit_branch(base_ref=base_branch, branch=branch, files=files, message=message)
    git.push_branch(branch, remote=remote)
    return gh.ensure_pr(branch=branch, base=base_branch, title=title, body=body)


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
                f"system/data/state/last-pushed/{song_id}.json": observed_bytes,
            },
            message=f"{title}\n\n" + "\n".join(f"- {c.field} -> {c.new!r}" for c in changes),
            title=title,
            body=_drift_pr_body(song_id, changes),
            base_branch=base_branch,
            remote=remote,
        )

    return PullResult(
        dry_run=dry_run,
        clean=clean,
        drifted=drifted,
        missing=missing,
        aborted=aborted,
    )
