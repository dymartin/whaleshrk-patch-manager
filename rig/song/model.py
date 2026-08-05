"""The song model: musicians' friendly YAML surface, as typed data.

Field set matches the canonical example in `docs/schema.md` exactly (see
`Prompt/02-schema.md` "Song shape"). Nothing here is a device identifier --
no slot ids, `moduleType` paths, parameter ids, `kit-N`, encoded CC keys or
chain letters (Prompt.md's Global Constraint #5).

Values are frozen dataclasses: a song is a value read from a file, not
something callers mutate in place. Round-trip fidelity for Phase 6's
in-place rewriting comes from `SongDocument.raw`, not from mutating these.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class ChainInput:
    guitar: bool = False


@dataclass(frozen=True)
class ChainMidi:
    """`channel` is None when the song omits `midi: { channel: }`.

    None means "declaration-position default" (1st chain -> 1, 2nd -> 2, ...)
    -- resolving that default is the compiler's job, not the parser's, since
    it depends on the chain's position among its siblings.
    """

    channel: Optional[int] = None


@dataclass(frozen=True)
class ChainMix:
    """Each field is None when the song omits it -- defaults are compiler-owned."""

    input_gain: Optional[float] = None
    output_gain: Optional[float] = None
    balance: Optional[float] = None
    width: Optional[float] = None


@dataclass(frozen=True)
class MidiMapping:
    """One entry of a module's `midi:` block.

    `channel` is None for the implied form (`size: 74`) -- the CC key's
    channel comes from the chain. An explicit channel (`{channel: 1, cc: 20}`)
    always states one, regardless of the chain it sits in.
    """

    cc: int
    channel: Optional[int] = None


@dataclass(frozen=True)
class ModuleSlot:
    """One module occupying a chain slot."""

    key: str
    params: dict[str, float] = field(default_factory=dict)
    midi: dict[str, MidiMapping] = field(default_factory=dict)
    send: dict[str, float] = field(default_factory=dict)
    note_thru: bool = False
    sample: Optional[str] = None


@dataclass(frozen=True)
class Chain:
    name: str
    input: ChainInput = field(default_factory=ChainInput)
    midi: ChainMidi = field(default_factory=ChainMidi)
    mix: ChainMix = field(default_factory=ChainMix)
    modules: list[ModuleSlot] = field(default_factory=list)


@dataclass(frozen=True)
class ModuleUse:
    """A bare module reference with parameters -- master FX and mod sources.

    Unlike a chain's `ModuleSlot`, these have no `midi:`, `send:`,
    `note-thru:` or `sample:` -- those fields only exist for chain slots.
    """

    key: str
    params: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class Send:
    name: str
    module: str
    params: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class Song:
    name: str
    program: int
    sends: list[Send] = field(default_factory=list)
    master: list[ModuleUse] = field(default_factory=list)
    mod_sources: list[ModuleUse] = field(default_factory=list)
    chains: list[Chain] = field(default_factory=list)
