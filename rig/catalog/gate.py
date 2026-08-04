"""The ordered per-candidate validation gate.

Order is load-bearing and undocumented in Patchstorage upstream data -- it
was derived by replaying the frozen fixture until every one of the five
asserted counts reproduced exactly (145 candidates -> 122 pass / 14
not-a-module / 5 wrong-arch / 3 rack-redistribution / 1 bad-JSON). The full
derivation, including the three candidates whose bucket depends on which
check runs first, is recorded in docs/catalog.md "Reject ordering". Do not
reorder these checks without re-deriving the counts.

Four conditions are candidate-level: if any of them fires anywhere in the
archive, the whole candidate is rejected and contributes zero catalog
entries, matching the measured buckets (a 5-module pack like `8rac` counts
once in the wrong-arch bucket, not five times). Two further conditions --
unmodelled sidecars and duplicate runtime paths -- are module-level and
handled by rig/catalog/ingest.py after this gate, since a duplicate path can
only be detected with the full catalog in view and the sidecar brief text
says "rejects the module" (singular), not the candidate.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum

from .archive import CandidateArchive
from .elf import ELF_MAGIC, ElfError, check_abi, parse_elf_header
from .safety import ArchiveEntry, check_archive_safety


class RejectReason(str, Enum):
    """Stable identifiers -- Task 9 consumes these as check ids, not log text."""

    ARCHIVE_UNSAFE = "archive-unsafe"
    NOT_A_MODULE = "not-a-module"
    BAD_JSON = "bad-json"
    WRONG_ARCH = "wrong-arch"
    RACK_REDISTRIBUTION = "rack-redistribution"
    UNMODELLED_SIDECAR = "unmodelled-sidecar"
    DUPLICATE_MODULE_PATH = "duplicate-module-path"


@dataclass(frozen=True)
class ModuleDir:
    """One `<dir>/module.json` + `<dir>/module.pd` pair inside a candidate archive."""

    path: str  # "" means the module sits at the archive root
    module_json: dict


@dataclass(frozen=True)
class GateReject:
    reason: RejectReason
    message: str


@dataclass(frozen=True)
class GateAccept:
    module_dirs: list[ModuleDir]


GateResult = GateReject | GateAccept


def _dirname(entry_name: str) -> str:
    parts = entry_name.rsplit("/", 1)
    return parts[0] if len(parts) == 2 else ""


def _skip_nested(module_dirs: set[str]) -> set[str]:
    """Drop a module directory that sits inside another module directory.

    Reproduces `loadModuleDir`'s recursion-stops-at-first-module.pd
    behaviour (docs/platform/modules.md): a nested module.json is never
    reached by the runtime, so it must never become a catalog entry either.
    Measured in the real fixture only inside two already wrong-arch-rejected
    candidates (162128, 171653) and the built-in tree's own
    `effects/delay/spiraldelay/module` -- kept general here rather than
    special-cased, since it is a structural runtime fact, not a fixture
    quirk.
    """
    kept: list[str] = []
    for d in sorted(module_dirs, key=lambda p: (p.count("/"), p)):
        if any(d == k or d.startswith(k + "/") for k in kept):
            continue
        kept.append(d)
    return set(kept)


def _module_dirs(file_entries: list[ArchiveEntry]) -> set[str]:
    """Directories containing both module.json and module.pd, nested ones dropped."""
    has_json: set[str] = set()
    has_pd: set[str] = set()
    for entry in file_entries:
        base = entry.name.rsplit("/", 1)[-1]
        if base == "module.json":
            has_json.add(_dirname(entry.name))
        elif base == "module.pd":
            has_pd.add(_dirname(entry.name))
    return _skip_nested(has_json & has_pd)


def _main_pd_dirs(file_entries: list[ArchiveEntry]) -> list[str]:
    return [_dirname(e.name) for e in file_entries if e.name.rsplit("/", 1)[-1] == "main.pd"]


def _under_any_module_dir(path: str, module_dirs: set[str]) -> bool:
    """True if `path` equals a module directory, or sits inside one."""
    return any(path == d or path.startswith(d + "/") for d in module_dirs)


def _binary_candidate_names(file_entries: list[ArchiveEntry]) -> list[str]:
    """Entry names worth an ELF check: everything that isn't module.json or a .pd file."""
    names = []
    for entry in file_entries:
        base = entry.name.rsplit("/", 1)[-1]
        if base == "module.json" or base.lower().endswith(".pd"):
            continue
        names.append(entry.name)
    return names


def module_json_path(module_dir: str) -> str:
    return f"{module_dir}/module.json" if module_dir else "module.json"


def gate_candidate(archive: CandidateArchive) -> GateResult:
    entries = archive.entries()

    safety_problems = check_archive_safety(entries)
    if safety_problems:
        return GateReject(RejectReason.ARCHIVE_UNSAFE, "; ".join(safety_problems))

    file_entries = [e for e in entries if not e.is_dir]

    module_dirs = _module_dirs(file_entries)
    if not module_dirs:
        return GateReject(
            RejectReason.NOT_A_MODULE,
            "no directory in the archive contains both module.json and module.pd",
        )

    parsed: dict[str, dict] = {}
    for module_dir in sorted(module_dirs):
        path = module_json_path(module_dir)
        try:
            raw = archive.read(path).decode("utf-8")
        except FileNotFoundError:
            return GateReject(RejectReason.BAD_JSON, f"{path}: not present in archive content")
        try:
            parsed[module_dir] = json.loads(raw)
        except json.JSONDecodeError as exc:
            return GateReject(RejectReason.BAD_JSON, f"{path}: {exc}")

    wrong_arch_problems = []
    for name in _binary_candidate_names(file_entries):
        try:
            header_bytes = archive.read_header(name, 64)
        except FileNotFoundError:
            # The frozen fixture only captures files that start with the ELF
            # magic number; a missing header means Task 0 already determined
            # this file is not ELF and there is nothing to check.
            continue
        if header_bytes[:4] != ELF_MAGIC:
            continue
        try:
            header = parse_elf_header(header_bytes)
        except ElfError as exc:
            wrong_arch_problems.append(f"{name}: {exc}")
            continue
        abi_problems = check_abi(header)
        if abi_problems:
            wrong_arch_problems.append(f"{name}: {'; '.join(abi_problems)}")
    if wrong_arch_problems:
        return GateReject(RejectReason.WRONG_ARCH, "; ".join(wrong_arch_problems))

    for main_pd_dir in _main_pd_dirs(file_entries):
        if not _under_any_module_dir(main_pd_dir, module_dirs):
            return GateReject(
                RejectReason.RACK_REDISTRIBUTION,
                f"main.pd at {main_pd_dir!r} is not inside any module directory "
                "-- rack entry point, not a chain-slot module",
            )

    return GateAccept(
        module_dirs=[ModuleDir(path=d, module_json=parsed[d]) for d in sorted(module_dirs)]
    )
