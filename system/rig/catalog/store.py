"""`modules/` -- the committed archive store.

One file per community module upload, byte-identical to what Patchstorage
served. This is what makes the repo's reproducibility promise true: pinning
an upload id in `.rig/modules.lock` proves nothing once the author deletes or
replaces that upload, so the bytes themselves travel with the repo
(docs/catalog.md "The archive store", docs/repo-layout.md).

Top-level rather than under `.rig/`: these are vendored inputs the repo owns,
not state the CLI generates.

The filename carries the author-declared `revision` because it is the only
human-readable version an upload has. It is *not* an identity -- revisions
collide across uploads and authors re-upload without bumping them -- so
identity stays `archive_sha256` in the lock, and `write_archive` refuses a
same-revision archive whose bytes differ rather than silently overwriting.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from rig.atomicio import write_bytes_atomic
from rig.errors import CodedError

# An archive this big is worth a second look before it enters git history
# forever: the median ORAC module is ~40KB, so anything past this is an
# outlier (a module shipping a large compiled binary) whose every future
# upgrade permanently adds another copy to the repo.
ARCHIVE_SIZE_WARN_BYTES = 5 * 1024 * 1024

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]")


class ArchiveStoreError(CodedError):
    pass


def archive_filename(source: str, revision: str) -> str:
    """`<upload slug>@v<revision>.zip`, with anything filesystem-unsafe in
    either part replaced -- `revision` is author free text and cannot be
    trusted to be a bare version number."""
    return f"{_UNSAFE.sub('-', source)}@v{_UNSAFE.sub('-', revision or 'unknown')}.zip"


def archive_path(modules_dir: Path, source: str, revision: str) -> Path:
    return modules_dir / archive_filename(source, revision)


def write_archive(modules_dir: Path, source: str, revision: str, data: bytes) -> Path:
    """Store one upload's archive, refusing to overwrite different bytes.

    Same revision, different bytes means the author replaced the upload
    without bumping their version -- the silent-change case that no diff
    would otherwise surface. Surfaced as a refusal, not resolved by an
    id-suffixed filename that would hide it.
    """
    path = archive_path(modules_dir, source, revision)
    if path.exists() and path.read_bytes() != data:
        raise ArchiveStoreError(
            "ARCHIVE_REVISION_COLLISION",
            f"{path.name} already exists with different content: upstream replaced revision "
            f"{revision!r} of {source!r} without bumping it. Delete the stored archive to accept "
            "the replacement, after checking what changed.",
        )
    modules_dir.mkdir(parents=True, exist_ok=True)
    write_bytes_atomic(path, data)
    return path


def read_archive(modules_dir: Path, source: str, revision: str, expected_sha256: str) -> bytes:
    """The stored archive's bytes, verified against the lock's digest.

    Verified on every read, not just at `add` time: a truncated clone or a
    hand-edited archive must be caught before its contents reach the card.
    """
    path = archive_path(modules_dir, source, revision)
    if not path.exists():
        raise ArchiveStoreError(
            "ARCHIVE_MISSING",
            f"{path} is missing -- the repo does not carry the module it pins. "
            f"Run `rig catalog add {source}` to restore it.",
        )
    data = path.read_bytes()
    actual = hashlib.sha256(data).hexdigest()
    if expected_sha256 and actual != expected_sha256:
        raise ArchiveStoreError(
            "ARCHIVE_DIGEST_MISMATCH",
            f"{path} does not match the digest pinned in system/data/modules.lock "
            f"(expected {expected_sha256[:12]}..., got {actual[:12]}...)",
        )
    return data
