"""CI's other required check, alongside `rig validate --tier static`:
"CI also regenerates the catalog from the frozen fixture and fails on diff.
Never hits the live API." (Prompt/09-static-validation.md "CI").

`.rig/catalog/` and `.rig/modules.lock` are committed, generated files
(docs/catalog.md) -- `rig catalog update` is the only path that regenerates
them, and it reaches live Patchstorage. This reproduces the same build
offline, from the frozen fixture `tests/test_catalog_ingest.py` already
proves matches the measured counts, and fails if the committed files were
hand-edited or left stale after a source change.
"""

from __future__ import annotations

from pathlib import Path

from rig.catalog.builtins import ingest_pinned_builtins
from rig.catalog.frozen import load_frozen_sources
from rig.catalog.ingest import build_catalog
from rig.catalog.io import read_lock, write_catalog, write_lock

REPO_ROOT = Path(__file__).resolve().parent.parent
CATALOG_DIR = REPO_ROOT / ".rig" / "catalog"
LOCK_PATH = REPO_ROOT / ".rig" / "modules.lock"


def _fresh_build():
    return build_catalog(ingest_pinned_builtins(), load_frozen_sources())


def test_committed_catalog_entries_match_a_fresh_frozen_build(tmp_path):
    result = _fresh_build()
    fresh_dir = tmp_path / "catalog"
    write_catalog(result.entries, fresh_dir)

    committed = {p.name: p.read_bytes() for p in CATALOG_DIR.glob("*.json")}
    fresh = {p.name: p.read_bytes() for p in fresh_dir.glob("*.json")}
    assert fresh == committed


def test_committed_lock_matches_a_fresh_frozen_build(tmp_path):
    result = _fresh_build()
    fresh_lock = tmp_path / "modules.lock"
    write_lock(result.entries, fresh_lock)

    assert read_lock(fresh_lock) == read_lock(LOCK_PATH)
