"""Step 2 of push: verify ORHACK, reconcile community modules against the lock.

See docs/workflows/push.md "Reconcile modules", docs/platform/card.md
("install_package.sh" offline verification), docs/catalog.md "Install layout
and category" / "Versioning", docs/decisions.md #29, #45, #57.

Never installs or repairs ORHACK itself (#45) -- `verify_orhack_manifest`
only reads. Community-module install/replace needs the module's actual file
content, which this package cannot fabricate or cache; it is fetched through
an injected `ModuleSource` so tests exercise the reconciliation *logic*
against a fake, exactly like `rig.catalog.patchstorage` is never reached by
a test (see that module's docstring). Task 8's CLI is responsible for
wiring a real, network-backed `ModuleSource`.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Optional, Protocol

from rig.catalog.entry import CatalogEntry
from rig.errors import CodedError
from rig.push.fsutil import list_files_recursive
from rig.push.hashing import hash_file_map
from rig.transport.base import Transport, normalize_path

MANIFEST_PATH = "Patches/0RHACK/manifest.txt"
USER_MODULES_ROOT = "media/orhack/user-modules"


class OrhackIntegrityError(CodedError):
    pass


def verify_orhack_structure(transport: Transport) -> None:
    """The two markers `rig.transport.card.is_card_root` already checks are
    necessary but not sufficient for push -- a card that merely has both
    directories but an incomplete install would fail loudly downstream
    instead of here. Cheap, offline, no manifest walk."""
    if not transport.exists(MANIFEST_PATH):
        raise OrhackIntegrityError(
            "ORHACK_NOT_INSTALLED",
            f"{MANIFEST_PATH} is missing -- ORHACK does not appear to be installed on this "
            "card; push never installs or repairs it (decision #45)",
        )


def verify_orhack_manifest(transport: Transport) -> None:
    """Recompute sha1 for every file `manifest.txt` lists and compare --
    the same check `install_package.sh` performs, run offline against an
    already-installed card. Never repairs a mismatch; only reports it."""
    verify_orhack_structure(transport)
    manifest_bytes = transport.read(MANIFEST_PATH)
    manifest = manifest_bytes.decode("utf-8")
    problems: list[str] = []
    entries: list[tuple[str, str]] = []
    for line in manifest.splitlines():
        line = line.rstrip("\n")
        if not line.strip():
            continue
        digest, sep, rel = line.partition("  ")
        if not sep:
            raise OrhackIntegrityError(
                "ORHACK_MANIFEST_MALFORMED", f"manifest.txt line is not sha1sum-formatted: {line!r}"
            )
        entries.append((digest, rel))
        normalize_path(f"Patches/{rel}")

    remote_check = getattr(transport, "check_sha1_manifest", None)
    if remote_check is not None:
        problem = remote_check(manifest_bytes)
        if problem:
            raise OrhackIntegrityError(
                "ORHACK_INTEGRITY_FAILED",
                "ORHACK installation does not match its manifest -- push never repairs this: " + problem,
            )
        return

    for digest, rel in entries:
        # manifest.txt paths are relative to Patches/ ("0RHACK/mother.pd");
        # the manifest itself lives inside that tree, at Patches/0RHACK/manifest.txt.
        card_path = f"Patches/{rel}"
        if not transport.exists(card_path):
            problems.append(f"missing: {rel}")
            continue
        actual = hashlib.sha1(transport.read(card_path)).hexdigest()
        if actual != digest:
            problems.append(f"modified: {rel}")
    if problems:
        shown = problems[:10]
        more = f" (+{len(problems) - 10} more)" if len(problems) > 10 else ""
        raise OrhackIntegrityError(
            "ORHACK_INTEGRITY_FAILED",
            "ORHACK installation does not match its manifest -- push never repairs this: "
            + "; ".join(shown)
            + more,
        )


class ModuleSourceUnavailable(RuntimeError):
    """The module's stored archive could not be read or does not contain the
    module the catalog entry names -- missing from `modules/`, failing its
    pinned digest, or no longer passing the gate. Always a hard refusal: the
    repo is meant to carry every module it pins, so this means the repo is
    incomplete, not that a remote service is having a bad day."""


class ModuleSource(Protocol):
    def fetch(self, entry: CatalogEntry) -> dict[str, bytes]:
        """The module's exact installable file set, path relative to its
        own install directory -> bytes, as pinned by `.rig/modules.lock`.
        Raises `ModuleSourceUnavailable` if it cannot be produced."""
        ...


def module_install_dir(entry: CatalogEntry) -> str:
    """Card-relative install directory for one community module
    (docs/catalog.md "Install layout and category")."""
    return f"{USER_MODULES_ROOT}/{entry.module_type}"


def installed_content_hash(transport: Transport, entry: CatalogEntry) -> Optional[str]:
    """The installed module's content hash, or None if nothing is installed
    at its install directory (docs/workflows/push.md: "reconcile ... by
    content hash")."""
    root = module_install_dir(entry)
    rel_paths = list_files_recursive(transport, root)
    if not rel_paths:
        return None
    files = {rel: transport.read(f"{root}/{rel}") for rel in rel_paths}
    return hash_file_map(files)


@dataclass(frozen=True)
class ModuleInstall:
    entry: CatalogEntry
    files: dict[str, bytes]  # relative to module_install_dir(entry)


@dataclass(frozen=True)
class ModuleReconcilePlan:
    to_install: list[ModuleInstall]  # missing on the card, read from modules/
    to_replace: list[ModuleInstall]  # present but content hash mismatch
    up_to_date: list[CatalogEntry]  # present and matching
    unavailable: list[CatalogEntry]  # stored archive unreadable -- caller must refuse


def plan_module_reconciliation(
    transport: Transport,
    community_entries: list[CatalogEntry],
    module_source: ModuleSource,
) -> ModuleReconcilePlan:
    """Reconcile every community module named in the (already-loaded) lock's
    catalog entries against what is installed on the card.

    Repo-wide by construction -- callers pass every locked community entry,
    never a song-scoped subset, because "one card holds one copy"
    (docs/decisions.md #57).
    """
    to_install: list[ModuleInstall] = []
    to_replace: list[ModuleInstall] = []
    up_to_date: list[CatalogEntry] = []
    unavailable: list[CatalogEntry] = []

    for entry in community_entries:
        installed_hash = installed_content_hash(transport, entry)
        try:
            files = module_source.fetch(entry)
        except ModuleSourceUnavailable:
            # Unlike a network fetch, a stored archive that cannot be read is
            # never a transient condition to skip past: the repo pins a module
            # it does not carry, and what is installed on the card cannot be
            # verified against anything.
            unavailable.append(entry)
            continue

        target_hash = hash_file_map(files)
        if installed_hash is None:
            to_install.append(ModuleInstall(entry=entry, files=files))
        elif installed_hash != target_hash:
            to_replace.append(ModuleInstall(entry=entry, files=files))
        else:
            up_to_date.append(entry)

    return ModuleReconcilePlan(
        to_install=to_install,
        to_replace=to_replace,
        up_to_date=up_to_date,
        unavailable=unavailable,
    )
