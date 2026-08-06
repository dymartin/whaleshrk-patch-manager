"""`rig` command-line entry point -- the surface musicians and CI actually run.

Every command here is thin: it discovers repo state (`songs/`, `.rig/`,
`media/`), wires it into the library functions Tasks 1-7 already built and
tested, and turns every refusal those libraries raise into a clear message
plus a non-zero exit -- never a stack trace (Ruling #2). No command
re-implements validation, compilation, push, pull or reverse-mapping; this
module is plumbing and formatting only.

Repo paths are resolved relative to the current working directory, matching
`catalog update`'s own convention below -- a musician runs `rig` from the
repo root, same as `git`.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Iterable, Optional

import httpx
import typer

from rig.catalog.archive import CandidateArchive, ZipCandidateArchive
from rig.catalog.builtins import ingest_pinned_builtins
from rig.catalog.entry import CatalogEntry
from rig.catalog.gate import GateAccept, gate_candidate
from rig.catalog.ingest import (
    CandidateSource,
    KeyCollisionError,
    build_catalog,
    build_community_catalog,
)
from rig.catalog.io import read_catalog, read_lock, write_catalog, write_lock
from rig.catalog.patchstorage import (
    PatchstorageError,
    discover_union,
    fetch_archive_bytes,
    fetch_detail,
)
from rig.catalog.slugs import module_key
from rig.compile import CompileError, SampleCompileError, scan_wav_folder
from rig.pull import (
    GhClient,
    GhError,
    GitError,
    GitRepo,
    PullError,
    PullResult,
    pull as run_pull,
)
from rig.push import (
    ModuleSourceUnavailable,
    OrhackIntegrityError,
    PushError,
    PushResult,
    PushTransactionError,
    push as run_push,
)
from rig.song import (
    KitsConfig,
    KitsError,
    Song,
    SongDocument,
    SongParseError,
    dump_song,
    load_song,
    parse_kits,
    read_bindings,
    validate_song,
    validate_songs,
    write_bindings,
)
from rig.transport import CardDetectionError, Transport, TransportPathError
from rig.validate import ReportIntegrityError, run_static, verify_report, write_report

app = typer.Typer(no_args_is_help=True, add_completion=False)
catalog_app = typer.Typer(no_args_is_help=True)
app.add_typer(catalog_app, name="catalog")

# Repo layout -- resolved against the current working directory, same
# convention `catalog update` (below) already uses.
SONGS_DIR = Path("songs")
MEDIA_ROOT = Path("media")
CATALOG_DIR = Path(".rig/catalog")
LOCK_PATH = Path(".rig/modules.lock")
STATE_DIR = Path(".rig/state")
KITS_PATH = Path(".rig/kits.yaml")
# Reports are run output, not repo state -- committed baselines live under
# .rig/state/ (docs/validation.md "reports are not [committed]"), so this
# gets its own .gitignore'd subtree rather than sitting alongside them.
REPORTS_DIR = Path(".rig/state/reports")

# Test-only override points. Every real invocation leaves these None, so
# push()/pull() fall back to their own real behaviour: auto-detecting the
# mounted card, shelling out to real git/gh, reaching Patchstorage live.
# Kept as private module attributes rather than extra CLI flags -- Ruling #4
# (scope discipline) reserves the command surface for exactly what the brief
# names; a test reaches these by `monkeypatch.setattr(rig.cli, "_transport", ...)`.
_transport: Optional[Transport] = None
_card_roots: Optional[Iterable[Path]] = None
_git: Optional[GitRepo] = None
_gh: Optional[GhClient] = None
_module_source: Optional[_PatchstorageModuleSource] = None
_upgrade_fetcher = None  # Optional[Callable[[dict[str, CatalogEntry]], dict[str, CatalogEntry]]]


def _fail(command: str, code: str, message: str) -> None:
    typer.echo(f"rig {command}: {code}: {message}", err=True)
    raise typer.Exit(code=1)


def _not_implemented(command: str) -> None:
    typer.echo(f"rig {command}: not implemented", err=True)
    raise typer.Exit(code=1)


# --- song discovery ----------------------------------------------------------


def _load_all_song_docs(songs_dir: Path) -> dict[str, SongDocument]:
    """Every `songs/<id>.yaml`, keyed by filename stem -- the song id every
    library function below (`push`, `pull`, `.rig/state/`) already uses."""
    if not songs_dir.is_dir():
        return {}
    return {path.stem: load_song(path) for path in sorted(songs_dir.glob("*.yaml"))}


def _resolve_selection(
    command: str, song_args: Optional[list[str]], available: dict[str, SongDocument]
) -> Optional[set[str]]:
    """`None` means every song (`push`/`pull`'s own convention) -- empty
    selection means all songs, per every workflow doc."""
    if not song_args:
        return None
    unknown = sorted(set(song_args) - set(available))
    if unknown:
        _fail(command, "UNKNOWN_SONG", f"unknown song(s): {', '.join(unknown)}")
    return set(song_args)


def _read_catalog_lock_kits(command: str) -> tuple[list[CatalogEntry], dict, KitsConfig]:
    catalog = read_catalog(CATALOG_DIR)
    lock = read_lock(LOCK_PATH)
    try:
        kits = parse_kits(KITS_PATH, MEDIA_ROOT)
    except KitsError as exc:
        _fail(command, "KITS_INVALID", str(exc))
    return catalog, lock, kits


def _lint_findings(
    songs: dict[str, Song], catalog: list[CatalogEntry], kits: KitsConfig, media_root: Path
) -> tuple[list[str], list[str]]:
    """(error lines, warning lines) -- every line already prefixed with the
    song id where one applies, ready to print."""
    errors: list[str] = []
    warnings: list[str] = []

    cross = validate_songs(list(songs.values()))
    errors += [f"{f.code}: {f.message}" for f in cross.errors]

    for sid in sorted(songs):
        bindings = read_bindings(STATE_DIR / "chains", sid)
        result = validate_song(
            songs[sid], catalog=catalog, kits=kits, media_root=media_root, bindings=bindings
        )
        errors += [f"{sid}: {f.code}: {f.message}" for f in result.errors]
        warnings += [f"{sid}: {f.code}: {f.message}" for f in result.warnings]

    return errors, warnings


def _require_valid(
    command: str, songs: dict[str, Song], catalog: list[CatalogEntry], kits: KitsConfig, media_root: Path
) -> None:
    errors, _warnings = _lint_findings(songs, catalog, kits, media_root)
    if errors:
        for line in errors:
            typer.echo(f"rig {command}: {line}", err=True)
        typer.echo(f"rig {command}: song validation failed -- run `rig lint` for the full report", err=True)
        raise typer.Exit(code=1)


# --- Patchstorage lookup shared by `rig upgrade` and push's live ModuleSource -


def _live_httpx_client() -> httpx.Client:
    return httpx.Client(timeout=30.0)


def _find_sources_by_slug(client: httpx.Client, wanted_slugs: set[str]) -> dict[str, CandidateSource]:
    """Every live Patchstorage candidate whose upload slug is in
    `wanted_slugs`, fully fetched (detail + archive bytes).

    Patchstorage's API (docs/platform/patchstorage.md) has no lookup-by-slug
    filter -- only platform, tag, category, author and a fuzzy `search`, none
    an exact identifier match -- so finding one upload's current candidate id
    means walking the same full discovery list `rig catalog update` already
    walks. Stops early once every wanted slug is found.
    """
    if not wanted_slugs:
        return {}
    found: dict[str, CandidateSource] = {}
    ids = discover_union(client)
    for patch_id in ids:
        if len(found) == len(wanted_slugs):
            break
        detail = fetch_detail(client, patch_id)
        detail_slug = detail.get("slug")
        if detail_slug not in wanted_slugs or detail_slug in found:
            continue
        files = detail.get("files") or []
        if not files:
            continue
        archive_bytes = fetch_archive_bytes(client, files[0]["url"])
        found[detail_slug] = CandidateSource(
            id=patch_id,
            archive=ZipCandidateArchive(archive_bytes),
            detail=detail,
            archive_sha256=hashlib.sha256(archive_bytes).hexdigest(),
        )
    return found


# --- push: a real, network-backed ModuleSource / UpdateChecker ---------------

# docs/catalog.md "Strip on install": junk every real archive carries. No doc
# pins an exact editor-swap-file pattern -- vim/emacs' own conventions
# (trailing "~", ".swp"/".swo") are used as a reasonable, documented default,
# a design call rather than a verified spec.
_EDITOR_SWAP_SUFFIXES = ("~", ".swp", ".swo")
ABL_LINK_FILENAME = "abl_link~.pd_linux"


def _should_strip(rel_path: str) -> bool:
    lower = rel_path.lower()
    if "__macosx" in lower.split("/"):
        return True
    name = lower.rsplit("/", 1)[-1]
    if name.startswith("._") or name == ".ds_store":
        return True
    if lower.endswith(".dll"):
        return True
    if name.endswith(_EDITOR_SWAP_SUFFIXES):
        return True
    return False


def _extract_module_files(archive: CandidateArchive, module_dir: str) -> dict[str, bytes]:
    """Every real file under one module's own directory, relative to that
    directory, junk stripped -- the shape `ModuleSource.fetch` must return
    (relative to `rig.push.modules.module_install_dir(entry)`)."""
    prefix = f"{module_dir}/" if module_dir else ""
    files: dict[str, bytes] = {}
    for entry in archive.entries():
        if entry.is_dir:
            continue
        if module_dir and not entry.name.startswith(prefix):
            continue
        rel = entry.name[len(prefix):] if module_dir else entry.name
        if not rel or _should_strip(rel):
            continue
        files[rel] = archive.read(entry.name)
    return files


class _PatchstorageModuleSource:
    """Live, network-backed `ModuleSource` *and* `UpdateChecker` for push's
    module reconciliation step -- `rig.push.modules`'s own docstring says
    Task 8's CLI is responsible for wiring this up; never reached by a test
    (`tests/conftest.py` blocks every socket for the whole session).

    One discovery pass covers every locked community module's slug at once,
    cached for the lifetime of one push -- `_find_sources_by_slug` has no
    cheaper way to find a specific upload (see its own docstring), so calling
    it once per module would multiply an already-expensive full candidate
    walk by the number of locked community modules.
    """

    def __init__(self, wanted_slugs: set[str]):
        self._wanted = wanted_slugs
        self._sources: Optional[dict[str, CandidateSource]] = None

    def _resolve(self) -> dict[str, CandidateSource]:
        if self._sources is None:
            try:
                with _live_httpx_client() as client:
                    self._sources = _find_sources_by_slug(client, self._wanted)
            except (httpx.HTTPError, PatchstorageError) as exc:
                raise ModuleSourceUnavailable(f"could not reach Patchstorage: {exc}") from exc
        return self._sources

    def fetch(self, entry: CatalogEntry) -> dict[str, bytes]:
        source = self._resolve().get(entry.source)
        if source is None:
            raise ModuleSourceUnavailable(f"{entry.key}: no longer found on Patchstorage")

        # Re-gate to find this module's own directory inside the (possibly
        # multi-module) archive -- the same walk ingest did originally, so
        # matching on the recomputed key finds the directory that produced
        # this exact catalog entry.
        gated = gate_candidate(source.archive)
        if not isinstance(gated, GateAccept):
            raise ModuleSourceUnavailable(f"{entry.key}: archive no longer passes the catalog gate")
        module_dir = next(
            (d for d in gated.module_dirs if module_key(d.module_json["display"], entry.source) == entry.key),
            None,
        )
        if module_dir is None:
            raise ModuleSourceUnavailable(f"{entry.key}: module no longer found inside its archive")

        files = _extract_module_files(source.archive, module_dir.path)
        if any(Path(rel).name.lower() == ABL_LINK_FILENAME for rel in files):
            # docs/catalog.md "Strip on install": Organelle_OS renames this
            # file away on every patch launch, so a module needing it never
            # loads its external -- unsupported, not merely stripped.
            raise ModuleSourceUnavailable(
                f"{entry.key}: ships {ABL_LINK_FILENAME}, which Organelle_OS renames away on "
                "every patch launch -- unsupported"
            )
        return files

    def check_update(self, entry: CatalogEntry) -> Optional[str]:
        source = self._resolve().get(entry.source)
        if source is None:
            return None
        live_updated = source.detail.get("updated_at")
        if live_updated and live_updated != entry.version.updated_at:
            return (
                f"updated_at changed ({entry.version.updated_at!r} -> {live_updated!r}); "
                f"run `rig upgrade {entry.key}`"
            )
        return None


def _locked_community_slugs(catalog: list[CatalogEntry], lock: dict) -> set[str]:
    locked_keys = set(lock.get("modules", {}))
    return {e.source for e in catalog if e.source != "orhack" and e.key in locked_keys}


# --- commands ------------------------------------------------------------


@app.command()
def push(
    song: Optional[list[str]] = typer.Argument(None),
    dry_run: bool = typer.Option(False, "--dry-run"),
    force: bool = typer.Option(False, "--force"),
) -> None:
    """Compile song YAML and write it to the card."""
    try:
        song_docs = _load_all_song_docs(SONGS_DIR)
    except SongParseError as exc:
        _fail("push", "SONG_PARSE_ERROR", str(exc))

    selected = _resolve_selection("push", song, song_docs)
    catalog, lock, kits = _read_catalog_lock_kits("push")
    songs = {sid: doc.song for sid, doc in song_docs.items()}

    _require_valid("push", songs, catalog, kits, MEDIA_ROOT)

    module_source = _module_source or _PatchstorageModuleSource(_locked_community_slugs(catalog, lock))

    try:
        result = run_push(
            songs=songs,
            selected=selected,
            catalog=catalog,
            lock=lock,
            kits=kits,
            media_root=MEDIA_ROOT,
            state_dir=STATE_DIR,
            module_source=module_source,
            update_checker=module_source,
            transport=_transport,
            roots=_card_roots,
            force=force,
            dry_run=dry_run,
        )
    except CardDetectionError as exc:
        _fail("push", exc.code, str(exc))
    except (PushError, PushTransactionError, OrhackIntegrityError) as exc:
        _fail("push", exc.code, str(exc))
    except SampleCompileError as exc:
        for f in exc.findings:
            typer.echo(f"rig push: {f.code}: {f.message}", err=True)
        raise typer.Exit(code=1) from exc
    except CompileError as exc:
        _fail("push", exc.code, str(exc))
    except TransportPathError as exc:
        _fail("push", "TRANSPORT_PATH_ERROR", str(exc))

    _echo_push_result(result)


def _echo_push_result(result: PushResult) -> None:
    if result.written:
        typer.echo(f"wrote: {', '.join(result.written)}")
    for sid, (old, new) in sorted(result.renamed.items()):
        typer.echo(f"renamed: {sid} ({old} -> {new})")
    if result.retired:
        typer.echo(f"retired: {', '.join(result.retired)}")
    if result.force_deleted:
        typer.echo(f"force-deleted: {', '.join(result.force_deleted)}")
    if result.placeholders_added:
        typer.echo(f"placeholders added: {result.placeholders_added}")
    if result.placeholders_removed:
        typer.echo(f"placeholders removed: {result.placeholders_removed}")
    if result.modules_installed:
        typer.echo(f"modules installed: {', '.join(result.modules_installed)}")
    if result.modules_replaced:
        typer.echo(f"modules replaced: {', '.join(result.modules_replaced)}")
    for key, description in sorted(result.updates_available.items()):
        typer.echo(f"update available: {key}: {description}")
    if result.current_preset_repaired:
        typer.echo(f"current preset repaired to: {result.current_preset_repaired}")
    if result.dry_run:
        typer.echo("(dry run -- nothing written)")
    elif not any(
        [
            result.written,
            result.renamed,
            result.retired,
            result.force_deleted,
            result.placeholders_added,
            result.placeholders_removed,
        ]
    ):
        typer.echo("nothing to push")


@app.command()
def pull(
    song: Optional[list[str]] = typer.Argument(None),
    dry_run: bool = typer.Option(False, "--dry-run"),
    adopt: bool = typer.Option(False, "--adopt"),
) -> None:
    """Detect card drift and open one PR per drifted song."""
    try:
        song_docs = _load_all_song_docs(SONGS_DIR)
    except SongParseError as exc:
        _fail("pull", "SONG_PARSE_ERROR", str(exc))

    selected = _resolve_selection("pull", song, song_docs)
    catalog, lock, kits = _read_catalog_lock_kits("pull")

    try:
        result = run_pull(
            song_docs=song_docs,
            catalog=catalog,
            kits=kits,
            media_root=MEDIA_ROOT,
            state_dir=STATE_DIR,
            repo_root=Path("."),
            selected=selected,
            transport=_transport,
            roots=_card_roots,
            git=_git,
            gh=_gh,
            dry_run=dry_run,
            adopt=adopt,
        )
    except CardDetectionError as exc:
        _fail("pull", exc.code, str(exc))
    except PullError as exc:
        _fail("pull", exc.code, str(exc))
    except GitError as exc:
        _fail("pull", "GIT_ERROR", str(exc))
    except GhError as exc:
        _fail("pull", "GH_ERROR", str(exc))
    except TransportPathError as exc:
        _fail("pull", "TRANSPORT_PATH_ERROR", str(exc))

    _echo_pull_result(result)
    if result.aborted or result.adoption_failed:
        raise typer.Exit(code=1)


def _echo_pull_result(result: PullResult) -> None:
    if result.clean:
        typer.echo(f"clean: {', '.join(result.clean)}")
    for sid, url in sorted(result.drifted.items()):
        typer.echo(f"drifted: {sid} -> {url or '(dry run)'}")
    for sid, url in sorted(result.adopted.items()):
        typer.echo(f"adopted: {sid} -> {url or '(dry run)'}")
    if result.missing:
        typer.echo(f"missing from card, song file kept: {', '.join(result.missing)}")
    for sid, message in sorted(result.aborted.items()):
        typer.echo(f"could not reverse-map {sid!r}: {message}", err=True)
    for directory, message in sorted(result.adoption_failed.items()):
        typer.echo(f"could not adopt {directory!r}: {message}", err=True)
    if result.dry_run:
        typer.echo("(dry run -- nothing written)")


@app.command()
def lint(
    song: Optional[list[str]] = typer.Argument(None),
) -> None:
    """Check song YAML without touching the card."""
    try:
        song_docs = _load_all_song_docs(SONGS_DIR)
    except SongParseError as exc:
        _fail("lint", "SONG_PARSE_ERROR", str(exc))

    selection = _resolve_selection("lint", song, song_docs)
    selected_ids = sorted(song_docs) if selection is None else sorted(selection)

    catalog, lock, kits = _read_catalog_lock_kits("lint")
    songs = {sid: doc.song for sid, doc in song_docs.items()}

    has_error = False

    cross = validate_songs(list(songs.values()))
    for f in cross.errors:
        typer.echo(f"error: {f.code}: {f.message}")
        has_error = True

    for sid in selected_ids:
        bindings = read_bindings(STATE_DIR / "chains", sid)
        result = validate_song(songs[sid], catalog=catalog, kits=kits, media_root=MEDIA_ROOT, bindings=bindings)
        for f in result.errors:
            typer.echo(f"error: {sid}: {f.code}: {f.message}")
            has_error = True
        for f in result.warnings:
            typer.echo(f"warning: {sid}: {f.code}: {f.message}")

    # Kits are shared, repo-wide state (docs/media.md "Samples are global
    # state"), so their folder contents are checked once, not per song.
    for alias in sorted(kits.aliases):
        _wav_names, findings = scan_wav_folder(kits.kit_dir(MEDIA_ROOT, alias), context=f"kit {alias!r}")
        for f in findings:
            if f.code == "IGNORED_NON_WAV_FILE":
                typer.echo(f"warning: {f.code}: {f.message}")

    if not has_error:
        typer.echo("lint: ok")
    if has_error:
        raise typer.Exit(code=1)


@catalog_app.command("update")
def catalog_update(
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Rebuild .rig/catalog/ and .rig/modules.lock from live Patchstorage data.

    Built-ins come from the pinned ORHACK 0.52b fixture, never a live card
    (see rig/catalog/builtins.py) -- only community modules are discovered
    live. This is the one command allowed to reach the network; ordinary
    builds and pushes only ever read the committed `.rig/catalog/`.
    """
    builtin_entries = ingest_pinned_builtins()

    try:
        with httpx.Client(timeout=30.0) as client:
            ids = discover_union(client)
            sources = []
            for patch_id in ids:
                detail = fetch_detail(client, patch_id)
                files = detail.get("files") or []
                if not files:
                    continue
                archive_bytes = fetch_archive_bytes(client, files[0]["url"])
                sources.append(
                    CandidateSource(
                        id=patch_id,
                        archive=ZipCandidateArchive(archive_bytes),
                        detail=detail,
                        archive_sha256=hashlib.sha256(archive_bytes).hexdigest(),
                    )
                )
    except (httpx.HTTPError, PatchstorageError) as exc:
        typer.echo(f"rig catalog update: could not reach Patchstorage: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    try:
        result = build_catalog(builtin_entries, sources)
    except KeyCollisionError as exc:
        typer.echo(f"rig catalog update: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    for reject in result.rejects:
        typer.echo(f"rejected {reject.candidate_id} ({reject.reason.value}): {reject.message}")

    if dry_run:
        typer.echo(f"{len(result.entries)} entries, {len(result.rejects)} rejected (dry run)")
        return

    write_catalog(result.entries, CATALOG_DIR)
    write_lock(result.entries, LOCK_PATH)
    typer.echo(f"{len(result.entries)} entries written, {len(result.rejects)} rejected")


def _used_param_slugs(song: Song, module_key_: str) -> set[str]:
    """Every friendly parameter slug this song uses against `module_key_`,
    across every context a module key can appear -- decision #56's "a
    parameter slug used by any song"."""
    slugs: set[str] = set()
    for chain in song.chains:
        for m in chain.modules:
            if m.key == module_key_:
                slugs.update(m.params)
                slugs.update(m.midi)
    for send in song.sends:
        if send.module == module_key_:
            slugs.update(send.params)
    for use in song.master:
        if use.key == module_key_:
            slugs.update(use.params)
    for use in song.mod_sources:
        if use.key == module_key_:
            slugs.update(use.params)
    return slugs


def _fetch_upgraded_entries(requested: dict[str, CatalogEntry]) -> dict[str, CatalogEntry]:
    """Module key -> its freshly re-ingested `CatalogEntry`, live from
    Patchstorage, for every key in `requested` whose upload still exists and
    still passes the catalog gate. A key absent from the result means it
    could not be refreshed -- the caller treats that as a refusal."""
    wanted_slugs = {entry.source for entry in requested.values()}
    with _live_httpx_client() as client:
        sources = _find_sources_by_slug(client, wanted_slugs)
    fresh_entries, _rejects = build_community_catalog(list(sources.values()))
    return {entry.key: entry for entry in fresh_entries if entry.key in requested}


@app.command()
def upgrade(
    module: list[str] = typer.Argument(...),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Bump pinned module versions in .rig/modules.lock."""
    current_catalog = read_catalog(CATALOG_DIR)
    current_by_key = {e.key: e for e in current_catalog}

    unknown = [m for m in module if m not in current_by_key]
    if unknown:
        _fail("upgrade", "UNKNOWN_MODULE", f"not in .rig/catalog/: {', '.join(unknown)}")

    builtins_named = [m for m in module if current_by_key[m].source == "orhack"]
    if builtins_named:
        _fail(
            "upgrade",
            "BUILTIN_NOT_UPGRADABLE",
            f"built-in module(s) {', '.join(builtins_named)} are pinned to the ORHACK build, "
            "not a live source -- nothing to upgrade to",
        )

    requested = {m: current_by_key[m] for m in module}
    fetcher = _upgrade_fetcher or _fetch_upgraded_entries
    try:
        fresh_by_key = fetcher(requested)
    except (httpx.HTTPError, PatchstorageError) as exc:
        _fail("upgrade", "SOURCE_UNREACHABLE", f"could not reach Patchstorage: {exc}")

    still_missing = [m for m in module if m not in fresh_by_key]
    if still_missing:
        _fail(
            "upgrade",
            "MODULE_UNAVAILABLE",
            f"module(s) {', '.join(still_missing)} could not be found live, or no longer pass "
            "the catalog gate -- nothing changed",
        )

    try:
        song_docs = _load_all_song_docs(SONGS_DIR)
    except SongParseError as exc:
        _fail("upgrade", "SONG_PARSE_ERROR", str(exc))
    songs = {sid: doc.song for sid, doc in song_docs.items()}

    refusal_lines: list[str] = []
    for m in module:
        old_ids = {p.name: p.id for p in requested[m].params}
        new_ids = {p.name: p.id for p in fresh_by_key[m].params}
        for sid in sorted(songs):
            for slug_name in sorted(_used_param_slugs(songs[sid], m)):
                if slug_name in old_ids and slug_name in new_ids and old_ids[slug_name] != new_ids[slug_name]:
                    refusal_lines.append(
                        f"{m}: parameter {slug_name!r} used by song {sid!r} now resolves to a "
                        "different parameter than before -- same slug, different id, no "
                        "song-file diff, different sound"
                    )

    if refusal_lines:
        for line in refusal_lines:
            typer.echo(f"rig upgrade: {line}", err=True)
        typer.echo("rig upgrade: refusing -- edit the affected song(s) by hand, then rerun", err=True)
        raise typer.Exit(code=1)

    if dry_run:
        for m in module:
            typer.echo(f"would upgrade: {m}")
        return

    merged = [fresh_by_key.get(entry.key, entry) for entry in current_catalog]
    write_catalog(merged, CATALOG_DIR)
    write_lock(merged, LOCK_PATH)
    for m in module:
        typer.echo(f"upgraded: {m}")


@app.command("rename-chain")
def rename_chain(
    song: str = typer.Argument(...),
    old: str = typer.Argument(...),
    new: str = typer.Argument(...),
) -> None:
    """Rename a chain within a song, preserving its letter binding.

    Edits the working tree only -- `git commit` is left to the musician
    (Ruling #5: this tool never commits without being asked).
    """
    path = SONGS_DIR / f"{song}.yaml"
    if not path.is_file():
        _fail("rename-chain", "UNKNOWN_SONG", f"no song file at {path}")

    try:
        doc = load_song(path)
    except SongParseError as exc:
        _fail("rename-chain", "SONG_PARSE_ERROR", str(exc))

    names = {c.name for c in doc.song.chains}
    if old not in names:
        _fail("rename-chain", "CHAIN_NOT_FOUND", f"song {song!r} has no chain named {old!r}")
    if new in names:
        _fail("rename-chain", "CHAIN_NAME_COLLISION", f"song {song!r} already has a chain named {new!r}")

    renamed = False
    for chain_raw in doc.raw.get("chains") or []:
        if chain_raw.get("name") == old:
            chain_raw["name"] = new
            renamed = True
            break
    if not renamed:
        # Unreachable in practice -- doc.song.chains was built from this same
        # raw list -- but never silently no-op a rename (Global Constraint #3).
        _fail("rename-chain", "CHAIN_NOT_FOUND", f"song {song!r} has no chain named {old!r} in its YAML")

    path.write_text(dump_song(doc), encoding="utf-8")

    chains_state_dir = STATE_DIR / "chains"
    bindings = read_bindings(chains_state_dir, song)
    if old in bindings:
        letter = bindings.pop(old)
        bindings[new] = letter
        write_bindings(chains_state_dir, song, bindings)

    typer.echo(f"renamed: {song}: {old} -> {new}")


# `validate` is a single flat command, deliberately not a typer sub-app/group,
# even though `verify-report` reads like a subcommand. typer's TyperGroup
# (vendored click) resolves a group's leftover positional tokens as a
# subcommand-name candidate before the group's own callback runs at all --
# confirmed against typer 0.27.1's TyperGroup.parse_args/invoke in
# typer/core.py -- regardless of allow_extra_args/ignore_unknown_options. A
# `song: list[str]` argument on a `validate` group callback therefore either
# swallows a literal `verify-report` (breaking subcommand dispatch) or, as a
# group argument, makes any non-empty SONG list fail with "No such command".
# Do not turn this back into a group; dispatch on args[0] instead.
#
# Hardware validation (Phase 10) has no hardware feedback channel yet, so
# `--tier hardware` stays a documented stub -- Global Constraint #1: never
# cite a planned tier as if it had already run.
def _validate_static(command: str, song_args: list[str]) -> None:
    try:
        song_docs = _load_all_song_docs(SONGS_DIR)
    except SongParseError as exc:
        _fail(command, "SONG_PARSE_ERROR", str(exc))

    selected = _resolve_selection(command, song_args, song_docs)
    catalog, lock, kits = _read_catalog_lock_kits(command)
    songs = {sid: doc.song for sid, doc in song_docs.items()}

    commit = None
    try:
        commit = GitRepo(Path(".")).rev_parse("HEAD")
    except GitError:
        pass  # no repo, or no commits yet -- Subject.commit stays None

    module_lock_digest = hashlib.sha256(LOCK_PATH.read_bytes()).hexdigest() if LOCK_PATH.exists() else None

    report = run_static(
        songs=songs,
        selected=selected,
        catalog=catalog,
        lock=lock,
        kits=kits,
        media_root=MEDIA_ROOT,
        bindings_dir=STATE_DIR / "chains",
        commit=commit,
        module_lock_digest=module_lock_digest,
    )

    report_path = REPORTS_DIR / f"static-{report.run_id}.json"
    write_report(report, report_path)

    typer.echo(f"verdict: {report.verdict}")
    for f in report.failures:
        typer.echo(f"failure: {f.id}: {f.message}")
    typer.echo(f"confidence: {report.confidence}")
    typer.echo(report.scope_note)
    typer.echo(f"report written: {report_path}")

    if report.verdict != "pass":
        raise typer.Exit(code=1)


def _validate_verify_report(command: str, report_arg: str) -> None:
    report_path = Path(report_arg)
    try:
        verify_report(report_path)
    except FileNotFoundError:
        _fail(command, "REPORT_NOT_FOUND", f"no report at {report_path}")
    except ReportIntegrityError as exc:
        _fail(command, "REPORT_INTEGRITY_ERROR", str(exc))
    typer.echo(f"rig validate verify-report: ok: {report_path}")


@app.command(
    context_settings={"ignore_unknown_options": True},
    epilog=(
        "rig validate --tier static|hardware [SONG...]\n\n"
        "rig validate verify-report REPORT"
    ),
)
def validate(
    args: Optional[list[str]] = typer.Argument(
        None,
        metavar="[SONG]... | verify-report REPORT",
        help="Song names for --tier validation, or the literal "
        "'verify-report REPORT'.",
    ),
    tier: Optional[str] = typer.Option(None, "--tier", help="static|hardware"),
) -> None:
    """Run static or hardware validation, or verify a recorded report.

    Two invocation forms:

        rig validate --tier static|hardware [SONG...]

        rig validate verify-report REPORT
    """
    args = args or []
    if args and args[0] == "verify-report":
        if len(args) != 2:
            typer.echo("usage: rig validate verify-report REPORT", err=True)
            raise typer.Exit(code=2)
        _validate_verify_report("validate verify-report", args[1])
        return

    if tier == "hardware":
        _not_implemented("validate --tier hardware")
    if tier != "static":
        typer.echo("rig validate: --tier static|hardware is required", err=True)
        raise typer.Exit(code=2)

    _validate_static("validate", args)


if __name__ == "__main__":
    app()
