"""Reverse mapping: an observed on-device preset back into song-file edits.

The inverse of `rig.compile.compiler.compile_song` for everything drift
covers (docs/workflows/pull.md "What drift covers"). Pure function over two
already-parsed `params.json` dicts -- no card or filesystem I/O for reading
snapshots, mirroring `rig.compile.compiler`'s own "pure function, no card
I/O" shape. Pull (Task 7) is the caller: it reads every preset, decides
which songs drifted by diffing the device's current `params.json` against
`.rig/state/last-pushed/<song>.json`, then hands both dicts to
`reverse_map_song` for translation into an edit applied to the song file.

**Diff against the stored baseline, never a recompile** (Prompt/06's
"Baseline" section, decision #17): recompiling the song fresh and diffing
against that would make a changed catalog default look like device drift,
burying real edits. `baseline` must be the last-pushed snapshot; the two
inputs are otherwise structurally identical `params.json`-shaped dicts
(`slot_id -> {"moduleType", "params", "midi-mapping", "mod-mapping"}`).

**Round-trip fidelity is the point** (Ruling 2): `doc.raw` is mutated in
place, one scalar per drifted field. Every edit is computed as a thunk first
and none of them run until every field has decoded successfully -- so a song
that turns out not to be cleanly reverse-mappable raises `ReverseMapError`
having touched `doc.raw` not at all (the brief's "Abort rule").

**Program is deliberately not reverse-mapped here.** `reverse_map_song` only
ever receives two `params.json`-shaped dicts -- it never sees a directory
name -- so it cannot observe a program change even in principle. Separately,
pull matches a preset to a song by the *recorded* directory name, never by
comparing prefixes, so a changed prefix surfaces earlier as a recorded
preset absent from the card (pull.md step 3's "warns and is skipped" path)
rather than reaching this function as drift at all.

**A slot's module identity is checked as a precondition, never edited --
by scope choice, not because the model has nowhere to put it.**
`rig.song.model`'s `ModuleSlot.key` (chain modules) and `ModuleUse.key`
(master/mod-source/send modules) are exactly the field a module swap would
land in, so this is not a missing-field case. What it would take is
re-deriving that slot's whole parameter set against the newly-observed
module -- an emission, not an edit to what moved -- and that was ruled out
of scope: the rig's owner does not edit module placement on the device.
`reverse_map_song` instead requires every slot's observed `moduleType` to
already match what the song declares before trusting any of that slot's
other drift, aborting with `ReverseMapError("MODULE_IDENTITY_DRIFT", ...)`
otherwise (see docs/decisions.md #70).

**What has no song-schema field at all cannot be edited, so it aborts.**
Two whole categories of documented "captured" drift have no YAML field to
receive them: mod-bus routing (`mod-mapping.bus` -- no song field anywhere,
`rig.song.model` has no mod-bus concept) and CC mappings on any slot besides
a chain module (`midi:` only exists on `ModuleSlot`, never on `ModuleUse` or
`Send` -- see `rig.song.model`'s own docstring). Rather than special-case
these, every raw diff between `baseline` and `observed` is required to be
*consumed* by some field handler below; whatever is left over after every
documented field has had its turn raises `ReverseMapError` naming exactly
what could not be placed. This also catches drift on the router's
compiler-pinned safety fields (`r-midi-ch`, `r-midi-pgmgate`,
`r-chin-midigate-N` -- docs/platform/routing.md "Traps") and on `s2`
transport params (decision #26: fully compiler-defaulted, no song field) --
both cases where a human should look before this tool guesses anything.

**A decoded channel or CC that `rig.song.validate` would hard-reject is
never written, even though it has a song field.** The device can hold
values the compiler itself would never have produced -- CC 1/74, channel 16,
channel 0 or anything outside a field's valid range -- because drift is
exactly "the device diverged from what the compiler would have produced".
Writing one of those into `midi: {channel:}` or a module's `midi:` block
would hand back a song file that parses but fails validation later, in a
more confusing place than where the problem was actually found; both
call sites raise `ReverseMapError("RESERVED_MIDI_VALUE_DRIFT", ...)` instead
(`check_chain_channel_writable`, `check_module_cc_writable`), reusing the
exact ranges `rig.song.validate` itself checks.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Optional

from ruamel.yaml.comments import CommentedMap

from rig.catalog.entry import CatalogEntry
from rig.compile.compiler import EMPTY_MODULE_TYPE, FIXED_SLOT_IDS
from rig.compile.router import LETTER_TO_N
from rig.compile.samples import scan_wav_folder
from rig.errors import CodedError
from rig.song.kits import KitsConfig
from rig.song.letters import ChainSlots, LetterAssignmentError, assign_letters
from rig.song.model import Chain
from rig.song.parser import SongDocument
from rig.song.validate import CHAIN_CHANNEL_RANGE, MODULE_CHANNEL_RANGE, RESERVED_CCS

_NON_SYSTEM_SLOT_IDS = [s for s in FIXED_SLOT_IDS if s not in ("s1", "s2")]


class ReverseMapError(CodedError):
    """A song cannot be cleanly reverse-mapped; `doc.raw` is left untouched.

    `code` identifies which rule fired, so callers can report this the same
    way as a compile failure.
    """


@dataclass(frozen=True)
class FieldChange:
    """One song-file edit `reverse_map_song` applied, for callers that want
    to log or summarise drift (e.g. a pull request body) without re-parsing
    the YAML diff themselves."""

    field: str
    new: object


@dataclass(frozen=True)
class _RawDiff:
    slot_id: str
    path: tuple
    old: object
    new: object


def clean_number(value):
    """Round device float noise away and prefer a plain int when the result
    is whole, matching how numbers already read in every song fixture
    (`output-gain: 90`, not `90.0`)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return value
    rounded = round(float(value), 6)
    return int(rounded) if rounded.is_integer() else rounded


def invert_cc(cc_map: dict) -> dict[str, int]:
    """`{key_str: [param_id, ...]}` -> `{param_id: key}`. Each parameter has
    at most one CC mapping at a time, so this is a clean inversion."""
    inverted: dict[str, int] = {}
    for key_str, ids in cc_map.items():
        key = int(key_str)
        for pid in ids:
            inverted[pid] = key
    return inverted


def check_chain_channel_writable(channel: int, context: str) -> None:
    """A chain's note channel is a hard validation error outside 0-15
    (`rig.song.validate.CHAIN_CHANNEL_RANGE`, `docs/schema.md` "Channel 16 is
    forbidden"). The device can hold a value validation would reject -- the
    whole premise of drift is that it can diverge from anything the compiler
    would ever have produced -- so writing it straight into `midi: {channel:}`
    would hand the musician a song file that fails validation later, in a
    more confusing place than where the actual problem was found."""
    if channel not in CHAIN_CHANNEL_RANGE:
        raise ReverseMapError(
            "RESERVED_MIDI_VALUE_DRIFT", f"{context}: chain channel {channel} is reserved or out of range"
        )


def check_module_cc_writable(channel: int, cc: int, context: str) -> None:
    """Same guard as `check_chain_channel_writable`, for a module `midi:`
    entry: CC 1/74 are hardwired per-chain modulation sources
    (`rig.song.validate.RESERVED_CCS`), and a module mapping's channel is a
    hard error outside 1-15 (`rig.song.validate.MODULE_CHANNEL_RANGE`) --
    channel 0 is never emitted by `ctlin` and channel 16 is reserved for
    Program Change."""
    if cc in RESERVED_CCS:
        raise ReverseMapError("RESERVED_MIDI_VALUE_DRIFT", f"{context}: CC {cc} is reserved")
    if channel not in MODULE_CHANNEL_RANGE:
        raise ReverseMapError(
            "RESERVED_MIDI_VALUE_DRIFT", f"{context}: module CC channel {channel} is reserved or out of range"
        )


def _raw_diffs(baseline: dict, observed: dict) -> list[_RawDiff]:
    """Every scalar-level difference between two `params.json` dicts, as a
    flat list of `(slot_id, path)` diffs. `reverse_map_song` consumes these
    one field handler at a time; whatever is left unconsumed is drift with
    nowhere in the schema to go (see module docstring)."""
    diffs: list[_RawDiff] = []
    for slot_id in set(baseline) | set(observed):
        b = baseline.get(slot_id, {})
        o = observed.get(slot_id, {})

        b_type = b.get("moduleType", EMPTY_MODULE_TYPE)
        o_type = o.get("moduleType", EMPTY_MODULE_TYPE)
        if b_type != o_type:
            diffs.append(_RawDiff(slot_id, ("moduleType",), b_type, o_type))

        b_params, o_params = b.get("params", {}), o.get("params", {})
        for pid in set(b_params) | set(o_params):
            bv, ov = b_params.get(pid), o_params.get(pid)
            if bv != ov:
                diffs.append(_RawDiff(slot_id, ("params", pid), bv, ov))

        b_cc = invert_cc(b.get("midi-mapping", {}).get("cc", {}))
        o_cc = invert_cc(o.get("midi-mapping", {}).get("cc", {}))
        for pid in set(b_cc) | set(o_cc):
            bv, ov = b_cc.get(pid), o_cc.get(pid)
            if bv != ov:
                diffs.append(_RawDiff(slot_id, ("midi-cc", pid), bv, ov))

        b_bus = b.get("mod-mapping", {}).get("bus", {})
        o_bus = o.get("mod-mapping", {}).get("bus", {})
        if b_bus != o_bus:
            diffs.append(_RawDiff(slot_id, ("mod-bus",), b_bus, o_bus))

    return diffs


# --- raw-document mutation helpers ------------------------------------------
#
# Every helper below either reads an already-existing node (safe at decode
# time) or is wrapped in a zero-arg thunk deferred to the apply phase, so
# nothing here runs until `reverse_map_song` has decoded every field without
# error.


def _ensure_map(parent: dict, key: str) -> dict:
    existing = parent.get(key)
    if not isinstance(existing, dict):
        existing = CommentedMap()
        parent[key] = existing
    return existing


def _list_item_body(seq, index: int, key: str) -> dict:
    """The mutable body mapping for a module-use list entry (a chain's
    `modules:`, or `master:`/`mod-sources:`), which the parser accepts as
    either a bare module key or a single-key `{key: body}` mapping
    (`rig.song.parser._split_module_use_item`). Upgrades a bare entry to the
    mapping form in place when a field needs to be written into it."""
    item = seq[index]
    if isinstance(item, str):
        new_item = CommentedMap()
        body = CommentedMap()
        new_item[key] = body
        seq[index] = new_item
        return body
    body = item.get(key)
    if not isinstance(body, dict):
        body = CommentedMap()
        item[key] = body
    return body


def _make_set_nested(parent: dict, subkey: str, field: str, value) -> Callable[[], None]:
    def _apply():
        _ensure_map(parent, subkey)[field] = value

    return _apply


def _make_set_module_field(seq, index: int, key: str, field: str, value) -> Callable[[], None]:
    def _apply():
        _list_item_body(seq, index, key)[field] = value

    return _apply


def _make_del_module_field(seq, index: int, key: str, field: str) -> Callable[[], None]:
    def _apply():
        item = seq[index]
        if isinstance(item, dict):
            body = item.get(key)
            if isinstance(body, dict) and field in body:
                del body[field]

    return _apply


def _make_set_module_nested(seq, index: int, key: str, subkey: str, field: str, value) -> Callable[[], None]:
    def _apply():
        body = _list_item_body(seq, index, key)
        _ensure_map(body, subkey)[field] = value

    return _apply


def _make_del_module_nested(seq, index: int, key: str, subkey: str, field: str) -> Callable[[], None]:
    def _apply():
        item = seq[index]
        if isinstance(item, dict):
            body = item.get(key)
            if isinstance(body, dict):
                sub = body.get(subkey)
                if isinstance(sub, dict) and field in sub:
                    del sub[field]
                    if not sub:
                        # An empty `midi: {}` left behind reads as noise --
                        # drop the now-pointless container along with it.
                        del body[subkey]

    return _apply


def _make_set_send_field(sends_map, send_name: str, field: str, value) -> Callable[[], None]:
    def _apply():
        sends_map[send_name][field] = value

    return _apply


def decode_sample(
    samp_source, samp_select, kits: Optional[KitsConfig], media_root: Optional[Path], context: str
) -> Optional[str]:
    """`samp_source`/`samp_select` -> `<alias>/<file>`, or `None` for
    "nothing selected" (docs/platform/samples.md, docs/media.md). Inverts
    the position formula against the repo folder's *current* listing --
    safe because push keeps the device and repo folders in lockstep
    (Prompt/06 "Samples").
    """
    samp_source = int(samp_source)
    if samp_source in (0, -1):
        return None
    if kits is None or media_root is None:
        raise ReverseMapError(
            "SAMPLE_RESOLUTION_UNAVAILABLE", f"{context}: sample decode needs both 'kits' and 'media_root'"
        )
    if 1 <= samp_source <= 24:
        alias = next((a for a, n in kits.aliases.items() if n == samp_source), None)
        if alias is None:
            raise ReverseMapError(
                "UNKNOWN_KIT_NUMBER", f"{context}: kit-{samp_source} has no alias recorded in .rig/kits.yaml"
            )
        folder = kits.kit_dir(media_root, alias)
    elif samp_source in (25, 26, 27):
        # docs/schema.md's `sample:` field only expresses the
        # <kit-alias>/<filename> form (rig.compile.samples's own docstring:
        # "the song schema has no field that reaches them") -- the shared
        # samples/loops/synths folders have no alias, so there is no YAML
        # this can decode to. Named and loud rather than a silent drop.
        raise ReverseMapError(
            "SAMPLE_FOLDER_UNREPRESENTABLE",
            f"{context}: samp_source {samp_source} selects the shared samples/loops/synths folder, "
            "which has no kit-alias form in the song schema",
        )
    else:
        raise ReverseMapError(
            "SAMPLE_SOURCE_OUT_OF_RANGE", f"{context}: samp_source {samp_source} is outside the documented range"
        )

    wav_names, findings = scan_wav_folder(folder, context)
    errors = [f for f in findings if f.code != "IGNORED_NON_WAV_FILE"]
    if errors:
        raise ReverseMapError("SAMPLE_FOLDER_INVALID", "; ".join(f.message for f in errors))
    n = len(wav_names)
    if n == 0:
        raise ReverseMapError("SAMPLE_FOLDER_EMPTY", f"{context}: {folder} has no .wav files to index into")
    index = int((float(samp_select) / 100.0) * (n - 0.05))
    index = max(0, min(n - 1, index))
    return f"{alias}/{wav_names[index]}"


def _match_use_param_diffs(
    edits: list, changes: list, seq, index: int, key: str, entry: CatalogEntry, remaining: dict, slot_id: str,
    *, skip_ids: frozenset = frozenset(),
) -> None:
    """`params.<paramId>` -> parameter slug, for a module-use list entry
    (chain module, `master:`, or `mod-sources:` item) -- decision #12's
    slug/id pairs, inverted."""
    for spec in entry.params:
        if spec.id in skip_ids:
            continue
        d = remaining.pop((slot_id, ("params", spec.id)), None)
        if d is None:
            continue
        value = clean_number(d.new)
        edits.append(_make_set_module_field(seq, index, key, spec.name, value))
        changes.append(FieldChange(f"{slot_id}.{spec.name}", value))


def _match_send_param_diffs(
    edits: list, changes: list, sends_map, send_name: str, entry: CatalogEntry, remaining: dict, slot_id: str
) -> None:
    for spec in entry.params:
        d = remaining.pop((slot_id, ("params", spec.id)), None)
        if d is None:
            continue
        value = clean_number(d.new)
        edits.append(_make_set_send_field(sends_map, send_name, spec.name, value))
        changes.append(FieldChange(f"{slot_id}.{spec.name}", value))


def _match_chain_mix_gain_diff(
    edits: list, changes: list, remaining: dict, chain_raw, chain_index: int, *, param: str, field: str
) -> None:
    """One `mix:` gain that is a straight number with no further decoding --
    `input-gain` and `output-gain` differ only in which s1 parameter carries
    them and which field receives them."""
    d = remaining.pop(("s1", ("params", param)), None)
    if d is None:
        return
    value = clean_number(d.new)
    edits.append(_make_set_nested(chain_raw, "mix", field, value))
    changes.append(FieldChange(f"chains[{chain_index}].mix.{field}", value))


def _match_chain_field_diffs(
    edits: list,
    changes: list,
    remaining: dict,
    chain_raw,
    chain_index: int,
    chain: Chain,
    *,
    n: int,
    s1_observed: dict,
    effective_channel: int,
) -> int:
    """Every chain-level field: note channel, the two mix gains, and the
    balance/width pair. Returns the chain's channel, which the module loop
    needs afterwards to decide whether a CC key can use the bare-number
    shorthand -- drift may have just changed it.

    Balance and width stay inline rather than going through
    `_match_chain_mix_gain_diff`: they are one derived pair recomputed from
    both observed pan values together, not two independent numbers.
    """
    d = remaining.pop(("s1", ("params", f"r-chin-midich-{n}")), None)
    if d is not None:
        effective_channel = int(d.new)
        check_chain_channel_writable(effective_channel, f"chains[{chain_index}] ({chain.name!r})")
        edits.append(_make_set_nested(chain_raw, "midi", "channel", effective_channel))
        changes.append(FieldChange(f"chains[{chain_index}].midi.channel", effective_channel))

    _match_chain_mix_gain_diff(
        edits, changes, remaining, chain_raw, chain_index, param=f"r-chin-l-gain-{n}", field="input-gain"
    )
    _match_chain_mix_gain_diff(
        edits, changes, remaining, chain_raw, chain_index, param=f"r-chout-gain-{n}", field="output-gain"
    )

    dl = remaining.pop(("s1", ("params", f"r-chout-l-pan-{n}")), None)
    dr = remaining.pop(("s1", ("params", f"r-chout-r-pan-{n}")), None)
    if dl is not None or dr is not None:
        l_pan = s1_observed[f"r-chout-l-pan-{n}"]
        r_pan = s1_observed[f"r-chout-r-pan-{n}"]
        balance = clean_number(100.0 * (float(l_pan) + float(r_pan)) / 2.0)
        width = clean_number(100.0 * (float(r_pan) - float(l_pan)))
        edits.append(_make_set_nested(chain_raw, "mix", "balance", balance))
        edits.append(_make_set_nested(chain_raw, "mix", "width", width))
        changes.append(FieldChange(f"chains[{chain_index}].mix.balance", balance))
        changes.append(FieldChange(f"chains[{chain_index}].mix.width", width))

    return effective_channel


def reverse_map_song(
    doc: SongDocument,
    *,
    baseline: dict,
    observed: dict,
    catalog: Iterable[CatalogEntry],
    kits: Optional[KitsConfig] = None,
    media_root: Optional[Path] = None,
    bindings: Optional[dict[str, str]] = None,
) -> list[FieldChange]:
    """Edit `doc.raw` in place to reflect device drift between `baseline`
    (the last-pushed snapshot) and `observed` (the device's current
    `params.json`), touching only the fields that actually differ.

    Raises `ReverseMapError` -- and leaves `doc.raw` byte-identical to how
    it was passed in -- when the song cannot be cleanly reverse-mapped: an
    unknown module, a slot whose occupant no longer matches what the song
    declares (module placement changed -- out of scope by deliberate choice,
    not a missing field; see the module docstring's "A slot's module
    identity is checked as a precondition" paragraph), or any drift left
    over once every documented field has had a chance to claim it.

    Assumes `doc.song` last compiled successfully (mirrors `compile_song`'s
    own assumption that `validate_song` already ran) -- capacity limits are
    not re-checked here.
    """
    song = doc.song
    catalog_by_key = {e.key: e for e in catalog}

    def require_entry(key: str, context: str) -> CatalogEntry:
        entry = catalog_by_key.get(key)
        if entry is None:
            raise ReverseMapError("UNKNOWN_MODULE", f"{context}: module {key!r} is not in the catalog")
        return entry

    chain_slots = [ChainSlots(name=c.name, slot_count=len(c.modules)) for c in song.chains]
    try:
        letters = assign_letters(chain_slots, bindings or {})
    except LetterAssignmentError as exc:
        raise ReverseMapError(exc.code, str(exc)) from exc

    # Every fixed slot's expected occupant: the song's declared module, or
    # -empty- where nothing is declared.
    slot_plan: dict[str, CatalogEntry] = {}
    for chain_index, chain in enumerate(song.chains):
        letter = letters[chain.name]
        for module_index, module in enumerate(chain.modules):
            slot_id = f"{letter.lower()}{module_index + 1}"
            slot_plan[slot_id] = require_entry(module.key, f"chain {chain.name!r} module {module.key!r}")
    for i, send in enumerate(song.sends):
        slot_plan["p1" if i == 0 else "p2"] = require_entry(send.module, f"send {send.name!r}")
    for i, use in enumerate(song.master):
        slot_plan[f"f{i + 1}"] = require_entry(use.key, f"master[{i}]")
    for i, use in enumerate(song.mod_sources):
        slot_plan[f"m{i + 1}"] = require_entry(use.key, f"mod-sources[{i}]")

    remaining: dict[tuple, _RawDiff] = {(d.slot_id, d.path): d for d in _raw_diffs(baseline, observed)}

    # Module-identity precondition: every occupied/unoccupied slot must
    # physically hold what the song says it does before any of that slot's
    # parameter diffs can be trusted to belong to the right module.
    for slot_id in _NON_SYSTEM_SLOT_IDS:
        entry = slot_plan.get(slot_id)
        expected_type = entry.module_type if entry is not None else EMPTY_MODULE_TYPE
        observed_type = observed.get(slot_id, {}).get("moduleType", EMPTY_MODULE_TYPE)
        if observed_type != expected_type:
            raise ReverseMapError(
                "MODULE_IDENTITY_DRIFT",
                f"slot {slot_id!r} now holds {observed_type!r}; song {song.name!r} expects "
                f"{expected_type!r} -- module placement changes are not reverse-mappable here "
                "(patch applier, not a song emitter)",
            )
        remaining.pop((slot_id, ("moduleType",)), None)

    edits: list[Callable[[], None]] = []
    changes: list[FieldChange] = []

    s1_observed = observed.get("s1", {}).get("params", {})

    for chain_index, chain in enumerate(song.chains):
        letter = letters[chain.name]
        n = LETTER_TO_N[letter]
        chain_raw = doc.raw["chains"][chain_index]
        position = chain_index + 1
        effective_channel = chain.midi.channel if chain.midi.channel is not None else position

        effective_channel = _match_chain_field_diffs(
            edits, changes, remaining, chain_raw, chain_index, chain,
            n=n, s1_observed=s1_observed, effective_channel=effective_channel,
        )

        modules_seq = chain_raw["modules"]
        for module_index, module in enumerate(chain.modules):
            slot_id = f"{letter.lower()}{module_index + 1}"
            entry = slot_plan[slot_id]
            sampler = {"samp_source", "samp_select"} <= {p.id for p in entry.params}
            skip_ids = frozenset({"samp_source", "samp_select"}) if sampler else frozenset()

            _match_use_param_diffs(
                edits, changes, modules_seq, module_index, module.key, entry, remaining, slot_id, skip_ids=skip_ids
            )

            d = remaining.pop(("s1", ("params", f"r-notethru-{slot_id}")), None)
            if d is not None:
                value = bool(d.new)
                edits.append(_make_set_module_field(modules_seq, module_index, module.key, "note-thru", value))
                changes.append(FieldChange(f"{slot_id}.note-thru", value))

            for send_index, prefix in ((0, "r-sendP1"), (1, "r-sendP2")):
                d = remaining.pop(("s1", ("params", f"{prefix}-{slot_id}")), None)
                if d is None:
                    continue
                if send_index >= len(song.sends):
                    raise ReverseMapError(
                        "SEND_TARGET_UNDECLARED",
                        f"{slot_id}: send amount changed for {prefix} but 'sends:' has no matching entry",
                    )
                send_name = song.sends[send_index].name
                value = clean_number(d.new)
                edits.append(
                    _make_set_module_nested(modules_seq, module_index, module.key, "send", send_name, value)
                )
                changes.append(FieldChange(f"{slot_id}.send.{send_name}", value))

            if sampler:
                d_source = remaining.pop((slot_id, ("params", "samp_source")), None)
                d_select = remaining.pop((slot_id, ("params", "samp_select")), None)
                if d_source is not None or d_select is not None:
                    obs_params = observed[slot_id]["params"]
                    context = f"{slot_id} ({module.key})"
                    new_sample = decode_sample(
                        obs_params.get("samp_source", 0), obs_params.get("samp_select", 0.0), kits, media_root, context
                    )
                    if new_sample is None:
                        edits.append(_make_del_module_field(modules_seq, module_index, module.key, "sample"))
                    else:
                        edits.append(
                            _make_set_module_field(modules_seq, module_index, module.key, "sample", new_sample)
                        )
                    changes.append(FieldChange(f"{slot_id}.sample", new_sample))

            for spec in entry.params:
                d = remaining.pop((slot_id, ("midi-cc", spec.id)), None)
                if d is None:
                    continue
                if d.new is None:
                    edits.append(
                        _make_del_module_nested(modules_seq, module_index, module.key, "midi", spec.name)
                    )
                    changes.append(FieldChange(f"{slot_id}.midi.{spec.name}", None))
                    continue
                key = int(d.new)
                channel, cc = divmod(key, 128)
                check_module_cc_writable(channel, cc, f"{slot_id}.midi.{spec.name}")
                # Shorthand only when the decoded channel matches the
                # chain's own resolved channel, and never on an omni chain
                # (Prompt/06 "CC keys"): a bare CC number on an omni chain
                # would be ambiguous about which channel it came from.
                if effective_channel != 0 and channel == effective_channel:
                    value = cc
                else:
                    value = {"channel": channel, "cc": cc}
                edits.append(_make_set_module_nested(modules_seq, module_index, module.key, "midi", spec.name, value))
                changes.append(FieldChange(f"{slot_id}.midi.{spec.name}", value))

    sends_map = doc.raw.get("sends")
    for i, send in enumerate(song.sends):
        slot_id = "p1" if i == 0 else "p2"
        _match_send_param_diffs(edits, changes, sends_map, send.name, slot_plan[slot_id], remaining, slot_id)

    master_seq = doc.raw.get("master")
    for i, use in enumerate(song.master):
        slot_id = f"f{i + 1}"
        _match_use_param_diffs(edits, changes, master_seq, i, use.key, slot_plan[slot_id], remaining, slot_id)

    mod_seq = doc.raw.get("mod-sources")
    for i, use in enumerate(song.mod_sources):
        slot_id = f"m{i + 1}"
        _match_use_param_diffs(edits, changes, mod_seq, i, use.key, slot_plan[slot_id], remaining, slot_id)

    if remaining:
        details = "; ".join(
            f"{slot_id} {path}: {d.old!r} -> {d.new!r}" for (slot_id, path), d in sorted(remaining.items())
        )
        raise ReverseMapError(
            "UNSUPPORTED_DRIFT", f"drift with no song-schema field to receive it: {details}"
        )

    for apply in edits:
        apply()

    return changes
