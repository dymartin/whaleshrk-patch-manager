"""Ruamel round-trip parsing of `songs/<slug>.yaml` into the song model.

Round-trip mode, not `typ="safe"` -- Phase 6 rewrites song files in place
preserving comments and formatting, and a plain-load parser cannot be
retrofitted (Prompt/02-schema.md ambiguity resolution #3). `SongDocument`
keeps the loaded ruamel node reachable for that reason, even though nothing
in this phase mutates it.

This module checks *shape* only: required fields present, values the right
type, no unknown fields (musicians see friendly YAML and a typo should fail
loudly, not vanish -- Prompt.md's Global Constraint #3). Catalog lookups,
capacity limits and range checks belong to `rig.song.validate`.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

from .errors import SongParseError
from .model import (
    Chain,
    ChainInput,
    ChainMidi,
    ChainMix,
    MidiMapping,
    ModuleSlot,
    ModuleUse,
    Send,
    Song,
)

_yaml = YAML(typ="rt")
_yaml.preserve_quotes = True
# `- item` two spaces in from its parent key, matching docs/schema.md's example
# and every song fixture. Verified against ruamel.yaml 0.19.1's own defaults
# (sequence=2, offset=0, dash flush with the parent key) round-tripping this
# song's exact indentation style incorrectly without this.
_yaml.indent(mapping=2, sequence=4, offset=2)

_TOP_LEVEL_KEYS = {"song", "program", "keyboard", "sends", "master", "mod-sources", "chains"}
_CHAIN_KEYS = {"name", "input", "midi", "mix", "modules"}
_INPUT_KEYS = {"guitar"}
_CHAIN_MIDI_KEYS = {"channel"}
_MIX_KEYS = {"input-gain", "output-gain", "balance", "width"}
_MODULE_RESERVED_KEYS = {"midi", "send", "note-thru", "sample"}


@dataclass
class SongDocument:
    """A parsed `Song` plus the live ruamel node it came from."""

    song: Song
    raw: Any  # ruamel CommentedMap -- the round-trip node `song` was built from
    path: Optional[Path] = None


def parse_song(text: str, *, source: str = "<string>") -> SongDocument:
    try:
        raw = _yaml.load(text)
    except YAMLError as exc:
        # Malformed YAML is a song the musician mistyped, not a crash: it has
        # to arrive as SongParseError like every other bad-shape failure, or
        # the CLI reports it as a ruamel traceback instead of a refusal.
        raise SongParseError(f"{source}: invalid YAML: {exc}") from exc
    if raw is None:
        raise SongParseError(f"{source}: empty song file")
    song = _build_song(raw, source)
    return SongDocument(song=song, raw=raw)


def load_song(path: Path) -> SongDocument:
    doc = parse_song(path.read_text(encoding="utf-8"), source=str(path))
    doc.path = path
    return doc


def dump_song(doc: SongDocument) -> str:
    """Serialise `doc.raw` back to YAML text -- round-trip fidelity for Phase 6."""
    buf = io.StringIO()
    _yaml.dump(doc.raw, buf)
    return buf.getvalue()


def _reject_unknown_keys(mapping: dict, allowed: set[str], source: str, context: str) -> None:
    unknown = sorted(str(k) for k in mapping if str(k) not in allowed)
    if unknown:
        raise SongParseError(f"{source}: {context} has unknown field(s) {unknown}")


def _require(mapping: dict, key: str, source: str, context: str) -> Any:
    if key not in mapping:
        raise SongParseError(f"{source}: {context} is missing required field {key!r}")
    return mapping[key]


def _build_song(raw: Any, source: str) -> Song:
    if not isinstance(raw, dict):
        raise SongParseError(f"{source}: song file must be a mapping at the top level")
    _reject_unknown_keys(raw, _TOP_LEVEL_KEYS, source, "song")

    name = _require(raw, "song", source, "song")
    if not isinstance(name, str) or not name.strip():
        raise SongParseError(f"{source}: 'song' must be a non-empty string")

    program = _require(raw, "program", source, "song")
    if not isinstance(program, int) or isinstance(program, bool):
        raise SongParseError(f"{source}: 'program' must be an integer")

    keyboard = raw.get("keyboard")
    if keyboard is not None and (not isinstance(keyboard, str) or not keyboard.strip()):
        raise SongParseError(f"{source}: 'keyboard' must be a non-empty chain name")

    sends = _build_sends(raw.get("sends"), source)
    master = _build_module_use_list(raw.get("master"), source, "master")
    mod_sources = _build_module_use_list(raw.get("mod-sources"), source, "mod-sources")
    chains = _build_chains(raw.get("chains"), source)

    return Song(
        name=name,
        program=program,
        sends=sends,
        master=master,
        mod_sources=mod_sources,
        chains=chains,
        keyboard=keyboard,
    )


def _build_sends(raw: Any, source: str) -> list[Send]:
    if raw is None:
        return []
    if not isinstance(raw, dict):
        raise SongParseError(f"{source}: 'sends' must be a mapping of name to body")
    sends = []
    for name, body in raw.items():
        if not isinstance(body, dict):
            raise SongParseError(f"{source}: send {name!r} must be a mapping")
        body = dict(body)
        module = _require(body, "module", source, f"send {name!r}")
        body.pop("module")
        sends.append(Send(name=str(name), module=str(module), params=_coerce_params(body)))
    return sends


def _split_module_use_item(item: Any, source: str, context: str) -> tuple[str, dict]:
    """A module-use item is either a bare key, or a single-key `{key: body}` map."""
    if isinstance(item, str):
        return item, {}
    if isinstance(item, dict):
        if len(item) != 1:
            raise SongParseError(
                f"{source}: {context} entry must have exactly one module key, got {list(item)}"
            )
        (key, body), = item.items()
        if body is None:
            body = {}
        if not isinstance(body, dict):
            raise SongParseError(f"{source}: {context} {key!r} body must be a mapping")
        return str(key), dict(body)
    raise SongParseError(f"{source}: {context} entry must be a module key or a mapping, got {item!r}")


def _build_module_use_list(raw: Any, source: str, field_name: str) -> list[ModuleUse]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise SongParseError(f"{source}: {field_name!r} must be a list")
    result = []
    for item in raw:
        key, body = _split_module_use_item(item, source, field_name)
        result.append(ModuleUse(key=key, params=_coerce_params(body)))
    return result


def _coerce_params(body: dict) -> dict[str, float]:
    """Plain param assignments -- everything left after reserved keys are popped.

    Bools coerce to 1.0/0.0 so a `bool`-typed catalog param can be written
    either way; validation applies the same range check regardless of form.
    """
    return {str(key): _coerce_value(value) for key, value in body.items()}


def _coerce_value(value: Any) -> float:
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        return float(value)
    raise SongParseError(f"parameter value {value!r} is not a number")


def _build_chains(raw: Any, source: str) -> list[Chain]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise SongParseError(f"{source}: 'chains' must be a list")
    return [_build_chain(item, source) for item in raw]


def _build_chain(raw: Any, source: str) -> Chain:
    if not isinstance(raw, dict):
        raise SongParseError(f"{source}: each chain must be a mapping")
    _reject_unknown_keys(raw, _CHAIN_KEYS, source, "chain")

    name = _require(raw, "name", source, "chain")
    if not isinstance(name, str) or not name.strip():
        raise SongParseError(f"{source}: chain 'name' must be a non-empty string")

    input_raw = raw.get("input") or {}
    if not isinstance(input_raw, dict):
        raise SongParseError(f"{source}: chain {name!r} 'input' must be a mapping")
    _reject_unknown_keys(input_raw, _INPUT_KEYS, source, f"chain {name!r} input")
    guitar = input_raw.get("guitar", False)
    if not isinstance(guitar, bool):
        raise SongParseError(f"{source}: chain {name!r} 'input.guitar' must be true or false")
    chain_input = ChainInput(guitar=guitar)

    midi_raw = raw.get("midi") or {}
    if not isinstance(midi_raw, dict):
        raise SongParseError(f"{source}: chain {name!r} 'midi' must be a mapping")
    _reject_unknown_keys(midi_raw, _CHAIN_MIDI_KEYS, source, f"chain {name!r} midi")
    channel = midi_raw.get("channel")
    if channel is not None and (not isinstance(channel, int) or isinstance(channel, bool)):
        raise SongParseError(f"{source}: chain {name!r} 'midi.channel' must be an integer")
    chain_midi = ChainMidi(channel=channel)

    mix_raw = raw.get("mix") or {}
    if not isinstance(mix_raw, dict):
        raise SongParseError(f"{source}: chain {name!r} 'mix' must be a mapping")
    _reject_unknown_keys(mix_raw, _MIX_KEYS, source, f"chain {name!r} mix")
    chain_mix = ChainMix(
        input_gain=_optional_number(mix_raw, "input-gain", source, name),
        output_gain=_optional_number(mix_raw, "output-gain", source, name),
        balance=_optional_number(mix_raw, "balance", source, name),
        width=_optional_number(mix_raw, "width", source, name),
    )

    modules_raw = raw.get("modules") or []
    if not isinstance(modules_raw, list):
        raise SongParseError(f"{source}: chain {name!r} 'modules' must be a list")
    modules = [_build_module_slot(item, source, name) for item in modules_raw]

    return Chain(name=name, input=chain_input, midi=chain_midi, mix=chain_mix, modules=modules)


def _optional_number(mapping: dict, key: str, source: str, chain_name: str) -> Optional[float]:
    if key not in mapping:
        return None
    value = mapping[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SongParseError(f"{source}: chain {chain_name!r} 'mix.{key}' must be a number")
    return float(value)


def _build_module_slot(item: Any, source: str, chain_name: str) -> ModuleSlot:
    key, body = _split_module_use_item(item, source, f"chain {chain_name!r} module")

    midi_raw = body.pop("midi", None) or {}
    if not isinstance(midi_raw, dict):
        raise SongParseError(f"{source}: chain {chain_name!r} module {key!r} 'midi' must be a mapping")
    midi = {
        str(param): _build_midi_mapping(value, source, chain_name, key, str(param))
        for param, value in midi_raw.items()
    }

    send_raw = body.pop("send", None) or {}
    if not isinstance(send_raw, dict):
        raise SongParseError(f"{source}: chain {chain_name!r} module {key!r} 'send' must be a mapping")
    send = {str(name): _coerce_value(value) for name, value in send_raw.items()}

    note_thru = body.pop("note-thru", False)
    if not isinstance(note_thru, bool):
        raise SongParseError(f"{source}: chain {chain_name!r} module {key!r} 'note-thru' must be true or false")

    sample = body.pop("sample", None)
    if sample is not None and not isinstance(sample, str):
        raise SongParseError(f"{source}: chain {chain_name!r} module {key!r} 'sample' must be a string")

    params = _coerce_params(body)

    return ModuleSlot(key=key, params=params, midi=midi, send=send, note_thru=note_thru, sample=sample)


def _build_midi_mapping(value: Any, source: str, chain_name: str, module_key: str, param: str) -> MidiMapping:
    context = f"chain {chain_name!r} module {module_key!r} midi.{param}"
    if isinstance(value, bool):
        raise SongParseError(f"{source}: {context} must be a CC number or a mapping")
    if isinstance(value, int):
        return MidiMapping(cc=value, channel=None)
    if isinstance(value, dict):
        _reject_unknown_keys(value, {"channel", "cc"}, source, context)
        cc = value.get("cc")
        channel = value.get("channel")
        if not isinstance(cc, int) or isinstance(cc, bool):
            raise SongParseError(f"{source}: {context} 'cc' must be an integer")
        if not isinstance(channel, int) or isinstance(channel, bool):
            raise SongParseError(f"{source}: {context} 'channel' must be an integer")
        return MidiMapping(cc=cc, channel=channel)
    raise SongParseError(f"{source}: {context} must be a CC number or a mapping")
