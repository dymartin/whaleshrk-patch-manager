"""Recursive file listing over a `Transport`.

`Transport.list` returns only immediate children (docs/transport.md);
module reconciliation and transaction verification both need every file
under a directory, so both walk through this one function rather than
reimplementing the recursion.
"""

from __future__ import annotations

from rig.transport.base import Transport


def list_files_recursive(transport: Transport, root: str) -> list[str]:
    """Every file under `root`, path relative to `root`, sorted.

    A path with children is a directory and is descended into; a path with
    none is read as a file. `Transport.list` returns `[]` for both an empty
    directory and a missing one, so an empty directory silently contributes
    no files -- consistent with "not there yet" and "empty" being treated
    the same way everywhere else in the transport layer.
    """
    out: list[str] = []

    def _dispatch(rel: str, full: str) -> None:
        children = transport.list(full)
        if children:
            for name in children:
                _dispatch(f"{rel}/{name}", f"{full}/{name}")
            return
        try:
            transport.read(full)
        except FileNotFoundError:
            return
        out.append(rel)

    for name in transport.list(root):
        _dispatch(name, f"{root}/{name}")
    return sorted(out)


def read_file_map(transport: Transport, root: str, rel_paths: list[str]) -> dict[str, bytes]:
    return {rel: transport.read(f"{root}/{rel}") for rel in rel_paths}
