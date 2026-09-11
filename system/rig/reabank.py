"""Generate a REAPER .reabank file from `songs/*.yaml`.

One bank, one line per song: `<program> <song name>`. Program numbers and
uniqueness are `rig lint`'s job (PROGRAM_OUT_OF_RANGE, DUPLICATE_PROGRAM) --
this module trusts its input.
"""

from __future__ import annotations

from .song import Song

BANK_MSB = 0
BANK_LSB = 0
BANK_NAME = "ORHACK"


def build_reabank(songs: dict[str, Song]) -> str:
    lines = [f"Bank {BANK_MSB} {BANK_LSB} {BANK_NAME}"]
    for song in sorted(songs.values(), key=lambda s: s.program):
        lines.append(f"{song.program} {song.name}")
    return "\n".join(lines) + "\n"
