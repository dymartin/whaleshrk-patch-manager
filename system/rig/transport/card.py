"""Structural identification of the ORHACK card among mounted volumes.

See docs/transport.md "Card identification": a candidate root is a card only
if it holds both `data/orhack/` and `Patches/0RHACK/`. Never picked by drive
letter or volume label -- either can be renamed by a musician and neither is
evidence of contents. Push does mirror-with-deletions, so a wrong pick is
unrecoverable; refusing on zero or multiple candidates is the only safe
default.
"""

from __future__ import annotations

import ctypes
import os
import string
from pathlib import Path
from typing import Iterable

from rig.errors import CodedError

from .usb import UsbMassStorage

CARD_MARKERS = ("data/orhack", "Patches/0RHACK")

# Card layout facts, not push's or pull's own policy: where ORHACK keeps
# presets, and the one preset it ships that no repo song may ever own or
# delete. Both push and pull already depend on this module, so they read the
# layout from here rather than one reaching into the other's internals.
PRESETS_ROOT = "data/orhack/presets"
INIT_PRESET_NAME = "Init"
PROTECTED_PRESET_NAMES = {INIT_PRESET_NAME}


class CardDetectionError(CodedError):
    """Zero or multiple candidate card roots found; refuses rather than guessing."""


def is_card_root(root: Path) -> bool:
    """True if `root` holds every structural marker of an ORHACK card."""
    return all((root / marker).is_dir() for marker in CARD_MARKERS)


def find_candidate_roots(roots: Iterable[Path]) -> list[Path]:
    """Every root in `roots` that carries all card markers."""
    return [r for r in roots if is_card_root(r)]


def resolve_card(roots: Iterable[Path] | None = None) -> UsbMassStorage:
    """Return the one card among `roots`, or refuse.

    `roots` defaults to `list_mounted_roots()`, a best-effort live scan;
    callers (tests, and an operator pointing at a non-standard mount) may
    pass an explicit list instead. Refusal is a `CardDetectionError` naming
    which case fired -- zero candidates or more than one -- never a silent
    pick.
    """
    if roots is None:
        roots = list_mounted_roots()
    roots = list(roots)
    candidates = find_candidate_roots(roots)
    if not candidates:
        raise CardDetectionError(
            "NO_CARD_FOUND",
            f"no candidate card found among {len(roots)} checked root(s); "
            f"a card must contain both {CARD_MARKERS[0]!r} and {CARD_MARKERS[1]!r}",
        )
    if len(candidates) > 1:
        listed = ", ".join(str(c) for c in candidates)
        raise CardDetectionError(
            "MULTIPLE_CARDS_FOUND",
            f"multiple candidate cards found, refusing to guess which is correct: {listed}",
        )
    return UsbMassStorage(candidates[0])


def list_mounted_roots() -> list[Path]:
    """Every plausible removable-drive mount point on this host.

    Best-effort and platform-specific -- an operator can always bypass this
    by passing an explicit `roots` list to `resolve_card`. Verified only
    against documented OS conventions, not against real hardware (no
    removable drive is attached in this development environment):
    Windows enumerates drive letters via `GetDriveTypeW`
    (`DRIVE_REMOVABLE`); POSIX hosts glob the conventional auto-mount
    parents (`/media/*`, `/run/media/*/*`, `/Volumes/*`).
    """
    if os.name == "nt":
        return _windows_removable_roots()
    return _posix_removable_roots()


def _windows_removable_roots() -> list[Path]:
    DRIVE_REMOVABLE = 2
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    bitmask = kernel32.GetLogicalDrives()
    roots = []
    for i, letter in enumerate(string.ascii_uppercase):
        if not (bitmask >> i) & 1:
            continue
        drive = f"{letter}:\\"
        if kernel32.GetDriveTypeW(drive) == DRIVE_REMOVABLE:
            roots.append(Path(drive))
    return roots


def _posix_removable_roots() -> list[Path]:
    roots: list[Path] = []
    for parent in (Path("/media"), Path("/Volumes")):
        if parent.is_dir():
            roots.extend(p for p in parent.iterdir() if p.is_dir())
    run_media = Path("/run/media")
    if run_media.is_dir():
        for user_dir in run_media.iterdir():
            if user_dir.is_dir():
                roots.extend(p for p in user_dir.iterdir() if p.is_dir())
    return roots
