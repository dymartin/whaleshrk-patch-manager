"""The ordered per-candidate gate -- docs/catalog.md "Reject ordering".

Every hard-reject condition gets its own synthetic-zip test, plus the two
ordering scenarios that only real fixture measurement revealed: a wrong-arch
external beats the main.pd-redistribution check (162128, 171653), and having
no module directory at all beats it too (96836, 105123, 114274, 189681).
"""

from __future__ import annotations

from rig.catalog.archive import ZipCandidateArchive
from rig.catalog.gate import GateAccept, GateReject, RejectReason, gate_candidate

from tests.catalog_helpers import MODULE_JSON, MODULE_PD, build_zip, elf32_header

_X86_ELF = elf32_header(e_machine=0x03, e_flags=0)


def _gate(files: dict[str, bytes]) -> GateAccept | GateReject:
    return gate_candidate(ZipCandidateArchive(build_zip(files)))


def test_valid_single_module_passes():
    result = _gate({"mymod/module.json": MODULE_JSON, "mymod/module.pd": MODULE_PD})
    assert isinstance(result, GateAccept)
    assert [d.path for d in result.module_dirs] == ["mymod"]


def test_not_a_module_when_no_dir_has_both_files():
    result = _gate({"somepatch/main.pd": b"#N canvas 0 0 1 1 10;\n"})
    assert isinstance(result, GateReject)
    assert result.reason == RejectReason.NOT_A_MODULE


def test_bad_json_is_rejected():
    result = _gate(
        {"mymod/module.json": b'{display: "no quotes"}', "mymod/module.pd": MODULE_PD}
    )
    assert isinstance(result, GateReject)
    assert result.reason == RejectReason.BAD_JSON


def test_wrong_arch_external_is_rejected():
    result = _gate(
        {
            "mymod/module.json": MODULE_JSON,
            "mymod/module.pd": MODULE_PD,
            "mymod/bad~.pd_linux": _X86_ELF,
        }
    )
    assert isinstance(result, GateReject)
    assert result.reason == RejectReason.WRONG_ARCH


def test_good_arm_external_passes():
    result = _gate(
        {
            "mymod/module.json": MODULE_JSON,
            "mymod/module.pd": MODULE_PD,
            "mymod/good~.pd_linux": elf32_header(),
        }
    )
    assert isinstance(result, GateAccept)


def test_main_pd_at_package_root_is_rack_redistribution():
    result = _gate(
        {
            "pack/main.pd": b"#N canvas 0 0 1 1 10;\n",
            "pack/modules/fx/delay/module.json": MODULE_JSON,
            "pack/modules/fx/delay/module.pd": MODULE_PD,
        }
    )
    assert isinstance(result, GateReject)
    assert result.reason == RejectReason.RACK_REDISTRIBUTION


def test_main_pd_inside_a_module_directory_only_warns():
    # A main.pd nested inside the module's own directory (or a subdirectory
    # of it) is that module's own business, not a rack entry point.
    result = _gate(
        {
            "mymod/module.json": MODULE_JSON,
            "mymod/module.pd": MODULE_PD,
            "mymod/demo/main.pd": b"#N canvas 0 0 1 1 10;\n",
        }
    )
    assert isinstance(result, GateAccept)


def test_main_pd_directly_in_the_module_directory_only_warns():
    result = _gate(
        {
            "mymod/module.json": MODULE_JSON,
            "mymod/module.pd": MODULE_PD,
            "mymod/main.pd": b"#N canvas 0 0 1 1 10;\n",
        }
    )
    assert isinstance(result, GateAccept)


def test_archive_unsafe_is_rejected_before_anything_else():
    result = _gate(
        {
            "../escape/module.json": MODULE_JSON,
            "../escape/module.pd": MODULE_PD,
        }
    )
    assert isinstance(result, GateReject)
    assert result.reason == RejectReason.ARCHIVE_UNSAFE


# --- ordering: which check wins when multiple conditions are present -----


def test_wrong_arch_wins_over_rack_redistribution():
    # Reproduces the real 162128 (ORHACK itself) / 171653 (8rac) shape: a
    # root main.pd plus a wrong-arch external. Measured: both land in the
    # wrong-arch bucket, not the redistribution bucket, so wrong-arch must
    # be checked first.
    result = _gate(
        {
            "pack/main.pd": b"#N canvas 0 0 1 1 10;\n",
            "pack/modules/fx/comp/module.json": MODULE_JSON,
            "pack/modules/fx/comp/module.pd": MODULE_PD,
            "pack/modules/fx/comp/bad~.pd_linux": _X86_ELF,
        }
    )
    assert isinstance(result, GateReject)
    assert result.reason == RejectReason.WRONG_ARCH


def test_not_a_module_wins_over_rack_redistribution():
    # Reproduces the real 96836/105123/114274/189681 shape: a root main.pd
    # with no module.json/module.pd pair anywhere. Measured: these land in
    # the not-a-module bucket, so that check must be checked first.
    result = _gate({"patch/main.pd": b"#N canvas 0 0 1 1 10;\n"})
    assert isinstance(result, GateReject)
    assert result.reason == RejectReason.NOT_A_MODULE


def test_nested_module_json_is_invisible_to_the_gate():
    # Mirrors effects/delay/spiraldelay/module/module.json: a module.json
    # nested inside another module's own directory is never registered --
    # loadModuleDir never descends past the outer module.pd.
    result = _gate(
        {
            "outer/module.json": MODULE_JSON,
            "outer/module.pd": MODULE_PD,
            "outer/module/module.json": MODULE_JSON,
            "outer/module/module.pd": MODULE_PD,
        }
    )
    assert isinstance(result, GateAccept)
    assert [d.path for d in result.module_dirs] == ["outer"]
