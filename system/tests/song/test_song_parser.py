from __future__ import annotations

from pathlib import Path

import pytest

from rig.song.errors import SongParseError
from rig.song.model import MidiMapping, ModuleUse
from rig.song.parser import dump_song, load_song, parse_song

FIXTURE = Path(__file__).parent.parent / "fixtures" / "songs" / "vellichor.yaml"


def test_canonical_example_round_trips_byte_identically():
    text = FIXTURE.read_text(encoding="utf-8")
    doc = parse_song(text, source=str(FIXTURE))
    assert dump_song(doc) == text


def test_load_song_sets_path():
    doc = load_song(FIXTURE)
    assert doc.path == FIXTURE


def test_keyboard_parses_as_a_friendly_chain_name():
    song = parse_song("song: Test\nprogram: 0\nkeyboard: keys\n").song
    assert song.keyboard == "keys"


def test_keyboard_rejects_a_non_string():
    with pytest.raises(SongParseError, match="keyboard"):
        parse_song("song: Test\nprogram: 0\nkeyboard: 1\n")


def test_canonical_example_parses_into_the_song_model():
    doc = parse_song(FIXTURE.read_text(encoding="utf-8"))
    song = doc.song

    assert song.name == "Vellichor"
    assert song.program == 12

    assert [s.name for s in song.sends] == ["reverb", "space"]
    assert song.sends[0].module == "plateverb@orhack"
    assert song.sends[0].params == {"size": 70.0}
    assert song.sends[1].module == "clouds@orhack"
    assert song.sends[1].params == {}

    assert [m.key for m in song.master] == ["marginal@orhack", "bus-comp@orhack"]
    assert song.master[0].params == {"low": 40.0}
    assert song.master[1].params == {}

    assert [m.key for m in song.mod_sources] == ["lfo@orhack"]
    assert song.mod_sources[0].params == {"speed-1": 30.0}

    assert [c.name for c in song.chains] == ["pads", "guitar"]

    pads = song.chains[0]
    assert pads.input.guitar is False
    assert pads.midi.channel is None
    assert pads.mix.output_gain == 90.0
    assert pads.mix.balance == 50.0
    assert pads.mix.input_gain is None
    assert pads.mix.width is None
    assert [m.key for m in pads.modules] == [
        "rings@orhack",
        "warp@orhack",
        "spiraldelay@orhack",
        "eq-iv@orhack",
    ]

    rings = pads.modules[0]
    assert rings.params == {"structure": 45.0}
    assert rings.midi == {"structure": MidiMapping(cc=71, channel=None)}
    assert rings.note_thru is True
    assert rings.send == {}
    assert rings.sample is None

    warp1 = pads.modules[1]
    assert warp1.params == {"drive": 30.0}
    assert warp1.send == {"reverb": 40.0}

    spiraldelay = pads.modules[2]
    assert spiraldelay.params == {}
    assert spiraldelay.send == {"space": 25.0}

    eq = pads.modules[3]
    assert eq.params == {}
    assert eq.note_thru is False

    guitar = song.chains[1]
    assert guitar.input.guitar is True
    assert guitar.mix.input_gain == 100.0
    assert guitar.mix.output_gain == 100.0
    assert guitar.mix.balance == 50.0
    assert guitar.mix.width == 100.0
    assert [m.key for m in guitar.modules] == ["warp@orhack", "samplement@orhack"]
    assert guitar.modules[1].sample == "warehouse/kick_808.wav"


def test_explicit_channel_midi_mapping():
    text = """
song: Test
program: 0
chains:
  - name: pads
    modules:
      - foo@orhack:
          midi: { damping: { channel: 1, cc: 20 } }
"""
    doc = parse_song(text)
    mapping = doc.song.chains[0].modules[0].midi["damping"]
    assert mapping == MidiMapping(cc=20, channel=1)


def test_missing_song_name_is_a_parse_error():
    with pytest.raises(SongParseError, match="song"):
        parse_song("program: 0\n")


def test_missing_program_is_a_parse_error():
    with pytest.raises(SongParseError, match="program"):
        parse_song("song: Test\n")


def test_unknown_top_level_field_is_a_parse_error():
    with pytest.raises(SongParseError, match="s1"):
        parse_song("song: Test\nprogram: 0\ns1: { foo: bar }\n")


def test_unknown_chain_field_is_a_parse_error():
    text = """
song: Test
program: 0
chains:
  - name: pads
    tempo: 120
"""
    with pytest.raises(SongParseError, match="tempo"):
        parse_song(text)


def test_malformed_yaml_is_a_parse_error_not_a_ruamel_error():
    """A mistyped song file must arrive as the same refusal type as any other
    bad shape -- the CLI turns SongParseError into a coded message, and anything
    else reaches the musician as a traceback (Ruling #2)."""
    with pytest.raises(SongParseError, match="invalid YAML"):
        parse_song("song: Test\nchains: [unclosed\n", source="songs/broken.yaml")


def test_bare_module_use_has_no_params():
    text = """
song: Test
program: 0
master:
  - bus-comp@orhack
"""
    doc = parse_song(text)
    assert doc.song.master == [ModuleUse(key="bus-comp@orhack", params={})]


def test_non_finite_param_value_parses_without_error():
    """Parsing only checks shape; NON_FINITE_VALUE is validate.py's job."""
    text = """
song: Test
program: 0
chains:
  - name: pads
    modules:
      - foo@orhack:
          size: .inf
"""
    doc = parse_song(text)
    import math

    assert math.isinf(doc.song.chains[0].modules[0].params["size"])
