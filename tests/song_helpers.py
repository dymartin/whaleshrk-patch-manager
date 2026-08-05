"""Synthetic catalog fixtures for song parsing/validation tests.

Built directly as `CatalogEntry`/`ParamSpec` objects, not read from
`.rig/catalog/` -- these tests validate `rig.song`, not the real ingested
catalog, so they own a minimal, stable set of modules and params rather than
depending on Task 1's live data changing under them. Mirrors how
`tests/catalog_helpers.py` builds synthetic fixtures for the same reason.
"""

from __future__ import annotations

from rig.catalog.entry import CatalogEntry, VersionInfo
from rig.catalog.params import ParamSpec


def make_entry(key: str, source: str, display: str, params: list[ParamSpec]) -> CatalogEntry:
    return CatalogEntry(
        key=key,
        source=source,
        display=display,
        module_type=f"test/{display.lower()}",
        category=None,
        category_override=None,
        tags=[],
        params=params,
        version=VersionInfo(),
    )


def param(name: str, type_: str = "pct", min_: float = 0, max_: float = 100, default: float = 0) -> ParamSpec:
    return ParamSpec(name=name, id=f"id_{name}", label=name, type=type_, min=min_, max=max_, default=default)


def vellichor_catalog() -> list[CatalogEntry]:
    """Every module/param referenced by tests/fixtures/songs/vellichor.yaml."""
    return [
        make_entry("rings@orhack", "orhack", "Rings", [param("structure")]),
        make_entry("warp@orhack", "orhack", "Warp", [param("drive")]),
        make_entry("plateverb@orhack", "orhack", "Plateverb", [param("size")]),
        make_entry("clouds@orhack", "orhack", "Clouds", []),
        make_entry("marginal@orhack", "orhack", "Marginal", [param("low", min_=0, max_=100)]),
        make_entry("bus-comp@orhack", "orhack", "Bus Comp", []),
        make_entry("lfo@orhack", "orhack", "LFO", [param("speed-1")]),
        make_entry("spiraldelay@orhack", "orhack", "Spiraldelay", []),
        make_entry("eq-iv@orhack", "orhack", "EQ IV", []),
        make_entry("samplement@orhack", "orhack", "Samplement", []),
    ]
