"""ORHACK built-in module ingestion.

Reads the pinned, verified ORHACK 0.52b module tree from `fixtures/card/`
(the same frozen, SHA-256-verified archive Task 0 built -- see
docs/platform/README.md). Built-ins are not "discovered" the way community
modules are: ORHACK's shipped version is pinned, so its module tree is fixed
data, not a live source.

Recursion mirrors `loadModuleDir`: a directory that carries both module.pd
and module.json registers as a module and is never descended into further,
so a nested module.json inside a registered module's own directory (e.g.
`effects/delay/spiraldelay/module/module.json`) is invisible to the runtime
and must be invisible here too -- see docs/platform/modules.md.
"""

from __future__ import annotations

import json
from pathlib import Path

from rig.transport.base import Transport
from rig.transport.memory import InMemoryTransport

from .entry import CatalogEntry, VersionInfo
from .params import parse_parameters
from .slugs import module_key

MODULES_ROOT = "Patches/0RHACK/modules"
SOURCE = "orhack"
EMPTY_MODULE_TYPE = "-empty-"

# The pinned, SHA-256-verified ORHACK 0.52b tree -- see docs/platform/README.md.
FIXTURE_CARD_ROOT = Path(__file__).resolve().parent.parent.parent / "fixtures" / "card"


def _walk(transport: Transport, root: str, rel_dir: str, out: list[CatalogEntry]) -> None:
    full_dir = f"{root}/{rel_dir}" if rel_dir else root
    children = transport.list(full_dir)

    if "module.pd" in children and "module.json" in children:
        if rel_dir != EMPTY_MODULE_TYPE:
            # "-empty-" is the runtime's own sentinel for an unoccupied slot
            # (decision #2), never a module a musician selects by catalog
            # key -- the song schema omits a slot to mean empty, it never
            # names "-empty-@orhack". Excluded from the catalog: 65
            # selectable built-ins, not 66 -- see docs/catalog.md "Measured
            # catalog size".
            raw = transport.read(f"{full_dir}/module.json").decode("utf-8")
            module_json = json.loads(raw)
            display = module_json["display"]
            params = parse_parameters(display, module_json.get("parameters"))
            out.append(
                CatalogEntry(
                    key=module_key(display, SOURCE),
                    source=SOURCE,
                    display=display,
                    module_type=rel_dir,
                    category=None,
                    category_override=None,
                    tags=[],
                    params=params,
                    version=VersionInfo(),
                )
            )
        return  # loadModuleDir never descends past a registered module.

    for child in children:
        child_rel = f"{rel_dir}/{child}" if rel_dir else child
        # `list()` on a plain file returns [] just like an empty directory, so
        # recursing into a stray file (none exist in the pinned tree) is a
        # harmless no-op rather than an error.
        _walk(transport, root, child_rel, out)


def ingest_builtins(transport: Transport, root: str = MODULES_ROOT) -> list[CatalogEntry]:
    """Every selectable built-in module -- 65, `-empty-` excluded (see `_walk`)."""
    out: list[CatalogEntry] = []
    _walk(transport, root, "", out)
    return out


def _load_fixture_card_transport(root: Path = FIXTURE_CARD_ROOT) -> InMemoryTransport:
    """Load the pinned fixture card tree into an in-memory transport.

    Built-ins are not re-discovered from a live mounted card -- ORHACK's
    version is pinned, so its module tree is fixed data. `.gitkeep` markers
    (used to represent otherwise-empty directories in git) become `mkdir`
    calls rather than files.
    """
    transport = InMemoryTransport()
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if path.name == ".gitkeep":
            transport.mkdir(str(Path(rel).parent.as_posix()))
            continue
        transport.write(rel, path.read_bytes())
    return transport


def ingest_pinned_builtins() -> list[CatalogEntry]:
    """Built-ins from the pinned fixture card -- the source `rig catalog update` uses."""
    return ingest_builtins(_load_fixture_card_transport())
