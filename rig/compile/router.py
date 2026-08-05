"""Compiles the fixed `s1` (routers/hybrid) and `s2` (clocks/transport)
system slots.

Both slots are structural -- module identity is fixed regardless of song
content (decision #25) -- but `s1`'s parameter block is the compile target
for every chain's `input:`, `midi: {channel}`, `mix:` and per-module
`send:` (docs/platform/routing.md "Full s1 parameter surface"). Every
parameter this module does not set here takes its catalog default
(Prompt/03-compiler.md "s1 parameters the compiler owns") -- sourced from
the live catalog rather than hand-copied, so an ORHACK version bump changes
this output without a doc-and-code double edit.

`s2` is fully compiler-defaulted (decision #26): every catalog default for
`clocks/transport` already matches the documented value (`midiin=1`,
`midiout=0`, ...), so nothing here overrides anything -- see
docs/platform/routing.md "Transport / clock".
"""

from __future__ import annotations

from rig.catalog.entry import CatalogEntry
from rig.song.model import Chain, Send

from .errors import CompileError

ROUTER_MODULE_TYPE = "routers/hybrid"
TRANSPORT_MODULE_TYPE = "clocks/transport"

LETTER_TO_N = {"A": 1, "B": 2, "C": 3, "D": 4}


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _find_by_module_type(catalog_by_type: dict[str, CatalogEntry], module_type: str) -> CatalogEntry:
    entry = catalog_by_type.get(module_type)
    if entry is None:
        raise CompileError(
            "MISSING_SYSTEM_MODULE",
            f"catalog has no entry for {module_type!r} -- routers/hybrid and "
            "clocks/transport must be present in the built-in catalog",
        )
    return entry


def _send_index(sends: list[Send], name: str, context: str) -> int:
    for i, send in enumerate(sends):
        if send.name == name:
            return i
    raise CompileError("UNDECLARED_SEND", f"{context}: send {name!r} is not declared in 'sends:'")


def compile_transport(catalog_by_type: dict[str, CatalogEntry]) -> dict:
    entry = _find_by_module_type(catalog_by_type, TRANSPORT_MODULE_TYPE)
    params = {p.id: p.default for p in entry.params}
    return {
        "moduleType": TRANSPORT_MODULE_TYPE,
        "params": params,
        "midi-mapping": {"cc": {}},
        "mod-mapping": {"bus": {}},
    }


def compile_router(
    chains: list[Chain],
    sends: list[Send],
    letters: dict[str, str],
    catalog_by_type: dict[str, CatalogEntry],
) -> dict:
    """Build `s1`'s full parameter dict.

    `letters` is chain name -> assigned letter (`rig.compile.letters.
    assign_letters`'s output) -- the caller resolves letter assignment
    once and shares it with the top-level slot compilation, since both need
    the same mapping.
    """
    entry = _find_by_module_type(catalog_by_type, ROUTER_MODULE_TYPE)
    params: dict[str, float] = {p.id: p.default for p in entry.params}

    # Pinned regardless of song content or catalog default drift
    # (docs/platform/routing.md "Traps"): omni r-midi-ch would turn every
    # channel into a preset-save trigger, and r-chin-midigate-N has no
    # schema toggle -- it is always on.
    params["r-midi-ch"] = 16
    params["r-midi-pgmgate"] = 1
    for n in range(1, 5):
        params[f"r-chin-midigate-{n}"] = 1

    for position, chain in enumerate(chains, start=1):
        letter = letters[chain.name]
        n = LETTER_TO_N[letter]
        channel = chain.midi.channel if chain.midi.channel is not None else position
        # Always written explicitly -- r-chin-midich-4's own catalog default
        # is 3, an upstream slip duplicating chain C, so leaving an occupied
        # chain's channel at the catalog default would silently inherit it.
        params[f"r-chin-midich-{n}"] = channel

        if chain.input.guitar:
            input_gain = chain.mix.input_gain if chain.mix.input_gain is not None else 100.0
            params[f"r-chin-l-gain-{n}"] = input_gain
            params[f"r-chin-l-pan-{n}"] = 0.5  # centred; catalog default is hard left (0)
        # `guitar: false` (the default) leaves both physical inputs muted at
        # their own catalog defaults -- nothing to override.

        output_gain = chain.mix.output_gain if chain.mix.output_gain is not None else 100.0
        params[f"r-chout-gain-{n}"] = output_gain

        balance = chain.mix.balance if chain.mix.balance is not None else 50.0
        width = chain.mix.width if chain.mix.width is not None else 100.0
        b, w = balance / 100.0, width / 100.0
        params[f"r-chout-l-pan-{n}"] = _clamp01(b - w / 2)
        params[f"r-chout-r-pan-{n}"] = _clamp01(b + w / 2)

        for index, module in enumerate(chain.modules):
            slot_id = f"{letter.lower()}{index + 1}"
            params[f"r-notethru-{slot_id}"] = 1 if module.note_thru else 0
            for send_name, amount in module.send.items():
                send_index = _send_index(sends, send_name, f"chain {chain.name!r} module {module.key!r}")
                key = f"r-sendP1-{slot_id}" if send_index == 0 else f"r-sendP2-{slot_id}"
                params[key] = amount

    return {
        "moduleType": ROUTER_MODULE_TYPE,
        "params": params,
        "midi-mapping": {"cc": {}},
        "mod-mapping": {"bus": {}},
    }
