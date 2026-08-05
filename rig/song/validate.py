"""Every hard error and the two chain-level lint warnings from
`Prompt/02-schema.md`'s hard-error table, plus `docs/schema.md`'s "Rules" and
"mix:" sections (Prompt.md's Global Constraint #3: every capacity, collision
and out-of-range condition documented is a hard error with its own message).

Findings accumulate rather than raising on the first problem, so `rig lint`
(Phase 8) can report everything wrong with a song in one pass. A caller that
wants fail-fast can raise `SongValidationError(result.errors)` itself.

The fuller lint policy in `docs/schema.md` ("Lint policy") -- instrument
ordering, multi-target CC, unused sends, and so on -- is Phase 8's job. This
module implements exactly the two warnings the schema phase's own brief
requires to be distinguishable from errors: a shared numbered channel, and
`note-thru` on a chain's last module.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

from rig.catalog.entry import CatalogEntry
from rig.catalog.slugs import slug
from rig.compile.letters import ChainSlots, LetterAssignmentError, assign_letters

from .errors import Finding
from .kits import KitsConfig
from .model import Chain, ModuleSlot, ModuleUse, Song

RESERVED_CCS = {1, 74}
CHAIN_CHANNEL_RANGE = range(0, 16)  # 0 = omni, 1-15 specific; 16 is reserved
MODULE_CHANNEL_RANGE = range(1, 16)  # 1-15; 0 never emitted by ctlin, 16 reserved

MIX_RANGES = {
    "input-gain": (0.0, 200.0),
    "output-gain": (0.0, 100.0),
    "balance": (0.0, 100.0),
    "width": (-100.0, 100.0),
}


@dataclass
class ValidationResult:
    errors: list[Finding] = field(default_factory=list)
    warnings: list[Finding] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def _catalog_index(catalog: Iterable[CatalogEntry]) -> dict[str, CatalogEntry]:
    return {entry.key: entry for entry in catalog}


def _finite(value: float) -> bool:
    return math.isfinite(value)


def _validate_module_params(
    *,
    module_key: str,
    params: dict[str, float],
    catalog_index: dict[str, CatalogEntry],
    findings: list[Finding],
    context: str,
) -> Optional[CatalogEntry]:
    """Look up `module_key` and check every declared param against it.

    Returns the matched entry (or None if the key is unknown) so callers that
    also need to validate a chain module's `midi:` keys against the same
    param set do not look it up twice.
    """
    entry = catalog_index.get(module_key)
    if entry is None:
        findings.append(Finding("UNKNOWN_MODULE", f"{context}: module {module_key!r} is not in the catalog"))
        return None

    param_index = {p.name: p for p in entry.params}
    for name, value in params.items():
        spec = param_index.get(name)
        if spec is None:
            findings.append(
                Finding("UNKNOWN_PARAM", f"{context}: module {module_key!r} has no parameter {name!r}")
            )
            continue
        if not _finite(value):
            findings.append(
                Finding(
                    "NON_FINITE_VALUE",
                    f"{context}: module {module_key!r} parameter {name!r} = {value} is not finite",
                )
            )
            continue
        if not (spec.min <= value <= spec.max):
            findings.append(
                Finding(
                    "PARAM_OUT_OF_RANGE",
                    f"{context}: module {module_key!r} parameter {name!r} = {value} is outside "
                    f"its range {spec.min}-{spec.max}",
                )
            )
    return entry


def _validate_capacity(
    findings: list[Finding], *, code: str, label: str, count: int, cap: int, unit: str
) -> None:
    if count > cap:
        findings.append(Finding(code, f"{count} {label} declared; at most {cap} {unit} exist"))


def _validate_sends(song: Song, catalog_index: dict[str, CatalogEntry], findings: list[Finding]) -> None:
    _validate_capacity(
        findings, code="SENDS_EXCEEDED", label="sends", count=len(song.sends), cap=2, unit="(p1, p2)"
    )
    for send in song.sends:
        _validate_module_params(
            module_key=send.module,
            params=send.params,
            catalog_index=catalog_index,
            findings=findings,
            context=f"send {send.name!r}",
        )


def _validate_module_use_list(
    items: list[ModuleUse], catalog_index: dict[str, CatalogEntry], findings: list[Finding], label: str
) -> None:
    for use in items:
        _validate_module_params(
            module_key=use.key,
            params=use.params,
            catalog_index=catalog_index,
            findings=findings,
            context=label,
        )


def _resolved_channel(chain: Chain, position: int) -> int:
    """Declaration position (1-based) unless the chain overrides it."""
    return chain.midi.channel if chain.midi.channel is not None else position


def _validate_chain_channel(chain: Chain, findings: list[Finding]) -> None:
    channel = chain.midi.channel
    if channel is None:
        return
    if channel == 16:
        findings.append(
            Finding(
                "CHAIN_CHANNEL_16",
                f"chain {chain.name!r} note channel is 16, reserved for song Program Change "
                "and preset control",
            )
        )
    elif channel not in CHAIN_CHANNEL_RANGE:
        findings.append(
            Finding(
                "CHAIN_CHANNEL_OUT_OF_RANGE",
                f"chain {chain.name!r} note channel {channel} is outside 0-15",
            )
        )


def _validate_mix(chain: Chain, findings: list[Finding]) -> None:
    mix = chain.mix
    values = {
        "input-gain": mix.input_gain,
        "output-gain": mix.output_gain,
        "balance": mix.balance,
        "width": mix.width,
    }
    in_range = {}
    for name, value in values.items():
        if value is None:
            in_range[name] = True
            continue
        if not _finite(value):
            findings.append(
                Finding("NON_FINITE_VALUE", f"chain {chain.name!r} mix.{name} = {value} is not finite")
            )
            in_range[name] = False
            continue
        lo, hi = MIX_RANGES[name]
        ok = lo <= value <= hi
        in_range[name] = ok
        if not ok:
            findings.append(
                Finding(
                    "MIX_FIELD_OUT_OF_RANGE",
                    f"chain {chain.name!r} mix.{name} = {value} is outside {lo}-{hi}",
                )
            )

    if in_range["balance"] and in_range["width"]:
        balance = mix.balance if mix.balance is not None else 50.0
        width = mix.width if mix.width is not None else 100.0
        b, w = balance / 100.0, width / 100.0
        left_pan, right_pan = b - w / 2, b + w / 2
        if not (0.0 <= left_pan <= 1.0 and 0.0 <= right_pan <= 1.0):
            findings.append(
                Finding(
                    "MIX_PAN_OUT_OF_RANGE",
                    f"chain {chain.name!r} balance={balance} width={width} push a pan outside 0-1",
                )
            )


def _validate_module_midi(
    chain: Chain,
    module: ModuleSlot,
    entry: Optional[CatalogEntry],
    chain_channel: int,
    findings: list[Finding],
) -> None:
    param_names = {p.name for p in entry.params} if entry is not None else set()
    for param, mapping in module.midi.items():
        context = f"chain {chain.name!r} module {module.key!r} midi.{param}"
        if entry is not None and param not in param_names:
            findings.append(Finding("UNKNOWN_PARAM", f"{context}: no such parameter"))

        if mapping.channel is None:
            if chain_channel == 0:
                findings.append(
                    Finding(
                        "OMNI_MIDI_SHORTHAND",
                        f"{context} has no explicit channel; chain {chain.name!r} is omni and "
                        "the implied form can never match a real message",
                    )
                )
        elif mapping.channel == 16:
            findings.append(Finding("MODULE_MIDI_CHANNEL_16", f"{context} channel is 16, reserved"))
        elif mapping.channel not in MODULE_CHANNEL_RANGE:
            findings.append(
                Finding(
                    "MODULE_MIDI_CHANNEL_OUT_OF_RANGE",
                    f"{context} channel {mapping.channel} is outside 1-15",
                )
            )

        if mapping.cc in RESERVED_CCS:
            findings.append(
                Finding("RESERVED_CC", f"{context} uses CC {mapping.cc}, reserved for per-chain modulation")
            )
        elif not (0 <= mapping.cc <= 127):
            findings.append(
                Finding("MODULE_MIDI_CC_OUT_OF_RANGE", f"{context} CC {mapping.cc} is outside 0-127")
            )


def _validate_module_send(
    chain: Chain, module: ModuleSlot, song: Song, findings: list[Finding]
) -> None:
    declared = {s.name for s in song.sends}
    for name, amount in module.send.items():
        context = f"chain {chain.name!r} module {module.key!r} send {name!r}"
        if name not in declared:
            findings.append(Finding("UNDECLARED_SEND", f"{context} is not declared in 'sends:'"))
        if not _finite(amount):
            findings.append(Finding("NON_FINITE_VALUE", f"{context} = {amount} is not finite"))
        elif not (0 <= amount <= 100):
            findings.append(Finding("SEND_AMOUNT_OUT_OF_RANGE", f"{context} = {amount} is outside 0-100"))


def _validate_sample(
    chain: Chain,
    module: ModuleSlot,
    kits: Optional[KitsConfig],
    media_root: Optional[Path],
    findings: list[Finding],
) -> None:
    if module.sample is None:
        return
    context = f"chain {chain.name!r} module {module.key!r} sample {module.sample!r}"
    parts = module.sample.split("/", 1)
    if len(parts) != 2 or not parts[0] or not parts[1] or not parts[1].endswith(".wav") or parts[1] != parts[1].lower():
        findings.append(
            Finding("INVALID_SAMPLE_REFERENCE", f"{context} is not '<kit-alias>/<filename.wav>'")
        )
        return
    alias, filename = parts

    if kits is not None:
        if alias not in kits.aliases:
            findings.append(Finding("UNKNOWN_KIT_ALIAS", f"{context} references unknown kit alias {alias!r}"))
            return
        if media_root is not None:
            path = kits.kit_dir(media_root, alias) / filename
            if not path.is_file():
                findings.append(Finding("MISSING_SAMPLE_FILE", f"{context} does not exist at {path}"))


def validate_song(
    song: Song,
    *,
    catalog: Iterable[CatalogEntry] = (),
    kits: Optional[KitsConfig] = None,
    media_root: Optional[Path] = None,
    bindings: Optional[dict[str, str]] = None,
) -> ValidationResult:
    findings: list[Finding] = []
    warnings: list[Finding] = []
    catalog_index = _catalog_index(catalog)

    if not (0 <= song.program <= 127):
        findings.append(Finding("PROGRAM_OUT_OF_RANGE", f"program {song.program} is outside 0-127"))

    seen_names: set[str] = set()
    for chain in song.chains:
        if chain.name in seen_names:
            findings.append(
                Finding("DUPLICATE_CHAIN_NAME", f"chain name {chain.name!r} is declared more than once")
            )
        seen_names.add(chain.name)

    _validate_sends(song, catalog_index, findings)
    _validate_module_use_list(song.master, catalog_index, findings, "master")
    _validate_capacity(
        findings, code="MASTER_EXCEEDED", label="master FX", count=len(song.master), cap=3, unit="(f1-f3)"
    )
    _validate_module_use_list(song.mod_sources, catalog_index, findings, "mod-sources")
    _validate_capacity(
        findings,
        code="MOD_SOURCES_EXCEEDED",
        label="mod sources",
        count=len(song.mod_sources),
        cap=3,
        unit="(m1-m3)",
    )

    _validate_capacity(
        findings, code="CHAINS_EXCEEDED", label="chains", count=len(song.chains), cap=4, unit="letters (A-D)"
    )

    for chain in song.chains:
        if len(chain.modules) > 4:
            findings.append(
                Finding(
                    "MODULES_PER_CHAIN_EXCEEDED",
                    f"chain {chain.name!r} has {len(chain.modules)} modules; a chain holds at most 4",
                )
            )

    if len(song.chains) <= 4 and all(len(c.modules) <= 4 for c in song.chains):
        chain_slots = [ChainSlots(name=c.name, slot_count=len(c.modules)) for c in song.chains]
        try:
            assign_letters(chain_slots, bindings or {})
        except LetterAssignmentError as exc:
            findings.append(Finding(exc.code, str(exc)))

    for position, chain in enumerate(song.chains, start=1):
        _validate_chain_channel(chain, findings)
        _validate_mix(chain, findings)

        chain_channel = _resolved_channel(chain, position)
        for index, module in enumerate(chain.modules):
            entry = _validate_module_params(
                module_key=module.key,
                params=module.params,
                catalog_index=catalog_index,
                findings=findings,
                context=f"chain {chain.name!r} module {module.key!r}",
            )
            _validate_module_midi(chain, module, entry, chain_channel, findings)
            _validate_module_send(chain, module, song, findings)
            _validate_sample(chain, module, kits, media_root, findings)

            if module.note_thru and index == len(chain.modules) - 1:
                warnings.append(
                    Finding(
                        "FINAL_NOTE_THRU",
                        f"chain {chain.name!r} module {module.key!r} is the last in its chain; "
                        "note-thru has nothing to forward to",
                    )
                )

    channel_groups: dict[int, list[str]] = {}
    for position, chain in enumerate(song.chains, start=1):
        channel = _resolved_channel(chain, position)
        if channel == 0:  # omni is exempt -- overlaps every chain by design
            continue
        channel_groups.setdefault(channel, []).append(chain.name)
    for channel, names in channel_groups.items():
        if len(names) > 1:
            warnings.append(
                Finding("SHARED_CHANNEL", f"chains {names} share note channel {channel}")
            )

    return ValidationResult(errors=findings, warnings=warnings)


def validate_songs(songs: list[Song]) -> ValidationResult:
    """Cross-song rules: a duplicate `program`, or names that collide once
    sanitised to a filename."""
    findings: list[Finding] = []

    by_program: dict[int, list[str]] = {}
    for song in songs:
        by_program.setdefault(song.program, []).append(song.name)
    for program, names in by_program.items():
        if len(names) > 1:
            findings.append(
                Finding("DUPLICATE_PROGRAM", f"program {program} is used by more than one song: {names}")
            )

    by_slug: dict[str, list[str]] = {}
    for song in songs:
        by_slug.setdefault(slug(song.name), []).append(song.name)
    for sanitised, names in by_slug.items():
        if len(set(names)) > 1:
            findings.append(
                Finding(
                    "SONG_NAME_COLLISION",
                    f"song names {names} collide after sanitisation to {sanitised!r}",
                )
            )

    return ValidationResult(errors=findings, warnings=[])
