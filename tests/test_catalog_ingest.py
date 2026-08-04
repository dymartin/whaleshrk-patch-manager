"""Full catalog build against the frozen fixture -- docs/catalog.md
"Measured catalog size": 200 entries (65 built-ins + 120 single-module
uploads + 15 from two module packs), zero qualified key collisions, no
built-in runtime path collision.
"""

from __future__ import annotations

from collections import Counter

from rig.catalog.builtins import ingest_pinned_builtins
from rig.catalog.frozen import load_frozen_sources
from rig.catalog.gate import RejectReason
from rig.catalog.ingest import build_catalog


def _build():
    return build_catalog(ingest_pinned_builtins(), load_frozen_sources())


def test_total_catalog_entries_is_200():
    result = _build()
    assert len(result.entries) == 200


def test_built_in_and_community_split():
    result = _build()
    builtin = [e for e in result.entries if e.source == "orhack"]
    community = [e for e in result.entries if e.source != "orhack"]
    assert len(builtin) == 65
    assert len(community) == 135


def test_two_packs_contribute_120_single_plus_15():
    result = _build()
    community = [e for e in result.entries if e.source != "orhack"]
    by_source = Counter(e.source for e in community)
    assert by_source["sequencers-bpm"] == 7
    assert by_source["orac-cvtools"] == 8
    single_module_sources = [src for src, n in by_source.items() if n == 1]
    assert len(single_module_sources) == 120


def test_zero_qualified_key_collisions():
    result = _build()
    keys = [e.key for e in result.entries]
    assert len(keys) == len(set(keys))


def test_no_community_module_shadows_a_built_in_runtime_path():
    result = _build()
    builtin_paths = {e.module_type for e in result.entries if e.source == "orhack"}
    community_paths = {e.module_type for e in result.entries if e.source != "orhack"}
    assert builtin_paths & community_paths == set()


def test_module_level_checks_reject_nothing_beyond_the_candidate_level_gate():
    # The gate's five candidate-level buckets (14+5+3+1 rejected, 122 pass)
    # are covered by test_catalog_frozen_gate.py. This confirms the two
    # module-level checks -- unmodelled sidecars and duplicate moduleType
    # paths -- contribute zero *additional* rejects on real data, which is
    # what makes 122 passing candidates equal exactly 200 catalog entries.
    result = _build()
    reject_reasons = Counter(r.reason for r in result.rejects)
    assert reject_reasons[RejectReason.UNMODELLED_SIDECAR] == 0
    assert reject_reasons[RejectReason.DUPLICATE_MODULE_PATH] == 0
    candidate_level_total = (
        reject_reasons[RejectReason.NOT_A_MODULE]
        + reject_reasons[RejectReason.WRONG_ARCH]
        + reject_reasons[RejectReason.RACK_REDISTRIBUTION]
        + reject_reasons[RejectReason.BAD_JSON]
    )
    assert candidate_level_total == 23
    assert len(result.rejects) == 23
