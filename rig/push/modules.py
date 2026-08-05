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
from rig.push.fsutil import list_files_recursive
from rig.push.hashing import hash_file_map
from rig.transport.base import Transport

MANIFEST_PATH = "Patches/0RHACK/manifest.txt"
USER_MODULES_ROOT = "media/orhack/user-modules"


class OrhackIntegrityError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


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
    manifest = transport.read(MANIFEST_PATH).decode("utf-8")
    problems: list[str] = []
    for line in manifest.splitlines():
        line = line.rstrip("\n")
        if not line.strip():
            continue
        digest, sep, rel = line.partition("  ")
        if not sep:
            raise OrhackIntegrityError(
                "ORHACK_MANIFEST_MALFORMED", f"manifest.txt line is not sha1sum-formatted: {line!r}"
            )
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
    """The module's source (Patchstorage) could not be reached. Caller
    decides whether that is a silent skip or a hard error -- see
    `plan_module_reconciliation`."""


class ModuleSource(Protocol):
    def fetch(self, entry: CatalogEntry) -> dict[str, bytes]:
        """The module's exact installable file set, path relative to its
        own install directory -> bytes, as pinned by `.rig/modules.lock`.
        Raises `ModuleSourceUnavailable` if unreachable."""
        ...


class UpdateChecker(Protocol):
    def check_update(self, entry: CatalogEntry) -> Optional[str]:
        """A human-readable description of a newer version than the one
        pinned, or None if the pinned version is current. Raises
        `ModuleSourceUnavailable` if unreachable -- callers must treat that
        as a silent skip, never a push blocker (decision #29)."""
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
    to_install: list[ModuleInstall]  # missing on the card, fetched successfully
    to_replace: list[ModuleInstall]  # present but content hash mismatch
    up_to_date: list[CatalogEntry]  # present and matching, or unreachable-but-already-installed
    unavailable: list[CatalogEntry]  # absent on the card AND unreachable -- caller must refuse
    updates_available: dict[str, str]  # entry key -> description, report-only


def plan_module_reconciliation(
    transport: Transport,
    community_entries: list[CatalogEntry],
    module_source: ModuleSource,
    update_checker: Optional[UpdateChecker] = None,
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
    updates_available: dict[str, str] = {}

    for entry in community_entries:
        installed_hash = installed_content_hash(transport, entry)
        try:
            files = module_source.fetch(entry)
        except ModuleSourceUnavailable:
            if installed_hash is None:
                # Absent on the card and its source cannot be reached: the
                # preset would name a moduleType that never resolves --
                # cannot be skipped (docs/workflows/push.md, decisions #29).
                unavailable.append(entry)
            else:
                # Already installed; merely cannot verify or refresh it
                # right now. Never blocks push (decision #29).
                up_to_date.append(entry)
            continue

        target_hash = hash_file_map(files)
        if installed_hash is None:
            to_install.append(ModuleInstall(entry=entry, files=files))
        elif installed_hash != target_hash:
            to_replace.append(ModuleInstall(entry=entry, files=files))
        else:
            up_to_date.append(entry)

        if update_checker is not None:
            try:
                description = update_checker.check_update(entry)
            except ModuleSourceUnavailable:
                description = None
            if description is not None:
                updates_available[entry.key] = description

    return ModuleReconcilePlan(
        to_install=to_install,
        to_replace=to_replace,
        up_to_date=up_to_date,
        unavailable=unavailable,
        updates_available=updates_available,
    )
