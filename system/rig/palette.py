"""`rig palette` -- fill the card's user-module tree with every compatible
community module, for on-device auditioning.

Push installs only the modules a song references and garbage-collects the rest,
so the native ORHACK loop -- initialise a blank preset, slot in any module --
is impossible to reach from songs alone: a module a song never names is never
on the card. Palette exists to make that loop possible without inventing songs.

It writes the modules as *unmanaged* files: it never touches push's
`managed.json` ledger, and push's cleanup only ever deletes paths that ledger
records. So a palette-installed module survives every later `rig push`
untouched, exactly like a module a musician copied on by hand. Nothing here
compiles a preset or changes device config -- auditioning is exploration, not
authored state. A chain you decide to keep still gets written in YAML and
reaches the card through push.

Deliberately outside the push transaction: this is a convenience, not the
reproducibility path, so it plans first (refusing if the repo cannot produce
every module) and then writes module by module. An interrupted install is
re-run, not rolled back.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Callable, Optional

from rig.catalog.entry import CatalogEntry
from rig.push import module_install_dir, verify_orhack_structure
from rig.push.modules import USER_MODULES_ROOT, ModuleSource, ModuleSourceUnavailable
from rig.transport.base import Transport

# Push records the community modules it owns here (runner writes it as
# {"modules": {key: moduleType}}). Palette reads it only to know which module
# directories belong to push, so `clear` leaves those alone.
MANAGED_LEDGER_PATH = f"{USER_MODULES_ROOT}/.rig/managed.json"

OnStep = Optional[Callable[[str], None]]


@dataclass(frozen=True)
class PalettePlan:
    installs: list[tuple[CatalogEntry, dict[str, bytes]]]  # entry -> files, relative to its install dir
    unavailable: list[tuple[str, str]]  # (key, reason) -- repo cannot produce the module


def compatible_community_entries(catalog: list[CatalogEntry], lock: dict) -> list[CatalogEntry]:
    """Every locked community module worth auditioning: all of them except the
    few whose runtime path would shadow an ORHACK built-in.

    Community modules install under a separate root and keep the catalog's
    `@source` suffix in their `moduleType`, so they never collide with built-ins
    or with each other -- with one pointless exception. When an upload's path
    minus that suffix equals a built-in's path, it is the ORAC ancestor of a
    module ORHACK already ships; installing it only clutters the browser with a
    near-identical (often inferior) duplicate of a module already on the device.
    Those are dropped; nothing else is.
    """
    builtins = {e.module_type for e in catalog if e.source == "orhack"}
    locked = set(lock.get("modules", {}))
    kept = [
        e
        for e in catalog
        if e.source != "orhack"
        and e.key in locked
        and e.module_type.rsplit("@", 1)[0] not in builtins
    ]
    return sorted(kept, key=lambda e: e.key)


def plan_palette(entries: list[CatalogEntry], module_source: ModuleSource) -> PalettePlan:
    """Read every module's installable files from the stored archives.

    All-or-nothing by intent: a module the repo pins but cannot produce is a
    repo-integrity problem, not something to install around. The caller refuses
    the whole run rather than leaving a half-populated palette on the card.
    """
    installs: list[tuple[CatalogEntry, dict[str, bytes]]] = []
    unavailable: list[tuple[str, str]] = []
    for entry in entries:
        try:
            installs.append((entry, module_source.fetch(entry)))
        except ModuleSourceUnavailable as exc:
            unavailable.append((entry.key, str(exc)))
    return PalettePlan(installs=installs, unavailable=unavailable)


def install_palette(
    transport: Transport,
    installs: list[tuple[CatalogEntry, dict[str, bytes]]],
    on_step: OnStep = None,
) -> list[str]:
    """Write each planned module into `media/orhack/user-modules/<moduleType>`.

    Each module is replaced whole (deleted then rewritten) so a re-install after
    an upstream shrink leaves no orphan files behind. The managed ledger is
    intentionally left untouched -- see the module docstring.
    """
    verify_orhack_structure(transport)
    installed: list[str] = []
    for entry, files in installs:
        dest = module_install_dir(entry)
        if transport.exists(dest):
            transport.delete(dest)
        for rel, data in files.items():
            transport.write(f"{dest}/{rel}", data)
        if on_step is not None:
            on_step(entry.key)
        installed.append(entry.key)
    transport.flush()
    return installed


def clear_palette(
    transport: Transport, entries: list[CatalogEntry], on_step: OnStep = None
) -> list[str]:
    """Remove palette-installed modules, leaving push-managed ones in place.

    A module the ledger records belongs to a song and is push's to remove, not
    palette's. Everything else in the compatible set is ours to clear.
    """
    protected = _managed_module_types(transport)
    removed: list[str] = []
    for entry in entries:
        if entry.module_type in protected:
            continue
        dest = module_install_dir(entry)
        if transport.exists(dest):
            transport.delete(dest)
            if on_step is not None:
                on_step(entry.key)
            removed.append(entry.key)
    transport.flush()
    return removed


def _managed_module_types(transport: Transport) -> set[str]:
    if not transport.exists(MANAGED_LEDGER_PATH):
        return set()
    ledger = json.loads(transport.read(MANAGED_LEDGER_PATH).decode("utf-8"))
    return set(ledger.get("modules", {}).values())
