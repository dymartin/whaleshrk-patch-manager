"""Song model -> one on-device preset.

Pure function, no card I/O: the caller gets back an in-memory preset
(directory name plus relative path -> bytes) and decides what to do with it
-- push (Task 5) is what writes, mirrors and deletes on the card. This is
what makes Global Constraint #6 ("a song file plus `.rig/modules.lock` plus
`.rig/state/chains/` fully determines the compiled output") testable without
a card at all.

See docs/schema.md, docs/platform/{routing,state,midi,samples}.md,
docs/media.md and Prompt/03-compiler.md for the rules this implements.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

from rig.catalog.builtins import EMPTY_MODULE_TYPE
from rig.catalog.entry import CatalogEntry
from rig.catalog.slugs import slug
from rig.song.kits import KitsConfig
from rig.song.letters import CAPACITY, CHAIN_LETTERS, ChainSlots, LetterAssignmentError, assign_letters
from rig.song.model import ModuleSlot, ModuleUse, Song

from . import sidecars
from .errors import CompileError
from .jsonfmt import dumps as _dumps_device_json
from .router import compile_router, compile_transport
from .samples import resolve_sample

# Verified against fixtures/card/Patches/0RHACK/modules/-empty-/module.json
# and every -empty- slot in the shipped Init and jam presets: the wrapper's
# only parameter, always at its declared default.
EMPTY_PARAMS: dict[str, float] = {"thru_gain": 100}

_CHAIN_SLOT_IDS = [
    f"{letter.lower()}{n}" for letter in CHAIN_LETTERS for n in range(1, CAPACITY[letter] + 1)
]
FIXED_SLOT_IDS = _CHAIN_SLOT_IDS + ["f1", "f2", "f3", "m1", "m2", "m3", "p1", "p2", "s1", "s2"]


@dataclass(frozen=True)
class CompiledPreset:
    """A compiled preset, in memory.

    `directory` is the sanitised song slug alone -- no program prefix. Push
    owns the zero-padded 3-digit prefix (`format_program_prefix` below) and
    the decision of *when* to prepend it, because that requires seeing every
    selected song at once (docs/workflows/push.md "Compile"). `files` maps a
    path relative to the preset directory ("params.json", each sidecar
    filename) to its exact bytes.
    """

    directory: str
    files: dict[str, bytes]


def format_program_prefix(program: int) -> str:
    """Zero-padded 3-digit program prefix (decision #49).

    MEC's directory scan sorts lexicographically, so an unpadded prefix
    desyncs the Program Change index for every song above program 9. A
    static formatting rule shared by real songs and gap placeholders alike,
    factored out so both compute it the same way.
    """
    if not (0 <= program <= 127):
        raise CompileError("PROGRAM_OUT_OF_RANGE", f"program {program} is outside 0-127")
    return f"{program:03d}"


def _catalog_by_key(catalog: Iterable[CatalogEntry]) -> dict[str, CatalogEntry]:
    return {e.key: e for e in catalog}


def _catalog_by_type(catalog: Iterable[CatalogEntry]) -> dict[str, CatalogEntry]:
    return {e.module_type: e for e in catalog}


def _empty_slot() -> dict:
    return {
        "moduleType": EMPTY_MODULE_TYPE,
        "params": dict(EMPTY_PARAMS),
        "midi-mapping": {"cc": {}},
        "mod-mapping": {"bus": {}},
    }


def _module_params(entry: CatalogEntry, song_params: dict[str, float], context: str) -> dict[str, float]:
    """Every catalog parameter, device id -> value: the song's value by
    friendly name where given, the catalog default otherwise (decision #13:
    "unmentioned params compile to catalog defaults, pinned per version").
    Emits the full set -- no deltas, no omitted defaults."""
    name_to_spec = {p.name: p for p in entry.params}
    unknown = sorted(set(song_params) - set(name_to_spec))
    if unknown:
        raise CompileError("UNKNOWN_PARAM", f"{context}: module {entry.key!r} has no parameter(s) {unknown}")
    return {p.id: song_params.get(p.name, p.default) for p in entry.params}


def _cc_key(channel: int, cc: int) -> int:
    return channel * 128 + cc


def _module_midi_mapping(module: ModuleSlot, entry: CatalogEntry, chain_channel: int, context: str) -> dict[int, list[str]]:
    name_to_spec = {p.name: p for p in entry.params}
    cc: dict[int, list[str]] = {}
    for param_name, mapping in module.midi.items():
        spec = name_to_spec.get(param_name)
        if spec is None:
            raise CompileError("UNKNOWN_PARAM", f"{context}: midi.{param_name!r} is not a parameter of {entry.key!r}")
        channel = mapping.channel if mapping.channel is not None else chain_channel
        key = _cc_key(channel, mapping.cc)
        cc.setdefault(key, []).append(spec.id)
    return dict(sorted(cc.items()))


def _compile_occupied_slot(
    entry: CatalogEntry,
    song_params: dict[str, float],
    cc: dict[int, list[str]],
    context: str,
    *,
    sample_ref: Optional[str] = None,
    kits: Optional[KitsConfig] = None,
    media_root: Optional[Path] = None,
) -> dict:
    params = _module_params(entry, song_params, context)
    if sample_ref is not None:
        # samp_source/samp_select are fixed device parameter ids
        # (docs/platform/samples.md), not friendly-name driven -- a module
        # carrying `sample:` must declare both or the reference has nowhere
        # to land.
        param_ids = {p.id for p in entry.params}
        if "samp_source" not in param_ids or "samp_select" not in param_ids:
            raise CompileError(
                "SAMPLE_NOT_SUPPORTED", f"{context}: module {entry.key!r} has no sampler parameters"
            )
        if kits is None or media_root is None:
            raise CompileError(
                "SAMPLE_RESOLUTION_UNAVAILABLE",
                f"{context}: sample {sample_ref!r} needs both 'kits' and 'media_root'",
            )
        resolved = resolve_sample(sample_ref, kits, media_root, context=context)
        params["samp_source"] = resolved.samp_source
        params["samp_select"] = resolved.samp_select
    return {
        "moduleType": entry.module_type,
        "params": params,
        "midi-mapping": {"cc": {str(k): v for k, v in cc.items()}},
        "mod-mapping": {"bus": {}},
    }


def _slot_sidecars(entry: CatalogEntry, slot_id: str) -> dict[str, bytes]:
    try:
        return sidecars.sidecar_files_for_slot(entry, slot_id)
    except sidecars.UnverifiedStatefulModuleError as exc:
        raise CompileError("UNVERIFIED_STATEFUL_MODULE", str(exc)) from exc


def _require_entry(catalog_by_key: dict[str, CatalogEntry], key: str, context: str) -> CatalogEntry:
    entry = catalog_by_key.get(key)
    if entry is None:
        raise CompileError("UNKNOWN_MODULE", f"{context}: module {key!r} is not in the catalog")
    return entry


def _compile_module_use(
    use: ModuleUse, catalog_by_key: dict[str, CatalogEntry], context: str
) -> tuple[dict, CatalogEntry]:
    entry = _require_entry(catalog_by_key, use.key, context)
    return _compile_occupied_slot(entry, use.params, {}, context), entry


def compile_song(
    song: Song,
    *,
    catalog: Iterable[CatalogEntry],
    kits: Optional[KitsConfig] = None,
    media_root: Optional[Path] = None,
    bindings: Optional[dict[str, str]] = None,
) -> CompiledPreset:
    """Compile one song to a preset. Raises `CompileError` (or
    `rig.compile.samples.SampleCompileError`) on anything invalid --
    callers that want every problem in one pass should run
    `rig.song.validate.validate_song` first, which never raises on the
    first finding."""
    catalog_by_key = _catalog_by_key(catalog)
    catalog_by_type = _catalog_by_type(catalog)

    chain_slots = [ChainSlots(name=c.name, slot_count=len(c.modules)) for c in song.chains]
    try:
        letters = assign_letters(chain_slots, bindings or {})
    except LetterAssignmentError as exc:
        raise CompileError(exc.code, str(exc)) from exc

    slots: dict[str, dict] = {slot_id: _empty_slot() for slot_id in FIXED_SLOT_IDS}
    sidecar_files: dict[str, bytes] = {}

    for position, chain in enumerate(song.chains, start=1):
        letter = letters[chain.name]
        channel = chain.midi.channel if chain.midi.channel is not None else position
        for index, module in enumerate(chain.modules):
            slot_id = f"{letter.lower()}{index + 1}"
            context = f"chain {chain.name!r} module {module.key!r}"
            entry = _require_entry(catalog_by_key, module.key, context)
            cc = _module_midi_mapping(module, entry, channel, context)
            slots[slot_id] = _compile_occupied_slot(
                entry, module.params, cc, context, sample_ref=module.sample, kits=kits, media_root=media_root
            )
            sidecar_files.update(_slot_sidecars(entry, slot_id))

    for i, send in enumerate(song.sends):
        slot_id = "p1" if i == 0 else "p2"
        slot, entry = _compile_module_use(
            ModuleUse(key=send.module, params=send.params), catalog_by_key, f"send {send.name!r}"
        )
        slots[slot_id] = slot
        sidecar_files.update(_slot_sidecars(entry, slot_id))

    for i, use in enumerate(song.master):
        slot_id = f"f{i + 1}"
        slot, entry = _compile_module_use(use, catalog_by_key, f"master[{i}]")
        slots[slot_id] = slot
        sidecar_files.update(_slot_sidecars(entry, slot_id))

    for i, use in enumerate(song.mod_sources):
        slot_id = f"m{i + 1}"
        slot, entry = _compile_module_use(use, catalog_by_key, f"mod-sources[{i}]")
        slots[slot_id] = slot
        sidecar_files.update(_slot_sidecars(entry, slot_id))

    slots["s1"] = compile_router(song.chains, song.sends, letters, catalog_by_type)
    slots["s2"] = compile_transport(catalog_by_type)

    params_obj = {slot_id: slots[slot_id] for slot_id in sorted(slots)}
    files: dict[str, bytes] = {"params.json": _dumps_device_json(params_obj).encode("utf-8"), **sidecar_files}
    return CompiledPreset(directory=slug(song.name), files=files)


def build_placeholder(program: int, *, catalog: Iterable[CatalogEntry]) -> CompiledPreset:
    """One gap placeholder preset: `s1`, `s2`, and every other slot
    `-empty-`, no sidecar files (decision #50). Push calls this once per
    unused program value below the highest one in use, to keep MEC's
    Program-Change vector contiguous (docs/workflows/push.md).

    Content never depends on `program` -- every placeholder is byte-
    identical -- `program` is validated defensively and otherwise unused.
    `directory` is `""`: like a real song, the placeholder carries no
    program prefix; unlike a real song it also has no slug, so push's own
    `f"{format_program_prefix(program)}{('-' + directory) if directory
    else ''}"` naming collapses to the bare zero-padded number.
    """
    format_program_prefix(program)  # validates range; result unused, see docstring
    catalog_by_type = _catalog_by_type(catalog)
    slots: dict[str, dict] = {slot_id: _empty_slot() for slot_id in FIXED_SLOT_IDS}
    slots["s1"] = compile_router([], [], {}, catalog_by_type)
    slots["s2"] = compile_transport(catalog_by_type)
    params_obj = {slot_id: slots[slot_id] for slot_id in sorted(slots)}
    return CompiledPreset(directory="", files={"params.json": _dumps_device_json(params_obj).encode("utf-8")})
