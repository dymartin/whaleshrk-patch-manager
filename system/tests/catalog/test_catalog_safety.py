"""Archive-safety checks -- docs/catalog.md "Reject ordering".

The real 145-candidate fixture has no adversarial archive (controller note
2), so every scenario here is a synthetic `ArchiveEntry` list built offline.
"""

from __future__ import annotations

from rig.catalog.safety import (
    MAX_ENTRIES,
    MAX_TOTAL_UNCOMPRESSED_SIZE,
    ArchiveEntry,
    check_archive_safety,
)

_S_IFLNK = 0o120000


def _entry(name, size=10, is_dir=False, external_attr=0) -> ArchiveEntry:
    return ArchiveEntry(name=name, size=size, compress_size=size, external_attr=external_attr, is_dir=is_dir)


def test_safe_archive_has_no_problems():
    entries = [
        _entry("mymodule/"),
        _entry("mymodule/module.json", size=200),
        _entry("mymodule/module.pd", size=500),
    ]
    assert check_archive_safety(entries) == []


def test_traversal_is_rejected():
    entries = [_entry("../../etc/passwd")]
    problems = check_archive_safety(entries)
    assert any("traversal" in p for p in problems)


def test_traversal_mid_path_is_rejected():
    entries = [_entry("mymodule/../../../etc/passwd")]
    problems = check_archive_safety(entries)
    assert any("traversal" in p for p in problems)


def test_absolute_path_is_rejected():
    entries = [_entry("/etc/passwd")]
    problems = check_archive_safety(entries)
    assert any("absolute" in p for p in problems)


def test_symlink_entry_is_rejected():
    external_attr = (_S_IFLNK | 0o777) << 16
    entries = [_entry("mymodule/evil-link", external_attr=external_attr)]
    problems = check_archive_safety(entries)
    assert any("symlink" in p for p in problems)


def test_case_colliding_entries_are_rejected():
    entries = [_entry("mymodule/Module.json"), _entry("mymodule/module.json")]
    problems = check_archive_safety(entries)
    assert any("case-colliding" in p for p in problems)


def test_identical_names_are_not_a_case_collision():
    entries = [_entry("mymodule/module.json"), _entry("mymodule/module.json")]
    problems = check_archive_safety(entries)
    assert not any("case-colliding" in p for p in problems)


def test_file_count_over_limit_is_rejected():
    entries = [_entry(f"mymodule/file{i}.txt") for i in range(MAX_ENTRIES + 1)]
    problems = check_archive_safety(entries)
    assert any("file count" in p for p in problems)


def test_expanded_size_over_limit_is_rejected():
    entries = [_entry("mymodule/huge.bin", size=MAX_TOTAL_UNCOMPRESSED_SIZE + 1)]
    problems = check_archive_safety(entries)
    assert any("expanded size" in p for p in problems)


def test_multiple_problems_are_all_reported():
    entries = [
        _entry("../escape"),
        _entry("/absolute"),
    ]
    problems = check_archive_safety(entries)
    assert len(problems) >= 2
