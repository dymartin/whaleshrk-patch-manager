"""`rig` command-line entry point -- the surface musicians and CI actually run.

Every command here is thin: it discovers repo state (`songs/`, `system/data/`,
`system/media/`), wires it into the library functions Tasks 1-7 already built and
tested, and turns every refusal those libraries raise into a clear message
plus a non-zero exit -- never a stack trace (Ruling #2). No command
re-implements validation, compilation, push, pull or reverse-mapping; this
module is plumbing and formatting only.

Repo paths are resolved relative to the current working directory, matching
`catalog update`'s own convention below -- a musician runs `rig` from the
repo root, same as `git`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Iterable, NoReturn, Optional

import httpx
import typer

from rig.atomicio import write_text_atomic
from rig.catalog import (
    ARCHIVE_SIZE_WARN_BYTES,
    ArchiveStoreError,
    CandidateSource,
    CatalogEntry,
    KeyCollisionError,
    PatchstorageError,
    build_catalog,
    build_community_catalog,
    discover_union_items,
    discover_sources,
    find_sources_by_slug,
    ingest_pinned_builtins,
    live_httpx_client,
    read_catalog,
    read_archive,
    write_archive,
    write_catalog,
)
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
    StoredArchiveModuleSource,
    push as run_push,
)
from rig.reabank import build_reabank
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
from rig.palette import (
    clear_palette,
    compatible_community_entries,
    install_palette,
    plan_palette,
)
from rig.transport import (
    CardDetectionError,
    Transport,
    TransportPathError,
    resolve_card,
)

app = typer.Typer(no_args_is_help=True, add_completion=False)
catalog_app = typer.Typer(no_args_is_help=True)
app.add_typer(catalog_app, name="catalog")
palette_app = typer.Typer(no_args_is_help=True)
app.add_typer(palette_app, name="palette")

# Repo layout -- resolved against the current working directory, same
# convention `catalog update` (below) already uses.
SONGS_DIR = Path("songs")
SYSTEM_DIR = Path("system")
MEDIA_ROOT = SYSTEM_DIR / "media"
MODULES_DIR = SYSTEM_DIR / "modules"
DATA_DIR = SYSTEM_DIR / "data"
CATALOG_PATH = DATA_DIR / "catalog.json"
STATE_DIR = DATA_DIR / "state"
KITS_PATH = DATA_DIR / "kits.yaml"

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
_module_source: Optional[StoredArchiveModuleSource] = None
_mirror_fetcher: Optional[Callable[[], dict[str, CandidateSource]]] = None


def _fail(command: str, code: str, message: str) -> NoReturn:
    typer.echo(f"rig {command}: {code}: {message}", err=True)
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


def _read_catalog_kits(command: str) -> tuple[list[CatalogEntry], KitsConfig]:
    catalog = read_catalog(CATALOG_PATH)
    try:
        kits = parse_kits(KITS_PATH, MEDIA_ROOT)
    except KitsError as exc:
        _fail(command, "KITS_INVALID", str(exc))
    return catalog, kits


def _lint_findings(
    songs: dict[str, Song],
    catalog: list[CatalogEntry],
    kits: KitsConfig,
    media_root: Path,
    selected_ids: Optional[Iterable[str]] = None,
) -> tuple[list[str], list[str]]:
    """(error lines, warning lines) -- every line already prefixed with the
    song id where one applies, ready to print.

    Cross-song checks always run against every song in `songs`; per-song
    checks are scoped to `selected_ids` (default: every song) -- `rig lint`
    can narrow the latter to a subset while `push` never narrows."""
    errors: list[str] = []
    warnings: list[str] = []

    cross = validate_songs(list(songs.values()))
    errors += [f"{f.code}: {f.message}" for f in cross.errors]

    ids = sorted(songs) if selected_ids is None else sorted(selected_ids)
    for sid in ids:
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


# --- Patchstorage lookup, shared by `catalog add` and `catalog update` -----


def _fetch_sources(command: str, slugs: set[str]) -> dict[str, CandidateSource]:
    """Fetch the named uploads from Patchstorage."""
    if not slugs:
        return {}
    try:
        with live_httpx_client() as client:
            return find_sources_by_slug(client, slugs)
    except (httpx.HTTPError, PatchstorageError) as exc:
        _fail(command, "SOURCE_UNREACHABLE", f"could not reach Patchstorage: {exc}")


def _store_archives(command: str, entries: list[CatalogEntry], sources: dict[str, CandidateSource]) -> None:
    """Commit each upload's archive to `modules/`, byte-identical to what
    Patchstorage served, and warn about any that will weigh on git history."""
    stored: set[str] = set()
    for entry in entries:
        source = sources.get(entry.source)
        if source is None or entry.source in stored:
            continue
        stored.add(entry.source)
        data = source.archive.data
        try:
            path = write_archive(MODULES_DIR, entry.source, entry.version.revision or "unknown", data)
        except ArchiveStoreError as exc:
            _fail(command, exc.code, str(exc))
        if len(data) > ARCHIVE_SIZE_WARN_BYTES:
            typer.echo(
                f"warning: {path.name} is {len(data) // 1024}KB -- every future version of it stays "
                "in git history permanently",
            )


def _mirror_source_satisfied(item: dict, entries_by_source: dict[str, list[CatalogEntry]]) -> bool:
    """Live listing unchanged and every pinned archive still verifies locally."""
    entries = entries_by_source.get(item.get("slug"), [])
    if not entries or any(e.version.updated_at != item.get("updated_at") for e in entries):
        return False
    checked: set[tuple[str, str, str]] = set()
    for entry in entries:
        archive = (
            entry.source,
            entry.version.revision or "unknown",
            entry.version.archive_sha256 or "",
        )
        if archive in checked:
            continue
        try:
            read_archive(MODULES_DIR, *archive)
        except ArchiveStoreError:
            return False
        checked.add(archive)
    return True


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
    catalog, kits = _read_catalog_kits("push")
    songs = {sid: doc.song for sid, doc in song_docs.items()}

    _require_valid("push", songs, catalog, kits, MEDIA_ROOT)

    module_source = _module_source or StoredArchiveModuleSource(MODULES_DIR)

    try:
        result = run_push(
            songs=songs,
            selected=selected,
            catalog=catalog,
            kits=kits,
            media_root=MEDIA_ROOT,
            state_dir=STATE_DIR,
            module_source=module_source,
            transport=_transport,
            roots=_card_roots,
            force=force,
            dry_run=dry_run,
            on_step=lambda label: typer.echo(f"  {label}"),
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
    if result.modules_removed:
        typer.echo(f"modules removed: {', '.join(result.modules_removed)}")
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
) -> None:
    """Detect card drift and open one PR per drifted song."""
    try:
        song_docs = _load_all_song_docs(SONGS_DIR)
    except SongParseError as exc:
        _fail("pull", "SONG_PARSE_ERROR", str(exc))

    selected = _resolve_selection("pull", song, song_docs)
    catalog, kits = _read_catalog_kits("pull")

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
    if result.aborted:
        raise typer.Exit(code=1)


def _echo_pull_result(result: PullResult) -> None:
    if result.clean:
        typer.echo(f"clean: {', '.join(result.clean)}")
    for sid, url in sorted(result.drifted.items()):
        typer.echo(f"drifted: {sid} -> {url or '(dry run)'}")
    if result.missing:
        typer.echo(f"missing from card, song file kept: {', '.join(result.missing)}")
    for sid, message in sorted(result.aborted.items()):
        typer.echo(f"could not reverse-map {sid!r}: {message}", err=True)
    if result.dry_run:
        typer.echo("(dry run -- nothing written)")


def _check_stored_archives(catalog: list[CatalogEntry]) -> list[str]:
    """Re-gate every community module's committed archive.

    This is the repo's reproducibility check: it proves `system/data/catalog.json`
    was generated from the archives actually present in `modules/`, rather than
    hand-edited, and that every archive still passes the safety and ARM32 ELF
    checks it passed when it was added. Cheap because the catalog is a
    shopping list -- it covers the modules this rig uses, not all of
    Patchstorage.
    """
    module_source = StoredArchiveModuleSource(MODULES_DIR)
    problems: list[str] = []
    for entry in catalog:
        if entry.source == "orhack":
            continue
        try:
            module_source.fetch(entry)
        except ModuleSourceUnavailable as exc:
            problems.append(str(exc))
    return problems


@app.command()
def lint(
    song: Optional[list[str]] = typer.Argument(None),
) -> None:
    """Check song YAML and stored module archives without touching the card."""
    try:
        song_docs = _load_all_song_docs(SONGS_DIR)
    except SongParseError as exc:
        _fail("lint", "SONG_PARSE_ERROR", str(exc))

    selection = _resolve_selection("lint", song, song_docs)
    selected_ids = sorted(song_docs) if selection is None else sorted(selection)

    catalog, kits = _read_catalog_kits("lint")
    songs = {sid: doc.song for sid, doc in song_docs.items()}

    has_error = False

    for problem in _check_stored_archives(catalog):
        typer.echo(f"error: MODULE_ARCHIVE: {problem}")
        has_error = True

    errors, warnings = _lint_findings(songs, catalog, kits, MEDIA_ROOT, selected_ids)
    for line in errors:
        typer.echo(f"error: {line}")
        has_error = True
    for line in warnings:
        typer.echo(f"warning: {line}")

    # Kits are shared, so their folder contents are checked once, not per song.
    for alias in sorted(kits.aliases):
        _wav_names, findings = scan_wav_folder(kits.kit_dir(MEDIA_ROOT, alias), context=f"kit {alias!r}")
        for f in findings:
            if f.code == "IGNORED_NON_WAV_FILE":
                typer.echo(f"warning: {f.code}: {f.message}")

    if not has_error:
        typer.echo("lint: ok")
    if has_error:
        raise typer.Exit(code=1)


@app.command()
def reabank(
    output: Path = typer.Option(DATA_DIR / "orhack.reabank", "--output"),
) -> None:
    """Write a REAPER .reabank file listing every song's MIDI program."""
    try:
        song_docs = _load_all_song_docs(SONGS_DIR)
    except SongParseError as exc:
        _fail("reabank", "SONG_PARSE_ERROR", str(exc))
    songs = {sid: doc.song for sid, doc in song_docs.items()}
    write_text_atomic(output, build_reabank(songs))
    typer.echo(f"wrote: {output}")


def _rebuild(command: str, sources: dict[str, CandidateSource]) -> list[CatalogEntry]:
    """Gate `sources` and rebuild the whole catalog around them.

    Built-ins come from the pinned ORHACK 0.52b fixture, never a live card
    (see rig/catalog/builtins.py); only community modules come from
    Patchstorage.
    """
    try:
        result = build_catalog(ingest_pinned_builtins(), list(sources.values()))
    except KeyCollisionError as exc:
        _fail(command, "KEY_COLLISION", str(exc))

    for reject in result.rejects:
        typer.echo(f"rejected {reject.candidate_id} ({reject.reason.value}): {reject.message}")
    return result.entries


@catalog_app.command("add")
def catalog_add(
    slug: list[str] = typer.Argument(..., help="Patchstorage upload slug(s)"),
) -> None:
    """Add community module(s) to the catalog by Patchstorage upload slug.

    The catalog is a shopping list, not a mirror of Patchstorage: it holds
    the modules this rig actually uses, and nothing else. `rig catalog add`,
    `rig catalog mirror` and `rig catalog update` are the only commands that
    reach the network; everything else reads the committed
    `system/data/catalog.json` and `modules/`.
    """
    wanted = set(slug)
    existing_sources = {e.source for e in read_catalog(CATALOG_PATH) if e.source != "orhack"}
    already = sorted(wanted & existing_sources)
    if already:
        _fail("catalog add", "ALREADY_ADDED", f"already in the catalog: {', '.join(already)}")

    sources = _fetch_sources("catalog add", wanted | existing_sources)
    missing = sorted(wanted - set(sources))
    if missing:
        _fail("catalog add", "SLUG_NOT_FOUND", f"no Patchstorage upload with slug(s): {', '.join(missing)}")

    entries = _rebuild("catalog add", sources)
    added = sorted(e.key for e in entries if e.source in wanted)
    if not added:
        _fail(
            "catalog add",
            "NO_MODULES_ACCEPTED",
            f"{', '.join(sorted(wanted))} passed no gate check -- see the rejections above",
        )

    _store_archives("catalog add", entries, sources)
    write_catalog(entries, CATALOG_PATH)
    typer.echo(f"added: {', '.join(added)}")


@catalog_app.command("mirror")
def catalog_mirror() -> None:
    """Vendor every Patchstorage ORAC upload without deleting vanished uploads."""
    current_catalog = read_catalog(CATALOG_PATH)
    skipped = 0
    discovered = 0
    try:
        if _mirror_fetcher is not None:
            sources = _mirror_fetcher()
        else:
            with live_httpx_client() as client:
                typer.echo("Discovering ORAC uploads...")
                items = discover_union_items(client)
                discovered = len(items)
                entries_by_source: dict[str, list[CatalogEntry]] = {}
                for entry in current_catalog:
                    if entry.source != "orhack":
                        entries_by_source.setdefault(entry.source, []).append(entry)
                pending = [
                    item for item in items if not _mirror_source_satisfied(item, entries_by_source)
                ]
                skipped = discovered - len(pending)
                display = {"text": ""}
                with typer.progressbar(
                    [item["id"] for item in pending],
                    label="Downloading",
                    item_show_func=lambda _item: display["text"],
                ) as progress:
                    def report(slug: str, state: str) -> None:
                        display["text"] = {
                            "downloading": f"... {slug}",
                            "downloaded": f"GOT {slug}",
                            "skipped": f"SKIP {slug}",
                            "failed": f"FAIL {slug}",
                        }[state]
                        progress.render_progress()

                    sources = discover_sources(client, progress, report)
                    display["text"] = ""
                    progress.render_progress()
    except (httpx.HTTPError, PatchstorageError) as exc:
        _fail("catalog mirror", "SOURCE_UNREACHABLE", f"could not reach Patchstorage: {exc}")

    entries = _rebuild("catalog mirror", sources)
    accepted_sources = {e.source for e in entries if e.source != "orhack"}
    verdict = {"text": ""}
    with typer.progressbar(
        list(sources),
        label="Verification",
        show_eta=False,
        item_show_func=lambda _item: verdict["text"],
    ) as progress:
        for slug in progress:
            verdict["text"] = f"{'OK' if slug in accepted_sources else 'REJECT'} {slug}"
            progress.render_progress()
        verdict["text"] = ""
        progress.render_progress()
    retained = [
        e for e in current_catalog if e.source != "orhack" and e.source not in accepted_sources
    ]
    merged = sorted(entries + retained, key=lambda e: e.key)

    _store_archives("catalog mirror", entries, sources)
    write_catalog(merged, CATALOG_PATH)
    typer.echo(
        f"mirrored {discovered or len(sources)} upload(s); {len(sources)} downloaded; "
        f"{skipped} unchanged; {len(accepted_sources)} accepted; "
        f"{len(retained)} retained from unavailable/rejected uploads"
    )


@catalog_app.command("update")
def catalog_update(
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Re-fetch every module already in the catalog and prune what upstream dropped.

    Only refreshes what the catalog already names -- adding a module is
    `rig catalog add`. An upload that has disappeared from Patchstorage is
    reported and left in place: its archive is committed, so the rig still
    works, and dropping a module a song may use is not this command's call.
    """
    current = read_catalog(CATALOG_PATH)
    wanted = {e.source for e in current if e.source != "orhack"}
    if not wanted:
        typer.echo("catalog holds no community modules -- add one with `rig catalog add SLUG`")
        return

    sources = _fetch_sources("catalog update", wanted)
    gone = sorted(wanted - set(sources))
    for source in gone:
        typer.echo(f"warning: {source} is no longer on Patchstorage -- keeping the stored archive")

    entries = _rebuild("catalog update", sources)
    kept = [e for e in current if e.source in gone]
    merged = sorted(entries + kept, key=lambda e: e.key)

    if dry_run:
        typer.echo(f"{len(merged)} entries, {len(gone)} no longer upstream (dry run)")
        return

    _store_archives("catalog update", merged, sources)
    write_catalog(merged, CATALOG_PATH)
    typer.echo(f"{len(merged)} entries written, {len(gone)} no longer upstream")


def _palette_transport(command: str) -> Transport:
    """The test seam (`_transport`) wins when set; otherwise the mounted USB card."""
    if _transport is not None:
        return _transport
    return resolve_card(_card_roots)


@palette_app.command("install")
def palette_install() -> None:
    """Install every compatible community module to the card for auditioning.

    Fills the ORHACK module browser so a blank preset can be built from the full
    palette on the device. These modules are unmanaged: `rig push` leaves them
    in place and never authors a preset from them -- a chain you keep is still
    written in YAML and pushed.
    """
    catalog = read_catalog(CATALOG_PATH)
    entries = compatible_community_entries(catalog)
    if not entries:
        typer.echo("palette install: no compatible community modules in the catalog")
        return

    plan = plan_palette(entries, _module_source or StoredArchiveModuleSource(MODULES_DIR))
    if plan.unavailable:
        names = ", ".join(f"{key} ({reason})" for key, reason in sorted(plan.unavailable))
        _fail(
            "palette install",
            "MODULE_UNAVAILABLE",
            f"the repo cannot produce {len(plan.unavailable)} pinned module(s); nothing installed: {names}",
        )

    try:
        live = _palette_transport("palette install")
        installed = install_palette(live, plan.installs, on_step=lambda key: typer.echo(f"  {key}"))
    except CardDetectionError as exc:
        _fail("palette install", exc.code, str(exc))
    except OrhackIntegrityError as exc:
        _fail("palette install", exc.code, str(exc))

    typer.echo(f"palette install: {len(installed)} module(s) installed to media/orhack/user-modules")


@palette_app.command("clear")
def palette_clear() -> None:
    """Remove palette-installed modules from the card.

    Leaves modules a song owns (installed by `rig push`) untouched.
    """
    catalog = read_catalog(CATALOG_PATH)
    entries = compatible_community_entries(catalog)

    try:
        live = _palette_transport("palette clear")
        removed = clear_palette(live, entries, on_step=lambda key: typer.echo(f"  {key}"))
    except CardDetectionError as exc:
        _fail("palette clear", exc.code, str(exc))

    typer.echo(f"palette clear: {len(removed)} module(s) removed")


if __name__ == "__main__":
    app()
