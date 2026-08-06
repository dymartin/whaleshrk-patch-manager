"""Tier 1 (static) validation -- Prompt/09-static-validation.md, docs/validation.md.

`run_static` runs, over every locked module and every song:

- the Phase 1 catalog gate (`rig.catalog.ingest.build_community_catalog`,
  which wraps `rig.catalog.gate.gate_candidate`) -- safe archive, ARM32
  hard-float little-endian ELF, modelled preset sidecars;
- the Phase 2 schema rules and Phase 8 lint rules
  (`rig.song.validate.validate_song`/`validate_songs`).

Neither is reimplemented here -- this module only replays them against the
frozen candidate fixture and the repo's song files, and shapes the result
into the canonical `Report`. No symbol or Pd-object resolution (decision
#68); a local song filter narrows which songs get their own `SongChecks`
entry, never what the catalog gate covers (docs/validation.md "A local song
filter is diagnostic only").

**Why the frozen fixture, not a live re-fetch.** This repo's committed
`.rig/catalog/` and `.rig/modules.lock` were themselves built by gating the
frozen fixture (`rig.catalog.frozen.load_frozen_sources`) -- replaying it is
therefore not a stand-in but the same data the committed catalog came from,
and it needs no network (`rig catalog update` is the only command allowed to
reach Patchstorage live, docs/catalog.md). A locked module whose upload slug
is not in the fixture (ingested after the fixture was frozen, e.g. via a
later `rig catalog update`) cannot be re-gated offline; its check is recorded
`unavailable` rather than silently skipped or assumed to still pass.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

from rig.catalog.entry import CatalogEntry
from rig.catalog.frozen import load_frozen_sources
from rig.catalog.ingest import CandidateSource, build_community_catalog
from rig.song.bindings import read_bindings
from rig.song.kits import KitsConfig
from rig.song.model import Song
from rig.song.validate import validate_song, validate_songs

from .report import (
    CONFIDENCE_STATIC_ONLY,
    REPORT_SCHEMA_VERSION,
    STATUS_FAIL,
    STATUS_PASS,
    STATUS_UNAVAILABLE,
    TIER_STATIC,
    VERDICT_FAIL,
    VERDICT_PASS,
    CheckResult,
    Report,
    SongChecks,
    Subject,
)

# Pinned per docs/validation.md: derived from the OS build recipe and
# confirmed against upstream source, not yet observed on real hardware.
# Phase 10 replaces PD_VERSION with the observed `pd -version` output.
OS_VERSION = "5.1"
PD_VERSION = "0.53.1+ds-2+deb12u1"
ORHACK_VERSION = "0.52b"

CATALOG_GATE_CHECK_ID = "catalog-gate"
SCHEMA_LINT_CHECK_ID = "schema-lint"

SCOPE_NOTE = (
    "static-only: catalog gate (archive safety, ELF ABI, preset-sidecar "
    "modelling) plus song schema and lint checks. Proves nothing about "
    "whether a module loads, DSP correctness, audio quality, silence, "
    "load time, CPU cost or thermals -- see docs/validation.md "
    "'Deliberately not covered'. A pass here is not evidence the rig is "
    "stage-ready."
)


def catalog_gate_checks(source: CandidateSource) -> list[CheckResult]:
    """Replay the catalog gate over one candidate archive, translating every
    `IngestReject`/admitted module into a `CheckResult` keyed by its check
    id -- a catalog `RejectReason` value for a reject, `catalog-gate` for an
    admitted module."""
    entries, rejects = build_community_catalog([source])
    results = [CheckResult(id=r.reason.value, status=STATUS_FAIL, message=r.message) for r in rejects]
    results += [
        CheckResult(id=CATALOG_GATE_CHECK_ID, status=STATUS_PASS, message=f"{e.key}: admitted")
        for e in entries
    ]
    return results


def locked_module_gate_checks(
    *, catalog: Iterable[CatalogEntry], lock: dict, frozen_sources: Iterable[CandidateSource]
) -> list[CheckResult]:
    """Every check in `catalog_gate_checks`, over every community module
    `.rig/modules.lock` currently pins -- built-ins are excluded, since they
    are pinned to the ORHACK build rather than gated as a Patchstorage
    candidate (docs/catalog.md "Versioning")."""
    catalog_index = {e.key: e for e in catalog}
    locked_keys = set(lock.get("modules", {}))
    wanted_slugs = {
        catalog_index[k].source for k in locked_keys if k in catalog_index and catalog_index[k].source != "orhack"
    }

    source_by_slug: dict[str, CandidateSource] = {}
    for source in frozen_sources:
        slug = source.detail.get("slug")
        if slug in wanted_slugs and slug not in source_by_slug:
            source_by_slug[slug] = source

    results: list[CheckResult] = []
    for slug in sorted(wanted_slugs):
        source = source_by_slug.get(slug)
        if source is None:
            results.append(
                CheckResult(
                    id=CATALOG_GATE_CHECK_ID,
                    status=STATUS_UNAVAILABLE,
                    message=f"{slug}: not present in the frozen fixture -- cannot statically re-verify without its archive",
                )
            )
            continue
        results.extend(catalog_gate_checks(source))
    return results


def _song_checks(
    song_id: str,
    song: Song,
    *,
    catalog: Iterable[CatalogEntry],
    kits: Optional[KitsConfig],
    media_root: Optional[Path],
    bindings_dir: Path,
) -> SongChecks:
    bindings = read_bindings(bindings_dir, song_id)
    result = validate_song(song, catalog=catalog, kits=kits, media_root=media_root, bindings=bindings)
    if result.errors:
        checks = [CheckResult(id=f.code, status=STATUS_FAIL, message=f.message) for f in result.errors]
        status = STATUS_FAIL
    else:
        checks = [CheckResult(id=SCHEMA_LINT_CHECK_ID, status=STATUS_PASS, message="no hard errors")]
        status = STATUS_PASS
    return SongChecks(song=song_id, status=status, checks=checks)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_static(
    *,
    songs: dict[str, Song],
    selected: Optional[set[str]] = None,
    catalog: list[CatalogEntry],
    lock: dict,
    kits: Optional[KitsConfig] = None,
    media_root: Optional[Path] = None,
    bindings_dir: Path,
    frozen_sources: Optional[Iterable[CandidateSource]] = None,
    commit: Optional[str] = None,
    module_lock_digest: Optional[str] = None,
    run_id: Optional[str] = None,
) -> Report:
    """Run the static tier over `songs` (filtered to `selected` for the
    per-song report entries; `None` or empty means every song) and every
    community module `lock` pins. `frozen_sources` defaults to the real
    frozen fixture; tests inject a smaller one."""
    started_at = _now_iso()
    sources = list(frozen_sources) if frozen_sources is not None else load_frozen_sources()

    gate_results = locked_module_gate_checks(catalog=catalog, lock=lock, frozen_sources=sources)
    gate_failures = [c for c in gate_results if c.status == STATUS_FAIL]

    cross = validate_songs(list(songs.values()))
    cross_failures = [CheckResult(id=f.code, status=STATUS_FAIL, message=f.message) for f in cross.errors]

    selected_ids = sorted(songs) if not selected else sorted(selected)
    song_groups = [
        _song_checks(
            sid, songs[sid], catalog=catalog, kits=kits, media_root=media_root, bindings_dir=bindings_dir
        )
        for sid in selected_ids
    ]
    song_failures = [c for group in song_groups for c in group.checks if c.status == STATUS_FAIL]

    failures = cross_failures + gate_failures + song_failures
    verdict = VERDICT_FAIL if failures else VERDICT_PASS

    metrics = {
        "catalog": {
            "modules_gated": sum(1 for c in gate_results if c.status == STATUS_PASS),
            "modules_failed": len(gate_failures),
            "modules_unavailable": sum(1 for c in gate_results if c.status == STATUS_UNAVAILABLE),
        }
    }

    subject = Subject(
        commit=commit,
        report_schema_version=REPORT_SCHEMA_VERSION,
        module_lock_digest=module_lock_digest,
        s2_device_id=None,
        os_version=OS_VERSION,
        pd_version=PD_VERSION,
        orhack_version=ORHACK_VERSION,
        midi_port_name=None,
        stimulus_profile_version=None,
    )

    return Report(
        schema_version=REPORT_SCHEMA_VERSION,
        verdict=verdict,
        tier=TIER_STATIC,
        subject=subject,
        run_id=run_id or uuid.uuid4().hex,
        checks=song_groups,
        metrics=metrics,
        failures=failures,
        started_at=started_at,
        ended_at=_now_iso(),
        confidence=CONFIDENCE_STATIC_ONLY,
        scope_note=SCOPE_NOTE,
    )
