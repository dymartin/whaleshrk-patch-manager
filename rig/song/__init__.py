"""The song model: musicians' YAML surface, its parser, and its validation.

See docs/schema.md for the field set and every rule this package enforces.
"""

from .bindings import read_bindings, write_bindings
from .errors import Finding, SongParseError, SongValidationError
from .kits import KitsConfig, KitsError, parse_kits
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
from .parser import SongDocument, dump_song, load_song, parse_song
from .validate import ValidationResult, validate_song, validate_songs

__all__ = [
    "read_bindings",
    "write_bindings",
    "Finding",
    "SongParseError",
    "SongValidationError",
    "KitsConfig",
    "KitsError",
    "parse_kits",
    "Chain",
    "ChainInput",
    "ChainMidi",
    "ChainMix",
    "MidiMapping",
    "ModuleSlot",
    "ModuleUse",
    "Send",
    "Song",
    "SongDocument",
    "dump_song",
    "load_song",
    "parse_song",
    "ValidationResult",
    "validate_song",
    "validate_songs",
]
