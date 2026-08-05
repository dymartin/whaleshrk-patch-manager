"""One test per hard error in Prompt/02-schema.md's table, asserting its own
distinct `Finding.code`, plus the two lint warnings that must be reportable
separately from errors.
"""

from __future__ import annotations

import math
from pathlib import Path

from rig.song.kits import KitsConfig
from rig.song.model import (
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
from rig.song.parser import parse_song
from rig.song.validate import validate_song, validate_songs

from .song_helpers import make_entry, param, vellichor_catalog

FIXTURE = Path(__file__).parent / "fixtures" / "songs" / "vellichor.yaml"


def codes(result, severity="errors"):
    return {f.code for f in getattr(result, severity)}


def test_canonical_example_validates_with_no_findings():
    song = parse_song(FIXTURE.read_text(encoding="utf-8")).song
    result = validate_song(song, catalog=vellichor_catalog())
    assert result.errors == []
    assert result.warnings == []


def test_unknown_module_key():
    song = Song(name="x", program=0, chains=[
        Chain(name="pads", modules=[ModuleSlot(key="nonexistent@orhack")])
    ])
    result = validate_song(song, catalog=[])
    assert "UNKNOWN_MODULE" in codes(result)


def test_unknown_parameter_name():
    catalog = [make_entry("foo@orhack", "orhack", "Foo", [param("size")])]
    song = Song(name="x", program=0, chains=[
        Chain(name="pads", modules=[ModuleSlot(key="foo@orhack", params={"nope": 1})])
    ])
    result = validate_song(song, catalog=catalog)
    assert "UNKNOWN_PARAM" in codes(result)


def test_param_out_of_range():
    catalog = [make_entry("foo@orhack", "orhack", "Foo", [param("size", min_=0, max_=100)])]
    song = Song(name="x", program=0, chains=[
        Chain(name="pads", modules=[ModuleSlot(key="foo@orhack", params={"size": 150})])
    ])
    result = validate_song(song, catalog=catalog)
    assert "PARAM_OUT_OF_RANGE" in codes(result)


def test_duplicate_chain_names():
    song = Song(name="x", program=0, chains=[Chain(name="pads"), Chain(name="pads")])
    result = validate_song(song, catalog=[])
    assert "DUPLICATE_CHAIN_NAME" in codes(result)


def test_duplicate_program_across_songs():
    a = Song(name="A", program=5)
    b = Song(name="B", program=5)
    result = validate_songs([a, b])
    assert "DUPLICATE_PROGRAM" in codes(result)


def test_program_out_of_range():
    song = Song(name="x", program=200)
    result = validate_song(song, catalog=[])
    assert "PROGRAM_OUT_OF_RANGE" in codes(result)


def test_song_names_colliding_after_sanitisation():
    a = Song(name="Low Tide", program=1)
    b = Song(name="low-tide", program=2)
    result = validate_songs([a, b])
    assert "SONG_NAME_COLLISION" in codes(result)


def test_chains_exceeded():
    song = Song(name="x", program=0, chains=[Chain(name=f"c{i}") for i in range(5)])
    result = validate_song(song, catalog=[])
    assert "CHAINS_EXCEEDED" in codes(result)


def test_modules_per_chain_exceeded():
    catalog = [make_entry("foo@orhack", "orhack", "Foo", [])]
    modules = [ModuleSlot(key="foo@orhack") for _ in range(5)]
    song = Song(name="x", program=0, chains=[Chain(name="pads", modules=modules)])
    result = validate_song(song, catalog=catalog)
    assert "MODULES_PER_CHAIN_EXCEEDED" in codes(result)


def test_chains_needing_4_slots_exceeded():
    catalog = [make_entry("foo@orhack", "orhack", "Foo", [])]

    def four_slot_chain(name):
        return Chain(name=name, modules=[ModuleSlot(key="foo@orhack") for _ in range(4)])

    song = Song(name="x", program=0, chains=[four_slot_chain("a"), four_slot_chain("b"), four_slot_chain("c")])
    result = validate_song(song, catalog=catalog)
    assert "CHAINS_NEEDING_4_SLOTS_EXCEEDED" in codes(result)


def test_sends_exceeded():
    catalog = [make_entry("foo@orhack", "orhack", "Foo", [])]
    sends = [Send(name=f"s{i}", module="foo@orhack") for i in range(3)]
    song = Song(name="x", program=0, sends=sends)
    result = validate_song(song, catalog=catalog)
    assert "SENDS_EXCEEDED" in codes(result)


def test_master_exceeded():
    catalog = [make_entry("foo@orhack", "orhack", "Foo", [])]
    master = [ModuleUse(key="foo@orhack") for _ in range(4)]
    song = Song(name="x", program=0, master=master)
    result = validate_song(song, catalog=catalog)
    assert "MASTER_EXCEEDED" in codes(result)


def test_mod_sources_exceeded():
    catalog = [make_entry("foo@orhack", "orhack", "Foo", [])]
    mod_sources = [ModuleUse(key="foo@orhack") for _ in range(4)]
    song = Song(name="x", program=0, mod_sources=mod_sources)
    result = validate_song(song, catalog=catalog)
    assert "MOD_SOURCES_EXCEEDED" in codes(result)


def test_bound_chain_outgrowing_its_letter():
    catalog = [make_entry("foo@orhack", "orhack", "Foo", [])]
    modules = [ModuleSlot(key="foo@orhack") for _ in range(4)]
    song = Song(name="x", program=0, chains=[Chain(name="pads", modules=modules)])
    result = validate_song(song, catalog=catalog, bindings={"pads": "A"})
    assert "BOUND_CHAIN_OUTGROWN" in codes(result)


def test_module_midi_shorthand_on_omni_chain_is_an_error():
    catalog = [make_entry("foo@orhack", "orhack", "Foo", [param("size")])]
    slot = ModuleSlot(key="foo@orhack", midi={"size": MidiMapping(cc=20, channel=None)})
    song = Song(name="x", program=0, chains=[
        Chain(name="drones", midi=ChainMidi(channel=0), modules=[slot])
    ])
    result = validate_song(song, catalog=catalog)
    assert "OMNI_MIDI_SHORTHAND" in codes(result)


def test_chain_note_channel_16_is_an_error():
    song = Song(name="x", program=0, chains=[Chain(name="pads", midi=ChainMidi(channel=16))])
    result = validate_song(song, catalog=[])
    assert "CHAIN_CHANNEL_16" in codes(result)


def test_module_midi_channel_16_is_an_error():
    catalog = [make_entry("foo@orhack", "orhack", "Foo", [param("size")])]
    slot = ModuleSlot(key="foo@orhack", midi={"size": MidiMapping(cc=20, channel=16)})
    song = Song(name="x", program=0, chains=[Chain(name="pads", modules=[slot])])
    result = validate_song(song, catalog=catalog)
    assert "MODULE_MIDI_CHANNEL_16" in codes(result)


def test_reserved_cc_1_is_an_error():
    catalog = [make_entry("foo@orhack", "orhack", "Foo", [param("size")])]
    slot = ModuleSlot(key="foo@orhack", midi={"size": MidiMapping(cc=1, channel=1)})
    song = Song(name="x", program=0, chains=[Chain(name="pads", modules=[slot])])
    result = validate_song(song, catalog=catalog)
    assert "RESERVED_CC" in codes(result)


def test_reserved_cc_74_is_an_error():
    catalog = [make_entry("foo@orhack", "orhack", "Foo", [param("size")])]
    slot = ModuleSlot(key="foo@orhack", midi={"size": MidiMapping(cc=74, channel=1)})
    song = Song(name="x", program=0, chains=[Chain(name="pads", modules=[slot])])
    result = validate_song(song, catalog=catalog)
    assert "RESERVED_CC" in codes(result)


def test_unknown_kit_alias_is_an_error():
    catalog = [make_entry("samplement@orhack", "orhack", "Samplement", [])]
    slot = ModuleSlot(key="samplement@orhack", sample="ghost/kick.wav")
    song = Song(name="x", program=0, chains=[Chain(name="pads", modules=[slot])])
    result = validate_song(song, catalog=catalog, kits=KitsConfig({"warehouse": 1}))
    assert "UNKNOWN_KIT_ALIAS" in codes(result)


def test_missing_sample_file_is_an_error(tmp_path: Path):
    catalog = [make_entry("samplement@orhack", "orhack", "Samplement", [])]
    slot = ModuleSlot(key="samplement@orhack", sample="warehouse/kick.wav")
    song = Song(name="x", program=0, chains=[Chain(name="pads", modules=[slot])])
    (tmp_path / "kits" / "warehouse").mkdir(parents=True)
    result = validate_song(
        song, catalog=catalog, kits=KitsConfig({"warehouse": 1}), media_root=tmp_path
    )
    assert "MISSING_SAMPLE_FILE" in codes(result)


def test_invalid_sample_reference_is_an_error():
    catalog = [make_entry("samplement@orhack", "orhack", "Samplement", [])]
    slot = ModuleSlot(key="samplement@orhack", sample="not-a-valid-reference")
    song = Song(name="x", program=0, chains=[Chain(name="pads", modules=[slot])])
    result = validate_song(song, catalog=catalog, kits=KitsConfig({}))
    assert "INVALID_SAMPLE_REFERENCE" in codes(result)


def test_non_finite_value_is_an_error():
    catalog = [make_entry("foo@orhack", "orhack", "Foo", [param("size")])]
    song = Song(name="x", program=0, chains=[
        Chain(name="pads", modules=[ModuleSlot(key="foo@orhack", params={"size": math.inf})])
    ])
    result = validate_song(song, catalog=catalog)
    assert "NON_FINITE_VALUE" in codes(result)


def test_undeclared_send_is_an_error():
    catalog = [make_entry("foo@orhack", "orhack", "Foo", [])]
    slot = ModuleSlot(key="foo@orhack", send={"nope": 50})
    song = Song(name="x", program=0, chains=[Chain(name="pads", modules=[slot])])
    result = validate_song(song, catalog=catalog)
    assert "UNDECLARED_SEND" in codes(result)


def test_mix_field_out_of_range():
    song = Song(name="x", program=0, chains=[
        Chain(name="pads", mix=ChainMix(output_gain=150))
    ])
    result = validate_song(song, catalog=[])
    assert "MIX_FIELD_OUT_OF_RANGE" in codes(result)


def test_mix_balance_and_width_pushing_a_pan_out_of_range():
    song = Song(name="x", program=0, chains=[
        Chain(name="pads", mix=ChainMix(balance=10, width=100))
    ])
    result = validate_song(song, catalog=[])
    assert "MIX_PAN_OUT_OF_RANGE" in codes(result)


def test_shared_numbered_channel_is_a_warning_not_an_error():
    song = Song(name="x", program=0, chains=[
        Chain(name="a", midi=ChainMidi(channel=5)),
        Chain(name="b", midi=ChainMidi(channel=5)),
    ])
    result = validate_song(song, catalog=[])
    assert "SHARED_CHANNEL" in codes(result, "warnings")
    assert "SHARED_CHANNEL" not in codes(result, "errors")


def test_two_omni_chains_are_not_a_shared_channel_warning():
    song = Song(name="x", program=0, chains=[
        Chain(name="a", midi=ChainMidi(channel=0)),
        Chain(name="b", midi=ChainMidi(channel=0)),
    ])
    result = validate_song(song, catalog=[])
    assert codes(result, "warnings") == set()


def test_note_thru_on_last_module_is_a_warning_not_an_error():
    catalog = [make_entry("foo@orhack", "orhack", "Foo", [])]
    slot = ModuleSlot(key="foo@orhack", note_thru=True)
    song = Song(name="x", program=0, chains=[Chain(name="pads", modules=[slot])])
    result = validate_song(song, catalog=catalog)
    assert "FINAL_NOTE_THRU" in codes(result, "warnings")
    assert "FINAL_NOTE_THRU" not in codes(result, "errors")


def test_note_thru_on_non_last_module_is_not_flagged():
    catalog = [make_entry("foo@orhack", "orhack", "Foo", [])]
    modules = [ModuleSlot(key="foo@orhack", note_thru=True), ModuleSlot(key="foo@orhack")]
    song = Song(name="x", program=0, chains=[Chain(name="pads", modules=modules)])
    result = validate_song(song, catalog=catalog)
    assert codes(result, "warnings") == set()
