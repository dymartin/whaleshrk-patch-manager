r"""Sidecar `.txt` generation for occupied stateful chain slots.

Five ORHACK built-ins persist state as loose `.txt` files beside a preset's
`params.json`, invisible to the preset system itself
(docs/platform/state.md). Compile emits a complete, deterministic default
set for each occupied stateful slot: an *absent* file leaves an array
holding whatever the previously loaded preset wrote there (decision #1), so
omitting one is not a safe simplification -- it is the exact staleness bug
this module exists to prevent.

Only `mod-sources/morpher` has a verified default template. Its 16
`p<N>.txt` banks are read from the pinned, SHA-256-verified ORHACK 0.52b
`Init` preset (`fixtures/card/...`, see docs/platform/README.md) -- the same
"fixed data, not a live source" treatment `rig.catalog.builtins` already
gives the module tree -- and morpher's filenames carry no slot token
(`rig.catalog.sidecar` resolves its template to bare `\$4.txt`), so the same
16 files apply regardless of which `m` slot the module occupies.

`sequencers/{overdrum,overflow,clips,polystep}` are stateful too, but none
has a verified template, so occupying a slot with any of them is a hard
`UnverifiedStatefulModuleError` (decision #69). This includes overdrum and
overflow even though `Init` ships default content for *some* of what they
read (`loop-*`, `metric-*`, `step-seq-{note,vel,length}-*`) -- because they
also read two file families `Init` never ships anywhere, and dropping only
those two would be exactly the silent, partial staleness this module exists
to prevent:

- **`<slot>-slot-tracker.txt`.** Traced in
  `sequencers/overdrum/CG-Pd-Library-Local/sequencer/seq3.pd`'s
  `save-the-txts` subpatch: `r loadbang-\$1` (line 639) -> `del 2` (line
  640) -> a literal `69` message -> `route 69` -> the `read
  \$1/presets/\$2/\$3-slot-tracker.txt` message (line 604). `loadbang-\$1`
  is broadcast on every patch load (the same receive many other subpatches
  in `overdrum.pd` use to trigger their own load-time refresh), so this read
  is unconditional, not gated behind a user action.
- **`<slot>-seq<n>x.txt`.** Same subpatch: the `read-bang` inlet (line 595)
  feeds, through a short unconditional chain (`f` -> `t f f` -> `list
  prepend`), the `read \$1/presets/\$2/\$3-seq\$4x.txt` message (line 597).
  `read-bang` is the subpatch's own declared load-trigger inlet -- paired
  with a `write-bang` inlet for saves -- not a manual control.

Both reads fire on every load, and `fixtures/card/Patches/0RHACK/data/
presets/Init/` -- decision #48's canonical source, and the one place that
also verifiably has *all four* of `loop`/`metric`/`step-seq-note`/`step-seq-
vel` present -- carries zero files matching either `*-slot-tracker.txt` or
`*-seq*x.txt` for any of its 24 slots. With no
verified template for either family (Prompt.md Global Constraint #1: never
assume device behaviour), and no way to emit only the *other* families
without silently narrowing what decision #1 requires, `sequencers/overdrum`
and `sequencers/overflow` raise like `clips` and `polystep` do. Recorded in
`docs/open-questions.md` -- resolvable by a hardware capture (Task 10) of
each module freshly placed and read back.
"""

from __future__ import annotations

from pathlib import Path

from rig.catalog.entry import CatalogEntry

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
# Only MORPHER_MODULE_TYPE has a verified template; see module docstring for
# why the other four -- including the two nominally "supported" sequencers
# -- all raise.
STATEFUL_MODULE_TYPES = {
    OVERDRUM_MODULE_TYPE,
    OVERFLOW_MODULE_TYPE,
    "sequencers/clips",
    "sequencers/polystep",
    MORPHER_MODULE_TYPE,
}


class UnverifiedStatefulModuleError(ValueError):
    """A song occupies a slot with a stateful module that has no verified
    default sidecar template -- see this module's docstring for why that is
    a hard error rather than fabricated or omitted content."""


def _read_init_template(filename: str) -> bytes:
    return (_INIT_PRESET_DIR / filename).read_bytes()


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
    a verified default template covering everything it reads.
    """
    module_type = entry.module_type
    if module_type == MORPHER_MODULE_TYPE:
        return _morpher_files()
    if module_type in STATEFUL_MODULE_TYPES or entry.sidecar_templates:
        raise UnverifiedStatefulModuleError(
            f"{entry.key} ({module_type!r}) persists state as sidecar files, but no "
            "verified default content is available for all of them -- see "
            "rig.compile.sidecars"
        )
    return {}
