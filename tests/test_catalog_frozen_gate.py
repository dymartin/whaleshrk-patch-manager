"""Replays the frozen 145-candidate fixture through the gate.

This is Task 1's central verification: Prompt/01-catalog.md "Verification"
requires the frozen fixture to reproduce 122 pass / 14 not-a-module / 5
wrong-arch / 3 rack-redistribution / 1 bad-JSON exactly, with no test ever
touching the network (tests/conftest.py blocks every socket).
"""

from __future__ import annotations

from collections import Counter

from rig.catalog.frozen import load_frozen_sources
from rig.catalog.gate import GateAccept, GateReject, RejectReason, gate_candidate


def _results():
    sources = load_frozen_sources()
    return {source.id: gate_candidate(source.archive) for source in sources}


def test_frozen_fixture_has_145_candidates():
    assert len(load_frozen_sources()) == 145


def test_gate_reproduces_the_measured_bucket_counts():
    results = _results()
    counts = Counter()
    for result in results.values():
        if isinstance(result, GateAccept):
            counts["pass"] += 1
        else:
            counts[result.reason] += 1

    assert counts["pass"] == 122
    assert counts[RejectReason.NOT_A_MODULE] == 14
    assert counts[RejectReason.WRONG_ARCH] == 5
    assert counts[RejectReason.RACK_REDISTRIBUTION] == 3
    assert counts[RejectReason.BAD_JSON] == 1
    assert sum(counts.values()) == 145


def test_the_three_rack_redistribution_ids():
    # "docs/catalog.md:96-97 -- all three measured redistributions", the
    # only candidates that ship literally orac/main.pd.
    results = _results()
    redistributed = {
        pid
        for pid, r in results.items()
        if isinstance(r, GateReject) and r.reason == RejectReason.RACK_REDISTRIBUTION
    }
    assert redistributed == {96789, 105149, 169334}


def test_the_five_wrong_arch_ids_include_orhack_itself_and_8rac():
    # The x86 tb_peakcomp~/ds_peakcomp~ pair propagates into bus-comp,
    # strip, percussions+, 8rac, and ORHACK's own archive (162128) --
    # Prompt/01-catalog.md "Done when".
    results = _results()
    wrong_arch = {
        pid
        for pid, r in results.items()
        if isinstance(r, GateReject) and r.reason == RejectReason.WRONG_ARCH
    }
    assert wrong_arch == {154884, 162128, 167630, 169558, 171653}


def test_the_bad_json_id():
    results = _results()
    bad_json = {
        pid
        for pid, r in results.items()
        if isinstance(r, GateReject) and r.reason == RejectReason.BAD_JSON
    }
    assert bad_json == {118027}


def test_8rac_and_orhack_land_in_wrong_arch_not_redistribution():
    # Both 162128 and 171653 also carry a root main.pd. Measured: wrong-arch
    # is checked first, so they land there, not in the redistribution
    # bucket -- see docs/catalog.md "Reject ordering".
    results = _results()
    assert results[162128].reason == RejectReason.WRONG_ARCH
    assert results[171653].reason == RejectReason.WRONG_ARCH


def test_plain_patches_with_root_main_pd_land_in_not_a_module():
    # These four ship a root main.pd but have no module.json/module.pd pair
    # anywhere, so not-a-module must be checked before redistribution.
    results = _results()
    for pid in (96836, 105123, 114274, 189681):
        assert results[pid].reason == RejectReason.NOT_A_MODULE


def test_modules_with_root_main_pd_in_their_own_directory_still_pass():
    # simpledist, mfbsynthlike, vj-fm each ship a main.pd directly inside
    # their own (single) module directory -- warn territory, not reject.
    results = _results()
    for pid in (125524, 125848, 163108):
        assert isinstance(results[pid], GateAccept)


def test_nested_main_pd_inside_a_module_subdirectory_still_passes():
    # monocle, apollo, macrosynth-pd, branks+ ship main.pd one level deeper
    # inside their module's own directory (an "aptone" subfolder).
    results = _results()
    for pid in (146075, 146090, 154907, 169842):
        assert isinstance(results[pid], GateAccept)
