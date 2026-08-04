"""Top-level catalog build: runs the gate over every candidate, merges with
built-ins, and resolves the two module-level (not candidate-level) reject
conditions that need the full catalog in view.

`moduleType` note: state.md says a slot's moduleType "is a path resolved
against userModuleDir first, then the built-in modules/ directory" -- both
are search-path roots, not part of the stored value. So a built-in's
moduleType is its path relative to `modules/` (e.g.
"effects/delay/spiraldelay") and a community module's is its path relative
to `userModuleDir` (`<category>/<name>`, decision #32: "category is part of
moduleType") -- the *same* namespace. That is what makes "a community path
shadowing a built-in" (docs/catalog.md) a real, checkable collision: a
community module and a built-in can produce the identical moduleType string.
"""

from __future__ import annotations

from dataclasses import dataclass

from .archive import CandidateArchive
from .category import resolve_category
from .entry import CatalogEntry, VersionInfo
from .gate import GateAccept, GateReject, ModuleDir, RejectReason, gate_candidate
from .params import parse_parameters
from .sidecar import scan_module_sidecars
from .slugs import module_key


@dataclass(frozen=True)
class CandidateSource:
    """Everything the ingest pipeline needs for one Patchstorage candidate."""

    id: int
    archive: CandidateArchive
    detail: dict  # raw /patches/<id> response
    archive_sha256: str
    category_override: str | None = None


@dataclass(frozen=True)
class IngestReject:
    # None for duplicate-module-path rejects: the collision is cross-
    # candidate (a community module against a built-in, or two different
    # uploads), so no single candidate id identifies it.
    candidate_id: int | None
    reason: RejectReason
    message: str
    module_path: str | None = None  # set for module-level rejects


@dataclass(frozen=True)
class CatalogBuildResult:
    entries: list[CatalogEntry]
    rejects: list[IngestReject]


class KeyCollisionError(RuntimeError):
    """Two catalog entries produced the identical `slug(display)@source` key.

    Source-qualification makes this structurally impossible across
    different sources; it can only happen if one source (one built-in tree
    or one upload) declares the same display name twice. Never silently
    dropped -- writing both to the same catalog filename would silently
    discard one of them.
    """


def _module_pd_texts(archive: CandidateArchive, module_dir: str) -> dict[str, str]:
    """Every .pd file inside a module's own directory subtree.

    `module_dir == ""` means the module sits at the archive root -- there is
    no separate wrapping structure, so every .pd file in the archive is part
    of it.
    """
    prefix = f"{module_dir}/" if module_dir else ""
    texts: dict[str, str] = {}
    for entry in archive.entries():
        if entry.is_dir or not entry.name.lower().endswith(".pd"):
            continue
        if module_dir and not entry.name.startswith(prefix):
            continue
        try:
            texts[entry.name] = archive.read(entry.name).decode("utf-8", errors="replace")
        except FileNotFoundError:
            continue
    return texts


def _file_id_for(detail: dict, archive_sha256: str) -> int | None:
    files = detail.get("files") or []
    if len(files) == 1:
        return files[0].get("id")
    # Multiple files on one upload: no direct sha->file mapping is exposed by
    # the API response captured in the fixture, so record nothing rather
    # than guess which file the pinned archive corresponds to.
    return None


def _build_community_module(
    source: CandidateSource, module_dir: ModuleDir
) -> CatalogEntry | IngestReject:
    display = module_dir.module_json["display"]
    upload_slug = source.detail["slug"]
    key = module_key(display, upload_slug)

    pd_texts = _module_pd_texts(source.archive, module_dir.path)
    sidecar_result = scan_module_sidecars(pd_texts)
    if not sidecar_result.is_modelled:
        return IngestReject(
            candidate_id=source.id,
            reason=RejectReason.UNMODELLED_SIDECAR,
            message=(
                f"{display}: unresolved preset sidecar pattern(s) "
                f"{sidecar_result.unresolved!r}"
            ),
            module_path=module_dir.path,
        )

    category_slugs = [c["slug"] for c in source.detail.get("categories", [])]
    category = source.category_override or resolve_category(category_slugs)
    # The trailing path component is the catalog key itself (already
    # source-qualified and unique), not the archive's own directory name.
    # Real data forced this: 6 community uploads (e.g. a standalone
    # "polystep" re-upload) reuse the exact directory name of an existing
    # built-in in the same category, which a raw-dirname install path would
    # collide on every single time. Qualifying by key makes a community
    # path collide with a built-in only if Patchstorage ever issued an
    # upload slug literally equal to "orhack" -- see docs/catalog.md
    # "Category mapping".
    module_type = f"{category}/{key}"

    tags = sorted(
        {c["slug"] for c in source.detail.get("categories", [])}
        | {t["slug"] for t in source.detail.get("tags", [])}
    )

    params = parse_parameters(display, module_dir.module_json.get("parameters"))

    return CatalogEntry(
        key=key,
        source=upload_slug,
        display=display,
        module_type=module_type,
        category=category,
        category_override=source.category_override,
        tags=tags,
        params=params,
        version=VersionInfo(
            updated_at=source.detail.get("updated_at"),
            file_id=_file_id_for(source.detail, source.archive_sha256),
            archive_sha256=source.archive_sha256,
        ),
        sidecar_templates=sidecar_result.resolved,
    )


def build_community_catalog(
    sources: list[CandidateSource],
) -> tuple[list[CatalogEntry], list[IngestReject]]:
    """Gate every candidate and build its surviving modules' catalog entries.

    Candidate-level rejects (not-a-module, bad-json, wrong-arch, rack-
    redistribution, archive-unsafe) drop the whole candidate. Sidecar
    rejects are module-level: other modules in the same candidate still
    contribute entries.
    """
    entries: list[CatalogEntry] = []
    rejects: list[IngestReject] = []

    for source in sources:
        result = gate_candidate(source.archive)
        if isinstance(result, GateReject):
            rejects.append(
                IngestReject(candidate_id=source.id, reason=result.reason, message=result.message)
            )
            continue
        assert isinstance(result, GateAccept)
        for module_dir in result.module_dirs:
            built = _build_community_module(source, module_dir)
            if isinstance(built, IngestReject):
                rejects.append(built)
            else:
                entries.append(built)

    return entries, rejects


def resolve_duplicate_module_paths(
    builtin_entries: list[CatalogEntry], community_entries: list[CatalogEntry]
) -> tuple[list[CatalogEntry], list[IngestReject]]:
    """Drop any community entry whose moduleType collides with an already-claimed path.

    Built-in paths are fixed, pinned truth and always win outright.
    Community entries are then processed in a fixed, deterministic order
    (ascending candidate key) so a rerun of ingest produces the same result;
    a later collision is rejected, never the earlier claimant.
    """
    claimed: dict[str, str] = {e.module_type: e.key for e in builtin_entries}
    kept: list[CatalogEntry] = []
    rejects: list[IngestReject] = []

    for entry in sorted(community_entries, key=lambda e: e.key):
        owner = claimed.get(entry.module_type)
        if owner is not None:
            rejects.append(
                IngestReject(
                    candidate_id=None,
                    reason=RejectReason.DUPLICATE_MODULE_PATH,
                    message=(
                        f"{entry.key}: moduleType {entry.module_type!r} already "
                        f"claimed by {owner!r}"
                    ),
                    module_path=entry.module_type,
                )
            )
            continue
        claimed[entry.module_type] = entry.key
        kept.append(entry)

    return kept, rejects


def _check_no_key_collisions(entries: list[CatalogEntry]) -> None:
    seen: dict[str, str] = {}
    for entry in entries:
        if entry.key in seen:
            raise KeyCollisionError(
                f"catalog key {entry.key!r} produced by both {seen[entry.key]!r} "
                f"and {entry.module_type!r}"
            )
        seen[entry.key] = entry.module_type


def build_catalog(
    builtin_entries: list[CatalogEntry], sources: list[CandidateSource]
) -> CatalogBuildResult:
    community_entries, sidecar_rejects = build_community_catalog(sources)
    surviving_community, path_rejects = resolve_duplicate_module_paths(
        builtin_entries, community_entries
    )
    all_entries = list(builtin_entries) + surviving_community
    _check_no_key_collisions(all_entries)
    all_rejects = sidecar_rejects + path_rejects
    return CatalogBuildResult(entries=all_entries, rejects=all_rejects)
