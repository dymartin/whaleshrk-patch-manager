"""Crash-safe writes to the repo working tree.

`.rig/` holds the state push and pull reason from: the last-pushed baseline
pull diffs against, the recorded lock hash, chain letter bindings. A plain
`write_text` truncates the old file before the new content lands, so an
interrupted run can leave a half-written baseline that the next pull reads as
truth. Writing to a temp file in the same directory and then renaming makes
the swap atomic: a reader sees either the old content or the new one.

Same-directory temp file matters -- `os.replace` is only atomic within one
filesystem, and the repo may sit on a different volume from the system temp
directory.

Not used for card writes: `rig.transport` goes through push's journal and
backup transaction (`rig.push.transact`), which provides recovery at a level
this cannot.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Callable


def _replace_via_temp(path: Path, write: Callable[[int], None]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        write(fd)
        os.replace(tmp_name, path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise


def write_bytes_atomic(path: Path, data: bytes) -> None:
    def _write(fd: int) -> None:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())

    _replace_via_temp(path, _write)


def write_text_atomic(path: Path, text: str, *, encoding: str = "utf-8") -> None:
    """Text mode with default newline translation, exactly like
    `Path.write_text(encoding=...)`. Writing the encoded bytes directly instead
    would drop that translation and silently rewrite the line endings of every
    committed generated file on Windows."""

    def _write(fd: int) -> None:
        with os.fdopen(fd, "w", encoding=encoding) as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())

    _replace_via_temp(path, _write)
