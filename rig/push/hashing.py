"""Shared content-hashing recipe.

Module reconciliation (`rig.push.modules`) and transaction verification
(`rig.push.transact`) both need to turn a `{relpath: bytes}` file map into
one comparable digest -- the same recipe, so a hash computed while staging
and one recomputed after a swap are guaranteed comparable.
"""

from __future__ import annotations

import hashlib


def hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def per_file_hashes(files: dict[str, bytes]) -> dict[str, str]:
    return {rel: hash_bytes(content) for rel, content in files.items()}


def hash_file_map(files: dict[str, bytes]) -> str:
    """One digest for a whole file map: sha256 over sorted
    (relpath, sha256(content)) pairs, independent of write order."""
    hasher = hashlib.sha256()
    for rel in sorted(files):
        hasher.update(rel.encode("utf-8"))
        hasher.update(hashlib.sha256(files[rel]).digest())
    return hasher.hexdigest()
