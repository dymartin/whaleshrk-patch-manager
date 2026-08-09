"""In-memory Transport implementation -- the test double for every later phase.

No filesystem, no device. Phase 4 promotes this to a first-class
implementation and runs it through the same conformance suite as
UsbMassStorage; nothing about its behaviour may be special-cased for tests.
"""

from __future__ import annotations

from .base import TransportPathError, normalize_path


class InMemoryTransport:
    """Transport backed by a dict of path -> bytes, plus an explicit directory set.

    A path is a file if it has bytes in `_files`, a directory if it is in
    `_dirs` or is a parent of any file or directory. Both are namespaced
    together: a path cannot be both.
    """

    def __init__(self) -> None:
        self._files: dict[str, bytes] = {}
        self._dirs: set[str] = {""}  # "" is the root directory

    def _parents(self, path: str) -> list[str]:
        parts = path.split("/") if path else []
        parents = []
        for i in range(len(parts)):
            parents.append("/".join(parts[:i]))
        return parents

    def _is_dir(self, path: str) -> bool:
        """`_dirs` alone is authoritative: every mutator (`write`, `mkdir`,
        `rename`) adds each ancestor of what it creates, so any path that has
        something beneath it is already recorded here."""
        return path in self._dirs

    def _assert_parents_not_files(self, path: str) -> None:
        """Nothing may be created under a path that is already a file -- that
        would silently corrupt the tree instead of raising."""
        for parent in self._parents(path):
            if parent in self._files:
                raise TransportPathError(f"{parent!r} is a file, cannot contain {path!r}")

    def _assert_writable_path(self, path: str) -> None:
        """A path cannot be created as a file if it, or any ancestor, is already
        a file or a directory."""
        if path in self._dirs or self._is_dir(path):
            raise TransportPathError(f"{path!r} is a directory")
        self._assert_parents_not_files(path)

    def exists(self, path: str) -> bool:
        path = normalize_path(path)
        return path in self._files or self._is_dir(path)

    def list(self, path: str) -> list[str]:
        path = normalize_path(path) if path else ""
        prefix = path + "/" if path else ""
        children: set[str] = set()
        for p in list(self._files) + [d for d in self._dirs if d]:
            if p.startswith(prefix) and p != path:
                rest = p[len(prefix):]
                children.add(rest.split("/", 1)[0])
        return sorted(children)

    def read(self, path: str) -> bytes:
        path = normalize_path(path)
        if path not in self._files:
            raise FileNotFoundError(path)
        return self._files[path]

    def write(self, path: str, data: bytes) -> None:
        path = normalize_path(path)
        self._assert_writable_path(path)
        for parent in self._parents(path):
            self._dirs.add(parent)
        self._files[path] = data

    def delete(self, path: str) -> None:
        path = normalize_path(path)
        if path in self._files:
            del self._files[path]
            return
        if self._is_dir(path):
            prefix = path + "/" if path else ""
            for p in [p for p in self._files if p.startswith(prefix)]:
                del self._files[p]
            for d in [d for d in self._dirs if d == path or d.startswith(prefix)]:
                self._dirs.discard(d)
            return
        raise FileNotFoundError(path)

    def mkdir(self, path: str) -> None:
        path = normalize_path(path)
        if path in self._files:
            raise TransportPathError(f"{path!r} is a file")
        self._assert_parents_not_files(path)
        for parent in self._parents(path) + [path]:
            self._dirs.add(parent)

    def rename(self, source: str, target: str) -> None:
        source = normalize_path(source)
        target = normalize_path(target)
        if source in self._files:
            data = self._files.pop(source)
            if target in self._dirs and target != "":
                self.delete(target)
            self._assert_parents_not_files(target)
            for parent in self._parents(target):
                self._dirs.add(parent)
            self._files[target] = data
            return
        if self._is_dir(source):
            if self.exists(target):
                self.delete(target)
            self._assert_parents_not_files(target)
            prefix = source + "/" if source else ""
            moved_files = {
                target + p[len(source):]: data
                for p, data in self._files.items()
                if p.startswith(prefix)
            }
            moved_dirs = {
                target + d[len(source):]
                for d in self._dirs
                if d == source or d.startswith(prefix)
            }
            for p in list(self._files):
                if p.startswith(prefix):
                    del self._files[p]
            for d in [d for d in self._dirs if d == source or d.startswith(prefix)]:
                self._dirs.discard(d)
            self._files.update(moved_files)
            for parent in self._parents(target):
                self._dirs.add(parent)
            self._dirs.update(moved_dirs)
            return
        raise FileNotFoundError(source)

    def flush(self) -> None:
        # Nothing is buffered: writes land in `_files` synchronously.
        pass
