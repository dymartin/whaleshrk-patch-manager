"""Adoption: mint a song file from a card preset with no recorded song.

A separate emitter, not a special case of `rig.pull.reverse`
(docs/workflows/pull.md "Adoption"): the reverse mapper edits an existing
song's already-parsed document field by field; this builds a brand-new one
from nothing but an observed `params.json`; the two share almost no code
path. What they do share -- number cleanup, the reserved-CC/channel guards,
sample-selection decoding, the program-prefix decoder -- is imported
straight from `rig.pull.reverse` rather than re-derived, since both modules
live in the same package and the rules are identical (Ruling: reuse existing
abstractions). Those shared names carry no leading underscore precisely
because this module imports them: they are `reverse`'s contract with
`adopt`, not its internals.

Every field this module writes is documented in docs/workflows/pull.md
"Adoption"; anything with no schema field to receive it (mod-bus routing, a
CC mapping outside a chain module) aborts the same way undecodable drift
does in `rig.pull.reverse` -- named and loud, never silently dropped.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq

from rig.catalog.entry import CatalogEntry
from rig.catalog.slugs import slug
from rig.compile.compiler import EMPTY_MODULE_TYPE
from rig.compile.router import LETTER_TO_N
from rig.pull.reverse import (
    ReverseMapError,
    check_chain_channel_writable,
    check_module_cc_writable,
    clean_number,
    decode_program_prefix,
    decode_sample,
    invert_cc,
)
from rig.song.kits import KitsConfig
from rig.song.letters import CAPACITY, CHAIN_LETTERS
from rig.song.parser import SongDocument, parse_song

# Matches rig.song.parser's own ruamel configuration (see that module's
# docstring): a fresh document has no existing formatting to preserve, but
# it should still come out indented the way every other song file is.
_yaml = YAML(typ="rt")
_yaml.preserve_quotes = True
_yaml.indent(mapping=2, sequence=4, offset=2)


@dataclass(frozen=True)
class AdoptedSong:
    """One minted song, ready for `rig.pull.runner` to write and commit."""

    song_id: str  # filename stem == branch slug
    program: int
    text: str  # dumped YAML, songs/<song_id>.yaml content
    doc: SongDocument
    bindings: dict[str, str]  # chain name -> letter, for .rig/state/chains/<song_id>.json


def _preset_display_name(directory: str) -> str:
    """Strip the compiler-shaped numeric prefix (`docs/schema.md` "Program"),
    if the directory looks like one, leaving whatever the device actually
    called the preset. A foreign directory with no recognisable prefix is
    used whole -- there is nothing else to call it."""
    if decode_program_prefix(directory) is not None and len(directory) > 3 and directory[3] == "-":
        return directory[4:]
    return directory


def _next_free_program(used: set[int]) -> int:
    for candidate in range(128):
        if candidate not in used:
            return candidate
    raise ReverseMapError("NO_FREE_PROGRAM", "every program value 0-127 is already in use")


def _dedupe(base: str, counts: dict[str, int]) -> str:
    """Collisions take -2, -3 (docs/workflows/pull.md "Adoption")."""
    counts[base] = counts.get(base, 0) + 1
    n = counts[base]
    return base if n == 1 else f"{base}-{n}"


def _module_short_name(entry: CatalogEntry) -> str:
    """The catalog key with `@source` dropped -- `rings@orhack` -> `rings`."""
    return entry.key.split("@", 1)[0]


def _require_entry(catalog_by_type: dict[str, CatalogEntry], module_type: str, context: str) -> CatalogEntry:
    entry = catalog_by_type.get(module_type)
    if entry is None:
        raise ReverseMapError("UNKNOWN_MODULE", f"{context}: moduleType {module_type!r} is not in the catalog")
    return entry


def _reject_unrepresentable(slot: dict, context: str) -> None:
    """Mod-bus routing and a CC mapping outside a chain module both have no
    song-schema field to receive them (docs/workflows/pull.md "What drift
    covers") -- callers for p1/p2/f1-f3/m1-m3 (never chain modules, which do
    have `midi:`) use this to refuse rather than silently drop them."""
    if slot.get("mod-mapping", {}).get("bus", {}):
        raise ReverseMapError("MOD_BUS_UNREPRESENTABLE", f"{context}: mod-bus routing has no song-schema field")
    if slot.get("midi-mapping", {}).get("cc", {}):
        raise ReverseMapError(
            "CC_MAPPING_UNREPRESENTABLE", f"{context}: a CC mapping here has no song-schema field"
        )


def _decode_params(entry: CatalogEntry, params: dict, *, skip_ids: frozenset = frozenset()) -> CommentedMap:
    """Every parameter that differs from its catalog default (decision #13's
    inverse: an adopted song stays short by omitting what would compile back
    to the same value unmentioned)."""
    body = CommentedMap()
    for spec in entry.params:
        if spec.id in skip_ids:
            continue
        value = clean_number(params.get(spec.id, spec.default))
        if value != clean_number(spec.default):
            body[spec.name] = value
    return body


def _decode_use_slot(
    slot_id: str, observed: dict, catalog_by_type: dict[str, CatalogEntry], context: str
) -> tuple[CatalogEntry, CommentedMap]:
    """A send/master/mod-source slot, assumed occupied (see
    `_decode_use_group`): the entry and its non-default param body.
    `ModuleUse` has no `midi:`/`send:`/`sample:` (rig.song.model), so those
    raw fields are checked and refused rather than silently dropped."""
    slot = observed[slot_id]
    entry = _require_entry(catalog_by_type, slot.get("moduleType", EMPTY_MODULE_TYPE), context)
    _reject_unrepresentable(slot, context)
    return entry, _decode_params(entry, slot.get("params", {}))


def _contiguous_occupied(slot_ids: list[str], observed: dict, label: str) -> list[str]:
    """Every occupied slot in `slot_ids` (fixed order), required to be a
    contiguous prefix. The song schema represents "N modules used" as
    exactly N list entries -- there is no way to write "skip this one" in
    the middle -- so an empty slot sitting before an occupied one has no
    index that would keep the occupied one's identity aligned on recompile.
    Raised rather than silently shifting it to the wrong slot."""
    occupied = [sid for sid in slot_ids if observed.get(sid, {}).get("moduleType", EMPTY_MODULE_TYPE) != EMPTY_MODULE_TYPE]
    if occupied != slot_ids[: len(occupied)]:
        raise ReverseMapError(
            "UNREPRESENTABLE_SLOT_GAP",
            f"{label}: occupied slot(s) {occupied} are not a contiguous prefix of {slot_ids} -- "
            "the song schema cannot represent an empty slot before an occupied one",
        )
    return occupied


def _decode_use_group(
    slot_ids: list[str], observed: dict, catalog_by_type: dict[str, CatalogEntry], label: str
) -> list[tuple[CatalogEntry, CommentedMap]]:
    occupied = _contiguous_occupied(slot_ids, observed, label)
    return [_decode_use_slot(sid, observed, catalog_by_type, f"{label} slot {sid!r}") for sid in occupied]


def _as_item(key: str, body: CommentedMap):
    return key if not body else CommentedMap({key: body})


def _decode_chain(
    letter: str,
    position: int,
    observed: dict,
    catalog_by_type: dict[str, CatalogEntry],
    kits: Optional[KitsConfig],
    media_root: Optional[Path],
    send_names: list[Optional[str]],
    used_names: dict[str, int],
) -> Optional[tuple[CommentedMap, str, str]]:
    """One chain letter's worth of the emitted YAML: `(chain_raw, name,
    letter)`, or `None` if every slot in the letter is `-empty-` (empty
    chains are omitted, not named -- docs/workflows/pull.md "Adoption")."""
    n = LETTER_TO_N[letter]
    slot_ids = [f"{letter.lower()}{i}" for i in range(1, CAPACITY[letter] + 1)]
    if all(observed.get(sid, {}).get("moduleType", EMPTY_MODULE_TYPE) == EMPTY_MODULE_TYPE for sid in slot_ids):
        return None
    occupied = _contiguous_occupied(slot_ids, observed, f"chain letter {letter}")

    s1 = observed.get("s1", {}).get("params", {})
    # Channel is decoded up front -- module CC decode below needs it to
    # choose between the implied form (bare CC number, same convention
    # `rig.pull.reverse` uses) and the explicit `{channel, cc}` form.
    observed_channel = int(s1.get(f"r-chin-midich-{n}", position))

    modules_raw = CommentedSeq()
    first_entry: Optional[CatalogEntry] = None

    for sid in occupied:
        slot = observed[sid]
        context = f"slot {sid!r}"
        entry = _require_entry(catalog_by_type, slot.get("moduleType", EMPTY_MODULE_TYPE), context)
        if first_entry is None:
            first_entry = entry
        if slot.get("mod-mapping", {}).get("bus", {}):
            raise ReverseMapError("MOD_BUS_UNREPRESENTABLE", f"{context}: mod-bus routing has no song-schema field")

        sampler = {"samp_source", "samp_select"} <= {p.id for p in entry.params}
        skip_ids = frozenset({"samp_source", "samp_select"}) if sampler else frozenset()
        body = _decode_params(entry, slot.get("params", {}), skip_ids=skip_ids)

        # note-thru
        if int(s1.get(f"r-notethru-{sid}", 0)):
            body["note-thru"] = True

        # send amounts -- silently skipped if the corresponding P1/P2 slot
        # itself is unoccupied (nothing declared to name it): the device
        # value would route to silence either way, so there is nothing
        # meaningful to write, unlike reverse-mapping an existing song where
        # an already-declared 'sends:' entry going missing is a real error.
        send_body = CommentedMap()
        for index, prefix in ((0, "r-sendP1"), (1, "r-sendP2")):
            key = f"{prefix}-{sid}"
            if key not in s1:
                continue
            amount = clean_number(s1[key])
            if amount and index < len(send_names) and send_names[index] is not None:
                send_body[send_names[index]] = amount
        if send_body:
            body["send"] = send_body

        # CC mapping -- bare CC number only when the decoded channel matches
        # the chain's own resolved channel, and never on an omni chain (same
        # rule and rationale as rig.pull.reverse: a bare number on an omni
        # chain would be ambiguous about which channel it came from).
        cc_map = invert_cc(slot.get("midi-mapping", {}).get("cc", {}))
        if cc_map:
            midi_body = CommentedMap()
            id_to_name = {p.id: p.name for p in entry.params}
            for pid, key in cc_map.items():
                name = id_to_name.get(pid)
                if name is None:
                    continue
                channel, cc = divmod(key, 128)
                check_module_cc_writable(channel, cc, f"{context}.midi.{name}")
                if observed_channel != 0 and channel == observed_channel:
                    midi_body[name] = cc
                else:
                    midi_body[name] = CommentedMap({"channel": channel, "cc": cc})
            if midi_body:
                body["midi"] = midi_body

        # sample selection
        if sampler:
            new_sample = decode_sample(
                slot["params"].get("samp_source", 0), slot["params"].get("samp_select", 0.0),
                kits, media_root, f"{context} ({entry.key})",
            )
            if new_sample is not None:
                body["sample"] = new_sample

        modules_raw.append(_as_item(entry.key, body))

    if first_entry is None:
        # The all-empty chain is rejected earlier, so a chain reaching here
        # always has at least one occupied slot. Raising keeps the failure
        # legible (and survives `python -O`) if that ever stops holding.
        raise ReverseMapError("INTERNAL_ERROR", f"{context}: chain has no occupied slot to name")
    name = _dedupe(slug(_module_short_name(first_entry)), used_names)

    chain_raw = CommentedMap()
    chain_raw["name"] = name

    l_pan = float(s1.get(f"r-chin-l-pan-{n}", 0.0))
    guitar = abs(l_pan - 0.5) < 1e-9
    if guitar:
        chain_raw["input"] = CommentedMap({"guitar": True})

    if observed_channel != position:
        check_chain_channel_writable(observed_channel, f"chain {name!r}")
        chain_raw["midi"] = CommentedMap({"channel": observed_channel})

    mix_body = CommentedMap()
    if guitar:
        input_gain = clean_number(s1.get(f"r-chin-l-gain-{n}", 100.0))
        if input_gain != 100:
            mix_body["input-gain"] = input_gain
    output_gain = clean_number(s1.get(f"r-chout-gain-{n}", 100.0))
    if output_gain != 100:
        mix_body["output-gain"] = output_gain
    l_out = float(s1.get(f"r-chout-l-pan-{n}", 0.5))
    r_out = float(s1.get(f"r-chout-r-pan-{n}", 0.5))
    balance = clean_number(100.0 * (l_out + r_out) / 2.0)
    width = clean_number(100.0 * (r_out - l_out))
    if balance != 50:
        mix_body["balance"] = balance
    if width != 100:
        mix_body["width"] = width
    if mix_body:
        chain_raw["mix"] = mix_body

    chain_raw["modules"] = modules_raw
    return chain_raw, name, letter


def adopt_preset(
    directory: str,
    observed: dict,
    *,
    catalog: Iterable[CatalogEntry],
    kits: Optional[KitsConfig] = None,
    media_root: Optional[Path] = None,
    existing_song_ids: Iterable[str] = (),
    used_programs: Iterable[int] = (),
) -> AdoptedSong:
    """Mint a `Song` from one unrecorded card preset.

    Raises `ReverseMapError` (the same exception `rig.pull.reverse` uses --
    same shape, same intent: named and loud rather than a guess) if any
    occupied slot cannot be represented: an unknown module, mod-bus routing,
    a CC mapping with no schema field, a reserved CC/channel, or a sampler
    pointed at the shared samples/loops/synths folders.
    """
    catalog_by_type = {e.module_type: e for e in catalog}
    existing = set(existing_song_ids)
    used = set(used_programs)

    program = decode_program_prefix(directory)
    if program is None or program in used:
        program = _next_free_program(used)

    display_name = _preset_display_name(directory)
    song_id = _dedupe(slug(display_name) or "preset", _seed_counts(existing))

    # --- sends (p1, p2) -------------------------------------------------
    send_names: list[Optional[str]] = [None, None]
    send_counts: dict[str, int] = {}
    sends_raw = CommentedMap()
    for i, (entry, body) in enumerate(_decode_use_group(["p1", "p2"], observed, catalog_by_type, "sends")):
        name = _dedupe(slug(_module_short_name(entry)), send_counts)
        send_names[i] = name
        entry_body = CommentedMap()
        entry_body["module"] = entry.key
        entry_body.update(body)
        sends_raw[name] = entry_body

    # --- chains -----------------------------------------------------------
    chains_raw = CommentedSeq()
    bindings: dict[str, str] = {}
    chain_name_counts: dict[str, int] = {}
    position = 0
    for letter in CHAIN_LETTERS:
        decoded = _decode_chain(
            letter, position + 1, observed, catalog_by_type, kits, media_root, send_names, chain_name_counts
        )
        if decoded is None:
            continue
        position += 1
        chain_raw, name, bound_letter = decoded
        bindings[name] = bound_letter
        chains_raw.append(chain_raw)

    # --- master (f1-f3) -----------------------------------------------------
    master_raw = CommentedSeq()
    for entry, body in _decode_use_group(["f1", "f2", "f3"], observed, catalog_by_type, "master"):
        master_raw.append(_as_item(entry.key, body))

    # --- mod-sources (m1-m3) -------------------------------------------------
    mod_sources_raw = CommentedSeq()
    for entry, body in _decode_use_group(["m1", "m2", "m3"], observed, catalog_by_type, "mod-sources"):
        mod_sources_raw.append(_as_item(entry.key, body))

    doc_raw = CommentedMap()
    doc_raw["song"] = display_name
    doc_raw["program"] = program
    if sends_raw:
        doc_raw["sends"] = sends_raw
    if master_raw:
        doc_raw["master"] = master_raw
    if mod_sources_raw:
        doc_raw["mod-sources"] = mod_sources_raw
    doc_raw["chains"] = chains_raw

    buf = io.StringIO()
    _yaml.dump(doc_raw, buf)
    text = buf.getvalue()

    doc = parse_song(text, source=f"<adopted {directory}>")
    return AdoptedSong(song_id=song_id, program=program, text=text, doc=doc, bindings=bindings)


def _seed_counts(existing: set[str]) -> dict[str, int]:
    """Seed `_dedupe`'s counter so a fresh slug colliding with an existing
    song id starts its own suffix at -2 rather than overwriting it."""
    return {name: 1 for name in existing}
