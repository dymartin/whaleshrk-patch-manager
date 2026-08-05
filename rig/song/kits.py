"""`.rig/kits.yaml`: kit alias -> `kit-N`, the friendly name a song's `sample:`
field references (`docs/media.md`, `docs/decisions.md` #7).

Format is this task's design choice -- no doc pins one. A flat mapping,
alias to the kit slot number `deploy.sh` gave it:

    warehouse: 1
    tape: 2

Global state shared by every song (`docs/media.md` "Samples are global
state"), so it is parsed and validated once, not per song.
"""

from __future__ import annotations

from pathlib import Path

from ruamel.yaml import YAML

MAX_ALIASES = 24

_yaml = YAML(typ="safe")


class KitsError(ValueError):
    """`.rig/kits.yaml` is malformed, over capacity, or names a symlink."""


class KitsConfig:
    """Alias -> kit number (1-24), plus the media root aliases resolve against."""

    def __init__(self, aliases: dict[str, int]):
        self.aliases = aliases

    def kit_dir(self, media_root: Path, alias: str) -> Path:
        return media_root / "kits" / alias


def parse_kits(path: Path, media_root: Path | None = None) -> KitsConfig:
    """Parse and validate `.rig/kits.yaml`.

    A missing file is an empty, valid config -- no song has to use samples.
    `media_root` is optional so the mapping can be validated (capacity,
    duplicates) without a checkout of `media/` on disk, e.g. in isolated
    tests; when given, each alias's directory is checked for a symlink.
    """
    if not path.exists():
        return KitsConfig({})

    raw = _yaml.load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise KitsError(f"{path}: expected a mapping of alias to kit number, got {type(raw).__name__}")

    aliases: dict[str, int] = {}
    for alias, kit_number in raw.items():
        if not isinstance(kit_number, int) or isinstance(kit_number, bool):
            raise KitsError(f"{path}: alias {alias!r} has non-integer kit number {kit_number!r}")
        aliases[alias] = kit_number

    if len(aliases) > MAX_ALIASES:
        raise KitsError(
            f"{path}: {len(aliases)} kit aliases declared, more than the {MAX_ALIASES} "
            "kit slots deploy.sh creates"
        )

    seen: dict[int, str] = {}
    for alias, kit_number in aliases.items():
        if kit_number in seen:
            raise KitsError(
                f"{path}: kit-{kit_number} is assigned to both {seen[kit_number]!r} and {alias!r}"
            )
        seen[kit_number] = alias

    if media_root is not None:
        for alias in aliases:
            kit_dir = media_root / "kits" / alias
            if kit_dir.is_symlink():
                raise KitsError(f"{path}: kit alias {alias!r} ({kit_dir}) is a symlink")

    return KitsConfig(aliases)
