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
    find_sources_by_slug,
    ingest_pinned_builtins,
    live_httpx_client,
    read_catalog,
    read_lock,
    write_archive,
    write_catalog,
    write_lock,
)
from rig.compile import CompileError, SampleCompileError, scan_wav_folder
from rig.hardware import (
    Device,
    DeviceUnavailable,
    HardwareCheckError,
    MidiOutput,
    MidiUnavailable,
    SongMeasurement,
    SshDevice,
    WinMidiOutput,
    make_subject,
    measure_song,
    read_baseline,
    regression_warnings,
    write_baseline,
)
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
from rig.transport import CardDetectionError, SshTransport, SshTransportError, Transport, TransportPathError

app = typer.Typer(no_args_is_help=True, add_completion=False)
catalog_app = typer.Typer(no_args_is_help=True)
app.add_typer(catalog_app, name="catalog")

# Repo layout -- resolved against the current working directory, same
# convention `catalog update` (below) already uses.
SONGS_DIR = Path("songs")
MEDIA_ROOT = Path("media")
# Vendored upload archives, not generated state -- hence top-level, beside
# songs/ and media/, rather than under .rig/ (docs/repo-layout.md).
MODULES_DIR = Path("modules")
CATALOG_DIR = Path(".rig/catalog")
LOCK_PATH = Path(".rig/modules.lock")
STATE_DIR = Path(".rig/state")
KITS_PATH = Path(".rig/kits.yaml")

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
_upgrade_fetcher: Optional[
    Callable[[dict[str, CatalogEntry]], tuple[dict[str, CatalogEntry], dict[str, CandidateSource]]]
] = None
_hardware_device: Optional[Device] = None
_midi_output: Optional[MidiOutput] = None


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


# --- Patchstorage lookup, shared by `catalog add`, `catalog update`, `upgrade` -


def _locked_community_slugs(catalog: list[CatalogEntry], lock: dict) -> set[str]:
    locked_keys = set(lock.get("modules", {}))
    return {e.source for e in catalog if e.source != "orhack" and e.key in locked_keys}


def _fetch_sources(command: str, slugs: set[str]) -> dict[str, CandidateSource]:
    """Fetch the named uploads from Patchstorage. The only network path in
    the tool besides `rig upgrade`, which routes through here too."""
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


# --- commands ------------------------------------------------------------


@app.command()
def push(
    song: Optional[list[str]] = typer.Argument(None),
    dry_run: bool = typer.Option(False, "--dry-run"),
    force: bool = typer.Option(False, "--force"),
    transport: str = typer.Option("ssh", "--transport", help="ssh (default) or usb"),
    host: str = typer.Option("organelle", "--host", help="OpenSSH host alias"),
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

    module_source = _module_source or StoredArchiveModuleSource(MODULES_DIR, lock)

    if transport not in {"ssh", "usb"}:
        _fail("push", "UNKNOWN_TRANSPORT", "--transport must be 'ssh' or 'usb'")
    live_transport = _transport or (None if transport == "usb" or _card_roots is not None else SshTransport(host))

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
            transport=live_transport,
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
    except SshTransportError as exc:
        _fail("push", "SSH_TRANSPORT_ERROR", str(exc))

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
    transport: str = typer.Option("ssh", "--transport", help="ssh (default) or usb"),
    host: str = typer.Option("organelle", "--host", help="OpenSSH host alias"),
) -> None:
    """Detect card drift and open one PR per drifted song."""
    try:
        song_docs = _load_all_song_docs(SONGS_DIR)
    except SongParseError as exc:
        _fail("pull", "SONG_PARSE_ERROR", str(exc))

    selected = _resolve_selection("pull", song, song_docs)
    catalog, lock, kits = _read_catalog_lock_kits("pull")

    if transport not in {"ssh", "usb"}:
        _fail("pull", "UNKNOWN_TRANSPORT", "--transport must be 'ssh' or 'usb'")
    live_transport = _transport or (None if transport == "usb" or _card_roots is not None else SshTransport(host))

    try:
        result = run_pull(
            song_docs=song_docs,
            catalog=catalog,
            kits=kits,
            media_root=MEDIA_ROOT,
            state_dir=STATE_DIR,
            repo_root=Path("."),
            selected=selected,
            transport=live_transport,
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
    except SshTransportError as exc:
        _fail("pull", "SSH_TRANSPORT_ERROR", str(exc))

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


def _check_stored_archives(catalog: list[CatalogEntry], lock: dict) -> list[str]:
    """Re-gate every locked module's committed archive.

    This is the repo's reproducibility check: it proves `.rig/catalog/` was
    generated from the archives actually present in `modules/`, rather than
    hand-edited, and that every archive still passes the safety and ARM32 ELF
    checks it passed when it was added. Cheap because the catalog is a
    shopping list -- it covers the modules this rig uses, not all of
    Patchstorage.
    """
    module_source = StoredArchiveModuleSource(MODULES_DIR, lock)
    locked_keys = set(lock.get("modules", {}))
    problems: list[str] = []
    for entry in catalog:
        if entry.source == "orhack" or entry.key not in locked_keys:
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

    catalog, lock, kits = _read_catalog_lock_kits("lint")
    songs = {sid: doc.song for sid, doc in song_docs.items()}

    has_error = False

    for problem in _check_stored_archives(catalog, lock):
        typer.echo(f"error: MODULE_ARCHIVE: {problem}")
        has_error = True

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


def _echo_hardware_measurement(measurement: SongMeasurement) -> None:
    verdict = "pass" if measurement.passed else "fail"
    typer.echo(
        f"{measurement.song_id}: {verdict}; stimulus v1; "
        f"load median {measurement.load_ms:.1f} ms; "
        f"idle CPU mean/p95 {measurement.idle_cpu.mean:.1f}/{measurement.idle_cpu.p95:.1f}%; "
        f"active CPU mean/p95 {measurement.active_cpu.mean:.1f}/{measurement.active_cpu.p95:.1f}%"
    )
    for line in measurement.errors:
        typer.echo(f"error: {measurement.song_id}: PD_LOAD_ERROR: {line}")
    if measurement.underruns:
        typer.echo(f"error: {measurement.song_id}: ALSA_UNDERRUN: {measurement.underruns}")
    for warning in measurement.warnings:
        typer.echo(f"warning: {measurement.song_id}: {warning}")


@app.command("hardware-check")
def hardware_check(
    song: Optional[list[str]] = typer.Argument(None),
    host: str = typer.Option("organelle", "--host", help="OpenSSH host alias"),
    midi_port: str = typer.Option(..., "--midi-port", help="Exact Windows MIDI output name"),
) -> None:
    """Measure load time and Pd CPU on an Organelle S2."""
    try:
        song_docs = _load_all_song_docs(SONGS_DIR)
    except SongParseError as exc:
        _fail("hardware-check", "SONG_PARSE_ERROR", str(exc))
    selected = _resolve_selection("hardware-check", song, song_docs)
    selected_ids = sorted(song_docs) if selected is None else sorted(selected)
    catalog, lock, kits = _read_catalog_lock_kits("hardware-check")
    songs = {sid: doc.song for sid, doc in song_docs.items()}
    _require_valid("hardware-check", songs, catalog, kits, MEDIA_ROOT)

    device = _hardware_device or SshDevice(host)
    midi: MidiOutput | None = _midi_output
    own_midi = midi is None
    try:
        subject = make_subject(device, midi_port, lock)
        before = device.card_hash()
        if midi is None:
            midi = WinMidiOutput(midi_port)
        failed = False
        pending_baselines: list[SongMeasurement] = []
        for song_id in selected_ids:
            measured = measure_song(song_id, songs[song_id], device, midi)
            baseline = read_baseline(STATE_DIR, song_id)
            warnings = regression_warnings(measured, baseline, subject)
            measured = SongMeasurement(
                measured.song_id, measured.load_ms, measured.idle_cpu,
                measured.active_cpu, measured.errors, measured.underruns, warnings,
            )
            _echo_hardware_measurement(measured)
            failed |= not measured.passed
            if measured.passed and (baseline is None or baseline.subject.key != subject.key):
                pending_baselines.append(measured)
        after = device.card_hash()
        if before != after:
            typer.echo("error: CARD_CHANGED: /sdcard changed during hardware check", err=True)
            failed = True
        else:
            for measured in pending_baselines:
                write_baseline(STATE_DIR, measured, subject)
                typer.echo(f"baseline written: {measured.song_id}")
        if failed:
            raise typer.Exit(code=1)
    except DeviceUnavailable as exc:
        typer.echo(f"hardware-check: unavailable: {exc}")
    except (HardwareCheckError, MidiUnavailable) as exc:
        _fail("hardware-check", "CHECK_FAILED", str(exc))
    finally:
        if own_midi and midi is not None:
            midi.close()


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
    the modules this rig actually uses, and nothing else. This is one of the
    two commands allowed to reach the network (`rig upgrade` is the other);
    everything afterwards reads the committed `.rig/catalog/` and `modules/`.
    """
    wanted = set(slug)
    existing_sources = {e.source for e in read_catalog(CATALOG_DIR) if e.source != "orhack"}
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
    write_catalog(entries, CATALOG_DIR)
    write_lock(entries, LOCK_PATH)
    typer.echo(f"added: {', '.join(added)}")


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
    current = read_catalog(CATALOG_DIR)
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
    write_catalog(merged, CATALOG_DIR)
    write_lock(merged, LOCK_PATH)
    typer.echo(f"{len(merged)} entries written, {len(gone)} no longer upstream")


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


def _fetch_upgraded_entries(
    requested: dict[str, CatalogEntry],
) -> tuple[dict[str, CatalogEntry], dict[str, CandidateSource]]:
    """Module key -> its freshly re-ingested `CatalogEntry`, live from
    Patchstorage, for every key in `requested` whose upload still exists and
    still passes the catalog gate, plus the fetched sources so their archives
    can be stored. A key absent from the result means it could not be
    refreshed -- the caller treats that as a refusal."""
    wanted_slugs = {entry.source for entry in requested.values()}
    with live_httpx_client() as client:
        sources = find_sources_by_slug(client, wanted_slugs)
    fresh = build_community_catalog(list(sources.values()))
    return {entry.key: entry for entry in fresh.entries if entry.key in requested}, sources


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
        fresh_by_key, fresh_sources = fetcher(requested)
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
    _store_archives("upgrade", [fresh_by_key[m] for m in module], fresh_sources)
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

    write_text_atomic(path, dump_song(doc))

    chains_state_dir = STATE_DIR / "chains"
    bindings = read_bindings(chains_state_dir, song)
    if old in bindings:
        letter = bindings.pop(old)
        bindings[new] = letter
        write_bindings(chains_state_dir, song, bindings)

    typer.echo(f"renamed: {song}: {old} -> {new}")


if __name__ == "__main__":
    app()
