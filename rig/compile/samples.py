"""Sample reference resolution: `<kit-alias>/<file.wav>` -> `samp_source`
plus `samp_select` (docs/platform/samples.md, docs/media.md).

The device stores no filename -- only a folder selector and a normalised
position resolved by a sorted directory listing -- so this is the one place
compile must faithfully reproduce both the position formula and the real
folder contents; getting either wrong plays a different file with no error
and no drift signal (docs/media.md "Positional-reference hazard").

Only the kit-alias form is compiled: docs/schema.md's `sample:` rule
documents `<kit-alias>/<filename>` as the only reference shape a song file
can express. `samp_source` values 25-27 (`samples/`, `loops/`, `synths/`)
are real device states -- needed by Task 6's reverse-mapper -- but the song
schema has no field that reaches them, so compile never produces them.

Folder-content validation (lowercase/portable names, case-insensitive
collisions, ignored non-.wav files) lives here rather than in
`rig.song.validate` because this is the phase that enumerates a folder's
contents anyway, to compute `samp_select` (Prompt/03-compiler.md
"Samples"). `rig.song.validate` already checked `.rig/kits.yaml` itself
(alias cap, duplicate `kit-N`, symlinks) and the reference's shape
(`<alias>/<filename.wav>`); this module re-derives only what that check has
no folder listing for yet.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from rig.song.errors import Finding
from rig.song.kits import KitsConfig


@dataclass(frozen=True)
class ResolvedSample:
    samp_source: int
    samp_select: float


class SampleCompileError(ValueError):
    """A `sample:` reference or the media folder it points at is invalid.

    Carries every `Finding` found, not just the first, matching
    `rig.song.errors.SongValidationError`'s contract.
    """

    def __init__(self, findings: list[Finding]):
        self.findings = findings
        super().__init__("; ".join(f"{f.code}: {f.message}" for f in findings))


def _is_portable_name(name: str) -> bool:
    """ASCII letters, digits, '-', '_', '.' only -- vfat/exfat-safe and
    unambiguous regardless of the filesystem the card or a repo checkout
    happens to use."""
    return bool(name) and all(c.isascii() and (c.isalnum() or c in "-_.") for c in name)


def scan_wav_names(names: list[str], context: str) -> tuple[list[str], list[Finding]]:
    """Validate one media folder's already-listed filenames.

    Separated from directory listing (`scan_wav_folder`, below) so the name
    rules -- portability, lowercase, case-insensitive collision -- are
    testable directly: a real filesystem that is itself case-insensitive
    (vfat/exfat on the card, but also NTFS and default APFS on a
    contributor's laptop) cannot reliably hold two on-disk entries whose
    names differ only by case, which is exactly the git-tracked scenario
    this exists to catch.

    Hard errors: a non-portable or non-lowercase name, or a case-insensitive
    collision. Warning: a non-`.wav` file, ignored and not counted toward
    `N`. Input order is preserved; callers list in POSIX `glob()` order
    (plain ascending, docs/platform/samples.md "Listing order").
    """
    findings: list[Finding] = []
    wav_names: list[str] = []
    lower_seen: dict[str, str] = {}
    for name in names:
        if not name.lower().endswith(".wav"):
            findings.append(
                Finding("IGNORED_NON_WAV_FILE", f"{context}: {name!r} is not a .wav file and is ignored")
            )
            continue
        lower = name.lower()
        if lower in lower_seen:
            findings.append(
                Finding(
                    "SAMPLE_FILENAME_COLLISION",
                    f"{context}: {name!r} collides with {lower_seen[lower]!r} once case is ignored",
                )
            )
            continue
        lower_seen[lower] = name
        if name != lower or not _is_portable_name(name):
            findings.append(
                Finding("INVALID_SAMPLE_FILENAME", f"{context}: {name!r} must be a lowercase, portable filename")
            )
            continue
        wav_names.append(name)

    return wav_names, findings


def scan_wav_folder(folder: Path, context: str) -> tuple[list[str], list[Finding]]:
    """List one media folder and validate its contents (`scan_wav_names`).

    Hard error: a missing folder, in addition to everything
    `scan_wav_names` checks.
    """
    if not folder.is_dir():
        return [], [Finding("MISSING_SAMPLE_FOLDER", f"{context}: {folder} does not exist")]
    names = sorted(entry.name for entry in folder.iterdir() if entry.is_file())
    return scan_wav_names(names, context)


def resolve_sample(sample_ref: str, kits: KitsConfig, media_root: Path, *, context: str) -> ResolvedSample:
    """`<kit-alias>/<filename.wav>` -> samp_source/samp_select.

    The reference's shape and the alias's existence in `.rig/kits.yaml` are
    already checked by `rig.song.validate` before this normally runs; this
    re-checks the alias defensively (compile is callable standalone) and
    then does what that check cannot: list the folder and locate the file
    in it.
    """
    alias, filename = sample_ref.split("/", 1)
    kit_number = kits.aliases.get(alias)
    if kit_number is None:
        raise SampleCompileError([Finding("UNKNOWN_KIT_ALIAS", f"{context}: unknown kit alias {alias!r}")])

    folder = kits.kit_dir(media_root, alias)
    wav_names, findings = scan_wav_folder(folder, f"{context}: kit {alias!r}")
    errors = [f for f in findings if f.code != "IGNORED_NON_WAV_FILE"]
    if errors:
        raise SampleCompileError(errors)

    if filename not in wav_names:
        raise SampleCompileError(
            [Finding("MISSING_SAMPLE_FILE", f"{context}: {filename!r} not found in {folder}")]
        )

    n = len(wav_names)
    k = wav_names.index(filename)
    # Midpoint of the valid interval for file k of n, for maximum float
    # tolerance against the device's own inverse formula (samples.md).
    samp_select = 100.0 * (k + 0.5) / (n - 0.05)
    return ResolvedSample(samp_source=kit_number, samp_select=samp_select)
