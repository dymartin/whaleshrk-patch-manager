"""`rig.compile.sidecars` -- default `.txt` state for occupied stateful slots.

Content is asserted byte-for-byte against the pinned `Init` preset itself
(not re-derived), so these tests catch a wrong path or off-by-one in the
retargeting logic, not just a wrong file count.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from rig.catalog.entry import CatalogEntry, VersionInfo
from rig.compile.sidecars import UnverifiedStatefulModuleError, sidecar_files_for_slot

INIT_DIR = (
    Path(__file__).resolve().parent.parent
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


def test_overdrum_emits_loop_metric_and_step_seq_note_vel_but_not_length():
    files = sidecar_files_for_slot(_entry("sequencers/overdrum"), "b2")
    assert len(files) == 154  # docs/platform/state.md: 154 for a slot without step-seq-length
    assert "loop-b2-a.txt" in files
    assert "metric-b2-g.txt" in files
    assert "step-seq-note-b2-c-p10.txt" in files
    assert "step-seq-vel-b2-c-p1.txt" in files
    assert not any(name.startswith("step-seq-length") for name in files)
    assert "loop-a1-a.txt" not in files  # retargeted, not left at the template slot


def test_overflow_emits_the_full_224_file_set_including_step_seq_length():
    files = sidecar_files_for_slot(_entry("sequencers/overflow"), "d4")
    assert len(files) == 224  # docs/platform/state.md: 224 for a1/b1/c1
    assert "step-seq-length-d4-a-p1.txt" in files
    assert "step-seq-length-d4-g-p10.txt" in files


def test_retargeted_content_matches_the_pinned_init_template_bytes():
    files = sidecar_files_for_slot(_entry("sequencers/overdrum"), "c3")
    assert files["loop-c3-a.txt"] == (INIT_DIR / "loop-a1-a.txt").read_bytes()
    assert files["step-seq-note-c3-b-p5.txt"] == (INIT_DIR / "step-seq-note-a1-b-p5.txt").read_bytes()


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


@pytest.mark.parametrize("module_type", ["sequencers/clips", "sequencers/polystep"])
def test_unverified_stateful_builtins_raise_rather_than_guess(module_type):
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
