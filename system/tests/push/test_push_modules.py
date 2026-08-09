"""ORHACK manifest verification and community module reconciliation.

See rig/push/modules.py and docs/workflows/push.md "Reconcile modules".
"""

from __future__ import annotations

import pytest

from rig.catalog.entry import CatalogEntry, VersionInfo
from rig.push.modules import (
    ModuleInstall,
    ModuleSourceUnavailable,
    OrhackIntegrityError,
    installed_content_hash,
    module_install_dir,
    plan_module_reconciliation,
    verify_orhack_manifest,
    verify_orhack_structure,
)
from rig.transport.memory import InMemoryTransport
from tests.fixture_card import load_fixture_card


def _loaded_card() -> InMemoryTransport:
    transport = InMemoryTransport()
    load_fixture_card(transport)
    return transport


def _community_entry(key: str = "warble@warble", module_type: str = "effects/mod/warble@warble") -> CatalogEntry:
    return CatalogEntry(
        key=key,
        source="warble",
        display="Warble",
        module_type=module_type,
        category="effects/mod",
        category_override=None,
        tags=[],
        params=[],
        version=VersionInfo(updated_at="2024-01-01", file_id=1, archive_sha256="deadbeef"),
    )


class _FakeSource:
    def __init__(self, files: dict[str, bytes] | None = None, unavailable: bool = False):
        self._files = files
        self._unavailable = unavailable

    def fetch(self, entry):
        if self._unavailable:
            raise ModuleSourceUnavailable(f"cannot reach source for {entry.key}")
        return dict(self._files)


def test_verify_orhack_structure_passes_on_the_fixture_card():
    verify_orhack_structure(_loaded_card())


def test_verify_orhack_structure_refuses_when_manifest_is_missing():
    transport = InMemoryTransport()
    with pytest.raises(OrhackIntegrityError) as exc:
        verify_orhack_structure(transport)
    assert exc.value.code == "ORHACK_NOT_INSTALLED"


def test_verify_orhack_manifest_passes_on_the_untouched_fixture_card():
    verify_orhack_manifest(_loaded_card())


def test_verify_orhack_manifest_detects_a_modified_file():
    transport = _loaded_card()
    transport.write("Patches/0RHACK/mother.pd", b"tampered")
    with pytest.raises(OrhackIntegrityError) as exc:
        verify_orhack_manifest(transport)
    assert exc.value.code == "ORHACK_INTEGRITY_FAILED"
    assert "mother.pd" in str(exc.value)


def test_verify_orhack_manifest_detects_a_missing_file():
    transport = _loaded_card()
    transport.delete("Patches/0RHACK/mother.pd")
    with pytest.raises(OrhackIntegrityError) as exc:
        verify_orhack_manifest(transport)
    assert exc.value.code == "ORHACK_INTEGRITY_FAILED"
    assert "missing" in str(exc.value)


def test_verify_orhack_manifest_uses_transport_bulk_check():
    transport = _loaded_card()
    transport.check_sha1_manifest = lambda manifest: None
    verify_orhack_manifest(transport)


def test_verify_orhack_manifest_reports_bulk_check_failure():
    transport = _loaded_card()
    transport.check_sha1_manifest = lambda manifest: "0RHACK/mother.pd: FAILED"
    with pytest.raises(OrhackIntegrityError, match="mother.pd"):
        verify_orhack_manifest(transport)


def test_installed_content_hash_is_none_when_nothing_installed():
    transport = InMemoryTransport()
    entry = _community_entry()
    assert installed_content_hash(transport, entry) is None


def test_installed_content_hash_matches_regardless_of_write_order():
    entry = _community_entry()
    root = module_install_dir(entry)
    t1 = InMemoryTransport()
    t1.write(f"{root}/module.json", b"{}")
    t1.write(f"{root}/module.pd", b"patch")
    t2 = InMemoryTransport()
    t2.write(f"{root}/module.pd", b"patch")
    t2.write(f"{root}/module.json", b"{}")
    assert installed_content_hash(t1, entry) == installed_content_hash(t2, entry)


def test_reconcile_plans_install_for_a_missing_module():
    transport = InMemoryTransport()
    entry = _community_entry()
    files = {"module.json": b"{}", "module.pd": b"patch"}
    plan = plan_module_reconciliation(transport, [entry], _FakeSource(files))
    assert plan.to_install == [ModuleInstall(entry=entry, files=files)]
    assert plan.to_replace == []
    assert plan.unavailable == []


def test_reconcile_plans_replace_when_installed_hash_differs_from_fetched():
    transport = InMemoryTransport()
    entry = _community_entry()
    root = module_install_dir(entry)
    transport.write(f"{root}/module.json", b"{OLD}")
    files = {"module.json": b"{NEW}"}
    plan = plan_module_reconciliation(transport, [entry], _FakeSource(files))
    assert len(plan.to_replace) == 1
    assert plan.to_replace[0].entry is entry
    assert plan.to_install == []


def test_reconcile_reports_up_to_date_when_hashes_match():
    transport = InMemoryTransport()
    entry = _community_entry()
    root = module_install_dir(entry)
    files = {"module.json": b"{}"}
    transport.write(f"{root}/module.json", b"{}")
    plan = plan_module_reconciliation(transport, [entry], _FakeSource(files))
    assert plan.up_to_date == [entry]
    assert plan.to_install == []
    assert plan.to_replace == []


def test_unreadable_archive_and_missing_module_is_a_hard_error_condition():
    # The preset would reference a moduleType that never resolves.
    transport = InMemoryTransport()
    entry = _community_entry()
    plan = plan_module_reconciliation(transport, [entry], _FakeSource(unavailable=True))
    assert plan.unavailable == [entry]
    assert plan.to_install == []


def test_unreadable_archive_still_refuses_when_the_module_is_already_installed():
    # Unlike a network fetch, this is never transient: the repo pins a module
    # whose archive it does not carry, so what sits on the card cannot be
    # verified against anything.
    transport = InMemoryTransport()
    entry = _community_entry()
    root = module_install_dir(entry)
    transport.write(f"{root}/module.json", b"{}")
    plan = plan_module_reconciliation(transport, [entry], _FakeSource(unavailable=True))
    assert plan.unavailable == [entry]
    assert plan.up_to_date == []
