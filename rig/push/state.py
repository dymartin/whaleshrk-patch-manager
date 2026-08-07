"""`.rig/state/last-pushed/` -- the drift baseline and push's own memory of
what it last wrote.

Read and write only through this module, the same convention
`rig.song.bindings` and `rig.catalog.io` already use for their own corners of
`.rig/` (docs/repo-layout.md).

Keyed by **song id**, not by the song's `name:` field or its compiled
directory slug. A song's `name:` can change (that is exactly the rename case
push's classify step has to detect), so the lookup key has to survive a
rename -- the song's repo identity is its YAML filename stem
(`songs/vellichor.yaml` -> `"vellichor"`), assigned by the caller that reads
`songs/` (Task 8's CLI), not by anything in this package.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from rig.atomicio import write_bytes_atomic, write_text_atomic


@dataclass(frozen=True)
class LastPushedMeta:
    directory: str  # e.g. "003-vellichor" -- program prefix + slug, as written
    program: int


def _last_pushed_dir(state_dir: Path) -> Path:
    return state_dir / "last-pushed"


def params_path(state_dir: Path, song_id: str) -> Path:
    return _last_pushed_dir(state_dir) / f"{song_id}.json"


def meta_path(state_dir: Path, song_id: str) -> Path:
    return _last_pushed_dir(state_dir) / f"{song_id}.meta.json"


def read_meta(state_dir: Path, song_id: str) -> Optional[LastPushedMeta]:
    path = meta_path(state_dir, song_id)
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return LastPushedMeta(directory=data["directory"], program=data["program"])


def read_all_meta(state_dir: Path) -> dict[str, LastPushedMeta]:
    """Every recorded song id -> its last-pushed meta. Empty if never pushed."""
    dir_path = _last_pushed_dir(state_dir)
    if not dir_path.is_dir():
        return {}
    result = {}
    for path in sorted(dir_path.glob("*.meta.json")):
        song_id = path.name[: -len(".meta.json")]
        data = json.loads(path.read_text(encoding="utf-8"))
        result[song_id] = LastPushedMeta(directory=data["directory"], program=data["program"])
    return result


def read_params(state_dir: Path, song_id: str) -> Optional[bytes]:
    path = params_path(state_dir, song_id)
    if not path.exists():
        return None
    return path.read_bytes()


def write_last_pushed(state_dir: Path, song_id: str, params_bytes: bytes, meta: LastPushedMeta) -> None:
    """Record what push just verified on the card. Called only after
    verification succeeds (docs/workflows/push.md step 8) -- writing this
    first would let a failed transaction fabricate a baseline pull could
    never actually observe."""
    _last_pushed_dir(state_dir).mkdir(parents=True, exist_ok=True)
    write_bytes_atomic(params_path(state_dir, song_id), params_bytes)
    write_text_atomic(
        meta_path(state_dir, song_id),
        json.dumps({"directory": meta.directory, "program": meta.program}, indent=2, sort_keys=True) + "\n",
    )


def remove_last_pushed(state_dir: Path, song_id: str) -> None:
    """Drop a retired song's baseline -- called once its preset is deleted from the card."""
    params_path(state_dir, song_id).unlink(missing_ok=True)
    meta_path(state_dir, song_id).unlink(missing_ok=True)


def lock_hash_path(state_dir: Path) -> Path:
    return _last_pushed_dir(state_dir) / ".modules-lock-hash"


def hash_lock(lock: dict) -> str:
    """A stable content hash of `.rig/modules.lock`, used only to detect
    whether the lock changed since the last push (docs/workflows/push.md
    step 2, decision #57) -- not a security hash, just a cheap equality
    check over canonical JSON."""
    canonical = json.dumps(lock, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def read_recorded_lock_hash(state_dir: Path) -> Optional[str]:
    path = lock_hash_path(state_dir)
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8").strip()


def write_recorded_lock_hash(state_dir: Path, lock_hash: str) -> None:
    _last_pushed_dir(state_dir).mkdir(parents=True, exist_ok=True)
    write_text_atomic(lock_hash_path(state_dir), lock_hash + "\n")
