"""Archive-safety checks on a zip's raw entry listing.

Operates on the entry metadata alone (name, size, external_attr) -- it never
needs to extract anything, so it runs against untrusted archive structure
before any path from the archive is trusted as a directory or a filename.
See docs/catalog.md "Reject ordering".

The real 145-candidate fixture has no adversarial archive (see
Prompt/01-catalog.md, controller note 2) -- these limits and detections are
exercised by synthetic zip fixtures built in tests/test_catalog_safety.py.
"""

from __future__ import annotations

from dataclasses import dataclass

# Policy limits, not measured facts: the real fixture's largest candidate
# (ORHACK's own archive, id 162128) has 2,477 entries and ~111 MB
# uncompressed. Limits sit comfortably above every real candidate while still
# catching a zip bomb (extreme compression ratio, or a huge file/entry count).
MAX_ENTRIES = 10_000
MAX_TOTAL_UNCOMPRESSED_SIZE = 500_000_000  # bytes

_S_IFLNK = 0o120000
_S_IFMT = 0o170000


@dataclass(frozen=True)
class ArchiveEntry:
    name: str
    size: int
    compress_size: int
    external_attr: int
    is_dir: bool

    @property
    def is_symlink(self) -> bool:
        unix_mode = self.external_attr >> 16
        return (unix_mode & _S_IFMT) == _S_IFLNK


def _is_traversal(name: str) -> bool:
    parts = name.replace("\\", "/").split("/")
    return ".." in parts


def _is_absolute(name: str) -> bool:
    normalized = name.replace("\\", "/")
    if normalized.startswith("/"):
        return True
    # Windows drive-letter or UNC absolute paths, in case a zip was built there.
    if len(normalized) > 1 and normalized[1] == ":":
        return True
    return False


def check_archive_safety(entries: list[ArchiveEntry]) -> list[str]:
    """Return a list of distinct problem messages; empty means the archive is safe.

    Every problem class is reported (not just the first found) -- Constraint
    3 requires a distinct message per condition, not a truncated report.
    """
    problems: list[str] = []

    for entry in entries:
        if _is_traversal(entry.name):
            problems.append(f"archive traversal: {entry.name!r}")
        if _is_absolute(entry.name):
            problems.append(f"absolute path in archive: {entry.name!r}")
        if entry.is_symlink:
            problems.append(f"symlink entry in archive: {entry.name!r}")

    lowered: dict[str, list[str]] = {}
    for entry in entries:
        lowered.setdefault(entry.name.lower(), []).append(entry.name)
    for lower_name, names in lowered.items():
        if len(set(names)) > 1:
            problems.append(f"case-colliding entries: {sorted(set(names))!r}")

    if len(entries) > MAX_ENTRIES:
        problems.append(f"archive file count {len(entries)} exceeds limit {MAX_ENTRIES}")

    total_size = sum(e.size for e in entries if not e.is_dir)
    if total_size > MAX_TOTAL_UNCOMPRESSED_SIZE:
        problems.append(
            f"archive expanded size {total_size} exceeds limit {MAX_TOTAL_UNCOMPRESSED_SIZE}"
        )

    return problems
