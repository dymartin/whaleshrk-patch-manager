"""Chain name -> letter binding store: `.rig/state/chains/<song-slug>.json`.

Format is this task's design choice -- no doc pins one (Prompt/02-schema.md
ambiguity resolution #2). One JSON object per song, mapping chain name to its
letter ("A"-"D"), keys sorted, two-space indent, trailing newline -- the same
convention `rig.catalog.io` already uses for `.rig/catalog/*.json`.

A recorded binding is authoritative (`docs/decisions.md` #8, #37, #58): push
writes it, pull uses it to attribute drift, `rename-chain` rewrites it, and
letter assignment (`rig.song.letters`) only fills in what
it does not cover. One module so all four reuse the same format rather than
reimplementing it.
"""

from __future__ import annotations

import json
from pathlib import Path

from rig.atomicio import write_text_atomic

from .letters import CHAIN_LETTERS


def bindings_path(state_dir: Path, song_slug: str) -> Path:
    return state_dir / f"{song_slug}.json"


def read_bindings(state_dir: Path, song_slug: str) -> dict[str, str]:
    """Chain name -> letter for `song_slug`. Empty when no binding is recorded yet."""
    path = bindings_path(state_dir, song_slug)
    if not path.exists():
        return {}
    return dict(json.loads(path.read_text(encoding="utf-8")))


def write_bindings(state_dir: Path, song_slug: str, bindings: dict[str, str]) -> None:
    for name, letter in bindings.items():
        if letter not in CHAIN_LETTERS:
            raise ValueError(f"chain {name!r}: {letter!r} is not a chain letter (A-D)")
    state_dir.mkdir(parents=True, exist_ok=True)
    write_text_atomic(bindings_path(state_dir, song_slug), json.dumps(bindings, indent=2, sort_keys=True) + "\n")


def remove_bindings(state_dir: Path, song_slug: str) -> None:
    """Drop a retired song's chain bindings. Without this, a later song
    reusing the same YAML filename stem silently inherits the retired
    song's name -> letter binding -- either a false un-commanded-rename
    refusal on a song nobody renamed, or silent reuse of old letters
    (`rig.push.plan.detect_chain_rename`, docs/workflows/push.md step 5)."""
    bindings_path(state_dir, song_slug).unlink(missing_ok=True)
