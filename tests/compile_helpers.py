"""Shared fixtures for `rig.compile` tests.

`system_catalog()` pulls the real, pinned `routers/hybrid` and
`clocks/transport` entries from the built-in catalog -- the compiler's `s1`/
`s2` defaults come from live catalog data (see `rig.compile.router`), so
tests need the real parameter set, not a hand-copied subset that could drift
from it. Everything else (chain/master/send/mod-source modules) uses small,
synthetic entries, same convention as `tests/song_helpers.py`.
"""

from __future__ import annotations

from rig.catalog.builtins import ingest_pinned_builtins
from rig.catalog.entry import CatalogEntry, VersionInfo
from rig.catalog.params import ParamSpec

_SYSTEM_MODULE_TYPES = {"routers/hybrid", "clocks/transport"}
_system_entries_cache: list[CatalogEntry] | None = None


def system_catalog() -> list[CatalogEntry]:
    global _system_entries_cache
    if _system_entries_cache is None:
        _system_entries_cache = [
            e for e in ingest_pinned_builtins() if e.module_type in _SYSTEM_MODULE_TYPES
        ]
    return list(_system_entries_cache)


def make_entry(key: str, source: str, display: str, module_type: str, params: list[ParamSpec]) -> CatalogEntry:
    return CatalogEntry(
        key=key,
        source=source,
        display=display,
        module_type=module_type,
        category=None,
        category_override=None,
        tags=[],
        params=params,
        version=VersionInfo(),
    )


def param(name: str, id_: str | None = None, type_: str = "pct", min_: float = 0, max_: float = 100, default: float = 0) -> ParamSpec:
    return ParamSpec(name=name, id=id_ or f"id_{name}", label=name, type=type_, min=min_, max=max_, default=default)


def samplement_entry(key: str = "samplement@orhack") -> CatalogEntry:
    return make_entry(
        key,
        "orhack",
        "Samplement",
        "instruments/sampler/samplement",
        [
            ParamSpec(name="sample-source", id="samp_source", label="Sample source", type="int", min=-1, max=27, default=0),
            ParamSpec(name="select", id="samp_select", label="select", type="float", min=0, max=100, default=0),
        ],
    )
