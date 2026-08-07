"""The live, network-backed `ModuleSource`/`UpdateChecker` push installs from.

Lives in `rig.push` rather than `rig.catalog` because it implements protocols
`rig.push.modules` declares: push already depends on catalog, and putting a
`ModuleSourceUnavailable`-raising adapter under catalog would point a second
edge back the other way.

Never reached by a test against the real network -- `tests/conftest.py` blocks
every socket for the whole session, so tests seed `_sources` directly.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import httpx

from rig.catalog.archive import CandidateArchive
from rig.catalog.discovery import find_sources_by_slug, live_httpx_client
from rig.catalog.entry import CatalogEntry
from rig.catalog.gate import GateAccept, gate_candidate
from rig.catalog.ingest import CandidateSource
from rig.catalog.patchstorage import PatchstorageError
from rig.catalog.slugs import module_key
from rig.push.modules import ModuleSourceUnavailable

# docs/catalog.md "Strip on install": junk every real archive carries. No doc
# pins an exact editor-swap-file pattern -- vim/emacs' own conventions
# (trailing "~", ".swp"/".swo") are used as a reasonable, documented default,
# a design call rather than a verified spec.
EDITOR_SWAP_SUFFIXES = ("~", ".swp", ".swo")
ABL_LINK_FILENAME = "abl_link~.pd_linux"


def should_strip(rel_path: str) -> bool:
    lower = rel_path.lower()
    if "__macosx" in lower.split("/"):
        return True
    name = lower.rsplit("/", 1)[-1]
    if name.startswith("._") or name == ".ds_store":
        return True
    if lower.endswith(".dll"):
        return True
    if name.endswith(EDITOR_SWAP_SUFFIXES):
        return True
    return False


def extract_module_files(archive: CandidateArchive, module_dir: str) -> dict[str, bytes]:
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
        if not rel or should_strip(rel):
            continue
        files[rel] = archive.read(entry.name)
    return files


class PatchstorageModuleSource:
    """Live `ModuleSource` *and* `UpdateChecker` for push's module
    reconciliation step -- `rig.push.modules`'s own docstring says the CLI is
    responsible for wiring this up.

    One discovery pass covers every locked community module's slug at once,
    cached for the lifetime of one push -- `find_sources_by_slug` has no
    cheaper way to find a specific upload (see its own docstring), so calling
    it once per module would multiply an already-expensive full candidate walk
    by the number of locked community modules.
    """

    def __init__(self, wanted_slugs: set[str]):
        self._wanted = wanted_slugs
        self._sources: Optional[dict[str, CandidateSource]] = None

    def _resolve(self) -> dict[str, CandidateSource]:
        if self._sources is None:
            try:
                with live_httpx_client() as client:
                    self._sources = find_sources_by_slug(client, self._wanted)
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

        files = extract_module_files(source.archive, module_dir.path)
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
