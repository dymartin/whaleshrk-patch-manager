"""Step 6 of push: media mirroring plan for the four playback paths.

Builds the *desired* final content of each mirrored directory by reading the
repo's `media/` tree. Push's staged-swap transaction (`rig.push.transact`)
replaces the live card directory wholesale with whatever is staged here, so
"mirrored, deletions included" falls out of a full-directory swap for free:
nothing absent from the desired set survives the swap.

`media/orhack/recordings/` and the card's own `media/samples/` (the shared
Organelle directory the sampler's record function writes, distinct from
`media/orhack/samples/`) are device-owned and never appear here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from rig.push.errors import PushError
from rig.song.kits import KitsConfig

WAV_SUFFIX = ".wav"


@dataclass(frozen=True)
class MediaGroup:
    """One mirrored directory. `card_path` is card-relative
    (`media/orhack/...`); `files` is relpath -> bytes, the exact desired
    final content."""

    name: str  # diagnostic label -- "samples", "kit:warehouse"
    card_path: str
    files: dict[str, bytes]


@dataclass(frozen=True)
class MediaPlan:
    groups: list[MediaGroup]
    ignored_non_wav: list[str] = field(default_factory=list)  # repo-relative paths, for the report


def _read_wav_dir(directory: Path, *, group_label: str, ignored: list[str]) -> dict[str, bytes]:
    if not directory.is_dir():
        return {}
    files: dict[str, bytes] = {}
    lower_seen: dict[str, str] = {}
    for path in sorted(directory.rglob("*")):
        if not path.is_file() and not path.is_symlink():
            continue
        rel = path.relative_to(directory).as_posix()
        if path.suffix.lower() != WAV_SUFFIX:
            ignored.append(f"{directory}/{rel}")
            continue
        if path.is_symlink():
            raise PushError(
                "MEDIA_SYMLINK_REJECTED",
                f"{group_label}: {rel!r} is a symlink -- media files must be real, "
                "version-controlled content",
            )
        lower = rel.lower()
        if lower in lower_seen:
            raise PushError(
                "MEDIA_CASE_COLLISION",
                f"{group_label}: {rel!r} and {lower_seen[lower]!r} collide on a "
                "case-insensitive filesystem",
            )
        lower_seen[lower] = rel
        files[rel] = path.read_bytes()
    return files


def build_media_plan(media_root: Path, kits: KitsConfig) -> MediaPlan:
    """The desired content of every card-mirrored playback path.

    `media/samples/` is one group that also carries `loops/` and `synths/`
    nested under it -- all three live under the identical card parent
    (`media/orhack/samples/...`), so one staged swap covers all three.
    Only kit aliases present in `kits.yaml` are
    considered, so a `kit-N` on the card with no alias mapped to it is never
    touched.
    """
    ignored: list[str] = []
    groups = [
        MediaGroup(
            name="samples",
            card_path="media/orhack/samples",
            files=_read_wav_dir(media_root / "samples", group_label="media/samples", ignored=ignored),
        )
    ]
    for alias, kit_number in sorted(kits.aliases.items()):
        groups.append(
            MediaGroup(
                name=f"kit:{alias}",
                card_path=f"media/orhack/kits/kit-{kit_number}",
                files=_read_wav_dir(
                    media_root / "kits" / alias, group_label=f"media/kits/{alias}", ignored=ignored
                ),
            )
        )
    return MediaPlan(groups=groups, ignored_non_wav=ignored)
