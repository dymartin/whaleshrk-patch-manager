"""The `ModuleSource` push installs from: `modules/`, on disk, never the network.

Push runs at a venue, before a gig, where there may be no usable wifi -- and
the repo's reproducibility promise ("same repo, same push, same rig") cannot
hold if the module bytes come from a third party who can delete or replace an
upload. So the archives travel with the repo (`rig.catalog.store`) and this
reads them, verifying each against the digest pinned in `.rig/modules.lock`
before anything reaches the card.

`rig catalog add` is the only command that reaches Patchstorage.
"""

from __future__ import annotations

from pathlib import Path

from rig.catalog.archive import CandidateArchive, ZipCandidateArchive
from rig.catalog.entry import CatalogEntry
from rig.catalog.gate import GateAccept, gate_candidate
from rig.catalog.slugs import module_key
from rig.catalog.store import ArchiveStoreError, read_archive
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
    (relative to `rig.push.modules.module_install_dir(entry)`).

    Stripping happens here, on the way to the card, rather than before the
    archive is stored: what is committed stays byte-identical to the upload,
    so its digest still means something against Patchstorage.
    """
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


class StoredArchiveModuleSource:
    """Reads each locked module out of `modules/`, keyed by the upload slug
    and revision the lock records. One archive can hold several modules, so
    parsed archives are cached for the lifetime of one push."""

    def __init__(self, modules_dir: Path, lock: dict):
        self._modules_dir = modules_dir
        self._lock_modules = lock.get("modules", {})
        self._archives: dict[str, CandidateArchive] = {}

    def _archive_for(self, entry: CatalogEntry) -> CandidateArchive:
        if entry.source in self._archives:
            return self._archives[entry.source]

        pin = self._lock_modules.get(entry.key)
        if pin is None:
            raise ModuleSourceUnavailable(f"{entry.key}: not pinned in .rig/modules.lock")
        try:
            data = read_archive(
                self._modules_dir,
                entry.source,
                pin.get("revision") or "unknown",
                pin.get("archive_sha256") or "",
            )
        except ArchiveStoreError as exc:
            raise ModuleSourceUnavailable(f"{entry.key}: {exc}") from exc

        archive = ZipCandidateArchive(data)
        self._archives[entry.source] = archive
        return archive

    def fetch(self, entry: CatalogEntry) -> dict[str, bytes]:
        archive = self._archive_for(entry)

        # Re-gate to find this module's own directory inside the (possibly
        # multi-module) archive -- the same walk ingest did originally, so
        # matching on the recomputed key finds the directory that produced
        # this exact catalog entry.
        gated = gate_candidate(archive)
        if not isinstance(gated, GateAccept):
            raise ModuleSourceUnavailable(f"{entry.key}: stored archive does not pass the catalog gate")
        module_dir = next(
            (d for d in gated.module_dirs if module_key(d.module_json["display"], entry.source) == entry.key),
            None,
        )
        if module_dir is None:
            raise ModuleSourceUnavailable(f"{entry.key}: module not found inside its stored archive")

        files = extract_module_files(archive, module_dir.path)
        if any(Path(rel).name.lower() == ABL_LINK_FILENAME for rel in files):
            # docs/catalog.md "Strip on install": Organelle_OS renames this
            # file away on every patch launch, so a module needing it never
            # loads its external -- unsupported, not merely stripped.
            raise ModuleSourceUnavailable(
                f"{entry.key}: ships {ABL_LINK_FILENAME}, which Organelle_OS renames away on "
                "every patch launch -- unsupported"
            )
        return files
