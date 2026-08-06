"""Every hard error, plus the full lint-warning policy from `docs/schema.md`
("Lint policy") and `Prompt/08-cli.md`.

Findings accumulate rather than raising on the first problem, so `rig lint`
can report everything wrong with a song in one pass. A caller that wants
fail-fast can raise `SongValidationError(result.errors)` itself.

Of the policy's error list, "unsafe, reserved, overlong or case-colliding
paths", "duplicate runtime module paths" and "unsafe archives" are not
re-checked here: they are catalog-ingest concerns (`docs/catalog.md`
"Validation gate", already enforced by `rig.catalog.ingest`/`rig.catalog.gate`
before a module can ever reach `.rig/catalog/`), not something a song file
can express. "Wrong slot class" has no separate mechanism of its own either:
a song can only place a module key into a slot by writing that key under
`sends:`/`master:`/`mod-sources:`/a chain's `modules:`, and any key that does
not resolve in the catalog is already `UNKNOWN_MODULE` -- there is no
narrower, checkable "right module, wrong slot" condition beyond that, as a
*hard error*. `category`/`module_type` are ingest-recorded and do let
`_module_role`/`_is_sampler` (below) guess a module's role for the
`INSTRUMENT_AFTER_EFFECT`/`UNSELECTED_SAMPLER` warnings -- `docs/platform/
modules.md` bans classifying by inspecting the *patch itself* (signal I/O
does not discriminate instrument from effect), not by this ingest-recorded
metadata. What that guess is not is *reliable* enough to error on: category
is "functionally inert" on the device (`docs/catalog.md`) and can be a bad
guess for a community upload, so a slot-class mismatch stays a warning, not
a hard error.
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

# input-gain's documented default/unity is 100 (docs/schema.md "mix:");
# output-gain's own hard cap is already 100, so it can never read as
# above-unity -- only input-gain can.
UNITY_INPUT_GAIN = 100.0

# Below this fraction of full width (100), a chain reads as collapsed toward
# mono. No doc pins a number -- a lint heuristic, not a device constant;
# picked as a starting point, cheap to revisit if it proves noisy.
NARROW_WIDTH_THRESHOLD = 20.0


def _module_role(entry: CatalogEntry) -> Optional[str]:
    """"instrument" or "effect" if the module's install folder says so,
    else None -- the best available signal, not an authoritative one.

    `docs/platform/modules.md` is explicit that a module's role cannot be
    derived from its patch (signal I/O does not discriminate), and
    `docs/catalog.md` calls the category folder "functionally inert" on the
    device. For a community module, `category_override` or `category` (the
    folder ingest mapped from its Patchstorage upload category) is that
    folder. `@orhack` built-ins never carry `category` (`rig.catalog.builtins`
    leaves it None) -- their `module_type` *is* their real install path
    inside ORHACK, filed under the identical `instruments/`/`effects/` top
    level for the same reason, so it stands in. A wrong guess here costs a
    stray or missing lint warning, never device behaviour.
    """
    folder = entry.category_override or entry.category
    if folder is None and entry.source == "orhack":
        folder = entry.module_type
    if folder is None:
        return None
    if folder.startswith("instruments/"):
        return "instrument"
    if folder.startswith("effects/"):
        return "effect"
    return None


def _is_sampler(entry: CatalogEntry) -> bool:
    folder = entry.category_override or entry.category
    if folder is None and entry.source == "orhack":
        folder = entry.module_type
    return folder is not None and folder.startswith("instruments/sampler")


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


def _validate_mix(chain: Chain, findings: list[Finding], warnings: list[Finding]) -> None:
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

    if in_range["input-gain"] and mix.input_gain is not None and mix.input_gain > UNITY_INPUT_GAIN:
        warnings.append(
            Finding(
                "ABOVE_UNITY_GAIN",
                f"chain {chain.name!r} mix.input-gain = {mix.input_gain} is above unity ({UNITY_INPUT_GAIN})",
            )
        )
    if in_range["width"] and mix.width is not None and abs(mix.width) < NARROW_WIDTH_THRESHOLD:
        warnings.append(
            Finding(
                "NARROW_WIDTH",
                f"chain {chain.name!r} mix.width = {mix.width} is narrow, close to mono",
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

    cc_targets: dict[tuple[int, int], list[str]] = {}

    for chain in song.chains:
        if not chain.modules:
            warnings.append(Finding("EMPTY_CHAIN", f"chain {chain.name!r} has no modules"))

    for position, chain in enumerate(song.chains, start=1):
        _validate_chain_channel(chain, findings)
        _validate_mix(chain, findings, warnings)

        chain_channel = _resolved_channel(chain, position)
        seen_effect = False
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

            if entry is not None:
                role = _module_role(entry)
                if role == "effect":
                    seen_effect = True
                elif role == "instrument" and seen_effect:
                    warnings.append(
                        Finding(
                            "INSTRUMENT_AFTER_EFFECT",
                            f"chain {chain.name!r} module {module.key!r} is an instrument placed "
                            "after an effect earlier in the same chain",
                        )
                    )
                if _is_sampler(entry) and module.sample is None:
                    warnings.append(
                        Finding(
                            "UNSELECTED_SAMPLER",
                            f"chain {chain.name!r} module {module.key!r} has no 'sample:' selected",
                        )
                    )
                for param_name, mapping in module.midi.items():
                    channel = mapping.channel if mapping.channel is not None else chain_channel
                    target = f"chain {chain.name!r} module {module.key!r} midi.{param_name}"
                    cc_targets.setdefault((channel, mapping.cc), []).append(target)

            if module.note_thru and index == len(chain.modules) - 1:
                warnings.append(
                    Finding(
                        "FINAL_NOTE_THRU",
                        f"chain {chain.name!r} module {module.key!r} is the last in its chain; "
                        "note-thru has nothing to forward to",
                    )
                )

    for (channel, cc), targets in cc_targets.items():
        if len(targets) > 1:
            warnings.append(
                Finding(
                    "MULTI_TARGET_CC",
                    f"channel {channel} CC {cc} is mapped to more than one target: {targets}",
                )
            )

    used_sends: set[str] = set()
    for chain in song.chains:
        for module in chain.modules:
            used_sends.update(module.send)
    for send in song.sends:
        if send.name not in used_sends:
            warnings.append(Finding("UNUSED_SEND", f"send {send.name!r} is declared but never used by a module"))

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
