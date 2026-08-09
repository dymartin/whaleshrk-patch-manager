"""`rig.compile.sidecars` -- default `.txt` state for occupied stateful slots.

Morpher content is asserted byte-for-byte against the pinned `Init` preset
itself (not re-derived). The four sequencer module types all raise --
`sequencers/overdrum`/`overflow` because a verified template covers only
part of what they read on load, `sequencers/clips`/`polystep` because none
of what they read has a verified template at all -- see
`rig.compile.sidecars`'s module docstring for the source citations.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from rig.catalog.entry import CatalogEntry, VersionInfo
from rig.compile.sidecars import UnverifiedStatefulModuleError, sidecar_files_for_slot

INIT_DIR = (
    Path(__file__).resolve().parents[2]
    / "fixtures"
    / "card"
    / "Patches"
    / "0RHACK"
    / "data"
    / "presets"
    / "Init"
)


def _entry(module_type: str, sidecar_templates: list[str] | None = None) -> CatalogEntry:
    return CatalogEntry(
        key=f"test@{module_type}",
        source="orhack",
        display="Test",
        module_type=module_type,
        category=None,
        category_override=None,
        tags=[],
        params=[],
        version=VersionInfo(),
        sidecar_templates=sidecar_templates or [],
    )


def test_morpher_emits_16_global_banks_regardless_of_target_slot():
    files_m1 = sidecar_files_for_slot(_entry("mod-sources/morpher"), "m1")
    files_m3 = sidecar_files_for_slot(_entry("mod-sources/morpher"), "m3")
    assert len(files_m1) == 16
    assert set(files_m1) == {f"p{n}.txt" for n in range(1, 17)}
    # Global -- identical regardless of which m-slot the morpher occupies.
    assert files_m1 == files_m3


def test_morpher_content_matches_the_pinned_init_template_bytes():
    files = sidecar_files_for_slot(_entry("mod-sources/morpher"), "m2")
    assert files["p1.txt"] == (INIT_DIR / "p1.txt").read_bytes()
    assert files["p16.txt"] == (INIT_DIR / "p16.txt").read_bytes()


@pytest.mark.parametrize(
    "module_type",
    ["sequencers/overdrum", "sequencers/overflow", "sequencers/clips", "sequencers/polystep"],
)
def test_unverified_stateful_builtins_raise_rather_than_guess(module_type):
    # overdrum/overflow raise alongside clips/polystep even though Init ships
    # verified default content for *some* of what they read (loop-*,
    # metric-*, step-seq-{note,vel,length}-*): both also read
    # <slot>-slot-tracker.txt and <slot>-seq<n>x.txt unconditionally on load
    # (seq3.pd's save-the-txts subpatch -- the read-bang inlet at line 595
    # drives the seq<n>x read at line 597/602; `r loadbang-\$1` at line 639
    # drives the slot-tracker read at line 604), and neither file family has
    # a verified default anywhere in Init or jam. Emitting only the verified
    # families would be a silently incomplete set -- see the module
    # docstring and decision #69.
    with pytest.raises(UnverifiedStatefulModuleError):
        sidecar_files_for_slot(_entry(module_type), "a1")


def test_community_module_flagged_stateful_by_ingest_also_raises():
    entry = _entry("effects/delay/some-community-module", sidecar_templates=[r"\$1/presets/\$2/\$3-data.txt"])
    with pytest.raises(UnverifiedStatefulModuleError):
        sidecar_files_for_slot(entry, "a1")


def test_ordinary_stateless_module_emits_nothing():
    assert sidecar_files_for_slot(_entry("effects/reverb/plateverb"), "p1") == {}


def test_empty_module_type_emits_nothing():
    assert sidecar_files_for_slot(_entry("-empty-"), "a1") == {}
