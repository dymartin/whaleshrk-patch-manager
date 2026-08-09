"""Transport protocol shared by every backend that moves files to or from the card.

Card-relative paths only: "data/orhack/rack.json", never an absolute mount
path. Sync, mirroring, diff and compile logic lives above this layer -- see
docs/transport.md.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


class TransportPathError(ValueError):
    """A path escaped the transport's root or was otherwise malformed."""


def normalize_path(path: str) -> str:
    """Validate and normalize a card-relative path.

    Rejects absolute paths and any ".." segment -- both are ways a caller could
    escape the transport root, and refusing beats guessing (see
    docs/transport.md "Card identification").
    """
    if not path:
        raise TransportPathError("path must not be empty")
    if path.startswith("/") or path.startswith("\\"):
        raise TransportPathError(f"path must be card-relative, got {path!r}")
    parts = [p for p in path.replace("\\", "/").split("/") if p not in ("", ".")]
    if ".." in parts:
        raise TransportPathError(f"path escapes transport root: {path!r}")
    return "/".join(parts)


@runtime_checkable
class Transport(Protocol):
    """Narrow file protocol. Nothing above card-relative read/write/list."""

    def exists(self, path: str) -> bool: ...

    def list(self, path: str) -> list[str]:
        """Immediate children (files and directories) of path, sorted.

        A missing directory yields an empty list, never an error -- sync logic
        above this layer treats "not there yet" and "empty" the same way.
        """
        ...

    def read(self, path: str) -> bytes: ...

    def write(self, path: str, data: bytes) -> None: ...

    def delete(self, path: str) -> None:
        """Remove a file or a directory and everything under it."""
        ...

    def mkdir(self, path: str) -> None:
        """Create a directory, including any missing parents. Idempotent."""
        ...

    def rename(self, source: str, target: str) -> None:
        """Move source to target, overwriting target if it exists."""
        ...

    def flush(self) -> None:
        """Block until buffered writes reach the storage device.

        `mount.sh` mounts the card with -o async,noatime, so a push is not
        durable until flush returns -- see docs/platform/card.md.
        """
        ...
