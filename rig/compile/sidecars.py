"""Sidecar `.txt` generation for occupied stateful chain slots.

Five ORHACK built-ins persist state as loose `.txt` files beside a preset's
`params.json`, invisible to the preset system itself
(docs/platform/state.md). Compile emits a complete, deterministic default
set for each occupied stateful slot: an *absent* file leaves an array
holding whatever the previously loaded preset wrote there (decision #1), so
omitting one is not a safe simplification -- it is the exact staleness bug
this module exists to prevent.

Templates and default content are read once from the pinned, SHA-256-
verified ORHACK 0.52b `Init` preset (`fixtures/card/...`, see
docs/platform/README.md) -- the same "fixed data, not a live source"
treatment `rig.catalog.builtins` already gives the module tree. `Init`'s a1
slot ships the full `loop`/`metric`/`step-seq-{note,vel,length}` default set
(224 files, verified by direct byte count against
docs/platform/state.md's "224 sidecars ... 154 for d1"). Those filenames
embed only the slot id and a track letter -- no song data -- so retargeting
to any occupied slot is a pure filename substitution with the content
copied unchanged.

Reading `sequencers/overdrum/CG-Pd-Library-Local/sequencer/seq3.pd` and
`sequencers/overflow/overflow.pd` directly (via
`rig.catalog.sidecar.scan_module_sidecars`, the same tool Task 1 built to
verify community modules) shows both also read/write `<slot>-slot-
tracker.txt` and `<slot>-seq<n>x.txt`, and `sequencers/clips` /
`sequencers/polystep` are stateful too. But *no* shipped preset -- neither a
freshly deployed `Init` nor `jam`, a real working set -- ever carries
default content for any of those four file families; the two `slot-tracker`
files `jam` does carry are documented stale leftovers on `-empty-` slots,
not a default anyone shipped (docs/platform/state.md). With no verified
template (Prompt.md Global Constraint #1: never assume device behaviour),
compiling a song that occupies a slot with any of those four is a hard,
distinct compile error rather than a fabricated or silently incomplete file
set -- see `docs/decisions.md` and the Task 3 report for the follow-up this
leaves open.
"""

from __future__ import annotations

from pathlib import Path

from rig.catalog.entry import CatalogEntry

TRACKS = "abcdefg"
PATTERNS = range(1, 11)

_TEMPLATE_SLOT = "a1"
_INIT_PRESET_DIR = (
    Path(__file__).resolve().parent.parent.parent
    / "fixtures"
    / "card"
    / "Patches"
    / "0RHACK"
    / "data"
    / "presets"
    / "Init"
)

MORPHER_BANKS = [f"p{n}" for n in range(1, 17)]

OVERDRUM_MODULE_TYPE = "sequencers/overdrum"
OVERFLOW_MODULE_TYPE = "sequencers/overflow"
MORPHER_MODULE_TYPE = "mod-sources/morpher"

# The complete built-in "Complete pattern inventory" from docs/platform/
# state.md -- every module type known to persist state outside params.json.
STATEFUL_MODULE_TYPES = {
    OVERDRUM_MODULE_TYPE,
    OVERFLOW_MODULE_TYPE,
    "sequencers/clips",
    "sequencers/polystep",
    MORPHER_MODULE_TYPE,
}

# Subset with a verified default template (see module docstring).
_VERIFIED_MODULE_TYPES = {OVERDRUM_MODULE_TYPE, OVERFLOW_MODULE_TYPE, MORPHER_MODULE_TYPE}


class UnverifiedStatefulModuleError(ValueError):
    """A song occupies a slot with a stateful module that has no verified
    default sidecar template -- see this module's docstring for why that is
    a hard error rather than fabricated or omitted content."""


def _read_init_template(filename: str) -> bytes:
    return (_INIT_PRESET_DIR / filename).read_bytes()


def _overdrum_family_files(target_slot: str, *, include_length: bool) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    for track in TRACKS:
        for prefix in ("loop", "metric"):
            template_name = f"{prefix}-{_TEMPLATE_SLOT}-{track}.txt"
            files[f"{prefix}-{target_slot}-{track}.txt"] = _read_init_template(template_name)
        for n in PATTERNS:
            for prefix in ("step-seq-note", "step-seq-vel"):
                template_name = f"{prefix}-{_TEMPLATE_SLOT}-{track}-p{n}.txt"
                files[f"{prefix}-{target_slot}-{track}-p{n}.txt"] = _read_init_template(template_name)
            if include_length:
                template_name = f"step-seq-length-{_TEMPLATE_SLOT}-{track}-p{n}.txt"
                files[f"step-seq-length-{target_slot}-{track}-p{n}.txt"] = _read_init_template(template_name)
    return files


def _morpher_files() -> dict[str, bytes]:
    # Global, not slot-keyed -- morpher's own filenames carry no slot token
    # (rig.catalog.sidecar resolves its template to bare "\$4.txt"), so the
    # occupying m-slot never appears in the sidecar name.
    return {f"{bank}.txt": _read_init_template(f"{bank}.txt") for bank in MORPHER_BANKS}


def sidecar_files_for_slot(entry: CatalogEntry, target_slot: str) -> dict[str, bytes]:
    """Sidecar files one occupied slot needs, keyed by filename (no directory).

    Empty for a module type with no persistent state -- the common case.
    Raises `UnverifiedStatefulModuleError` for a module known to be
    stateful (one of the five built-ins, or -- for a community module --
    flagged by `rig.catalog.sidecar`'s own scan at ingest time) but without
    a verified default template.
    """
    module_type = entry.module_type
    if module_type == OVERDRUM_MODULE_TYPE:
        return _overdrum_family_files(target_slot, include_length=False)
    if module_type == OVERFLOW_MODULE_TYPE:
        return _overdrum_family_files(target_slot, include_length=True)
    if module_type == MORPHER_MODULE_TYPE:
        return _morpher_files()
    if module_type in STATEFUL_MODULE_TYPES or entry.sidecar_templates:
        raise UnverifiedStatefulModuleError(
            f"{entry.key} ({module_type!r}) persists state as sidecar files, but no "
            "verified default content is available for them -- see rig.compile.sidecars"
        )
    return {}
