"""`rig.pull.adopt` -- minting a song from a card preset with no song file.

The strongest check here is round-trip fidelity: compile a hand-built `Song`
to get a realistic `params.json`, forget it was ever a song, adopt it, and
confirm recompiling the adopted result reproduces the same `params.json`
(modulo directory naming, which adoption does not own). That is what backs
docs/workflows/pull.md's adoption verification bullets -- "pushed
immediately, is recognised as managed" only holds if the round trip is
faithful.
"""

from __future__ import annotations

import json

import pytest

from rig.compile.compiler import compile_song
from rig.pull.adopt import adopt_preset
from rig.pull.reverse import ReverseMapError
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

from .compile_helpers import make_entry, param, samplement_entry, system_catalog


def _catalog():
    return [
        make_entry("rings@orhack", "orhack", "Rings", "x/rings", [param("structure", id_="struct")]),
        make_entry("warp@orhack", "orhack", "Warp", "x/warp", [param("drive", id_="drv")]),
        make_entry("plateverb@orhack", "orhack", "Plateverb", "x/plateverb", [param("size", id_="sz")]),
        make_entry("marginal@orhack", "orhack", "Marginal", "x/marginal", [param("low", id_="lo")]),
        make_entry("lfo@orhack", "orhack", "LFO", "x/lfo", [param("speed", id_="spd")]),
        samplement_entry("samplement@orhack"),
        *system_catalog(),
    ]


def _kits_and_media(tmp_path):
    kit_dir = tmp_path / "kits" / "warehouse"
    kit_dir.mkdir(parents=True)
    (kit_dir / "kick.wav").write_bytes(b"")
    (kit_dir / "snare.wav").write_bytes(b"")
    return KitsConfig({"warehouse": 3}), tmp_path


def _rich_song() -> Song:
    return Song(
        name="Vellichor",
        program=12,
        sends=[Send(name="reverb", module="plateverb@orhack", params={"size": 70})],
        master=[ModuleUse(key="marginal@orhack", params={"low": 40})],
        mod_sources=[ModuleUse(key="lfo@orhack", params={"speed": 30})],
        chains=[
            Chain(
                name="pads",
                input=ChainInput(guitar=False),
                mix=ChainMix(output_gain=80, balance=40),
                modules=[
                    ModuleSlot(
                        key="rings@orhack", params={"structure": 45},
                        midi={"structure": MidiMapping(cc=71)}, note_thru=True, send={"reverb": 40},
                    ),
                    ModuleSlot(key="warp@orhack", params={"drive": 30}),
                ],
            ),
            Chain(
                name="guitar",
                input=ChainInput(guitar=True),
                midi=ChainMidi(channel=5),
                mix=ChainMix(input_gain=90),
                modules=[ModuleSlot(key="samplement@orhack", sample="warehouse/kick.wav")],
            ),
        ],
    )


def _observed(tmp_path):
    catalog = _catalog()
    kits, media_root = _kits_and_media(tmp_path)
    song = _rich_song()
    compiled = compile_song(song, catalog=catalog, kits=kits, media_root=media_root)
    return json.loads(compiled.files["params.json"]), catalog, kits, media_root


def test_adopt_derives_program_from_a_recognised_prefix(tmp_path):
    observed, catalog, kits, media_root = _observed(tmp_path)
    adopted = adopt_preset("012-Vellichor", observed, catalog=catalog, kits=kits, media_root=media_root)
    assert adopted.program == 12
    assert adopted.song_id == "vellichor"


def test_adopt_assigns_next_free_program_for_an_unrecognised_prefix(tmp_path):
    observed, catalog, kits, media_root = _observed(tmp_path)
    adopted = adopt_preset("Mystery Preset", observed, catalog=catalog, kits=kits, media_root=media_root, used_programs={0, 1})
    assert adopted.program == 2
    assert adopted.song_id == "mystery-preset"


def test_adopt_dedupes_song_id_against_existing_songs(tmp_path):
    observed, catalog, kits, media_root = _observed(tmp_path)
    adopted = adopt_preset(
        "012-Vellichor", observed, catalog=catalog, kits=kits, media_root=media_root,
        existing_song_ids={"vellichor"}, used_programs={12},
    )
    assert adopted.song_id == "vellichor-2"
    assert adopted.program == 0  # 12 already used, no other prefix info


def test_adopt_derives_chain_and_send_names_from_module_keys_not_originals(tmp_path):
    # The device stores no names -- the adopted song must not resurrect
    # "pads"/"guitar"/"reverb", only what the catalog key implies.
    observed, catalog, kits, media_root = _observed(tmp_path)
    adopted = adopt_preset("012-Vellichor", observed, catalog=catalog, kits=kits, media_root=media_root)
    names = [c.name for c in adopted.doc.song.chains]
    assert names == ["rings", "samplement"]
    assert adopted.doc.song.sends[0].name == "plateverb"


def test_adopt_preserves_chain_letters_as_a_binding(tmp_path):
    observed, catalog, kits, media_root = _observed(tmp_path)
    adopted = adopt_preset("012-Vellichor", observed, catalog=catalog, kits=kits, media_root=media_root)
    assert adopted.bindings == {"rings": "A", "samplement": "C"}


def test_adopt_writes_explicit_channel_only_when_it_differs_from_position(tmp_path):
    observed, catalog, kits, media_root = _observed(tmp_path)
    adopted = adopt_preset("012-Vellichor", observed, catalog=catalog, kits=kits, media_root=media_root)
    song = adopted.doc.song
    assert song.chains[0].midi.channel is None  # position 1 == observed channel 1
    assert song.chains[1].midi.channel == 5  # explicit override on the device


def test_adopt_writes_sample_selection_not_the_default(tmp_path):
    observed, catalog, kits, media_root = _observed(tmp_path)
    adopted = adopt_preset("012-Vellichor", observed, catalog=catalog, kits=kits, media_root=media_root)
    sampler_slot = adopted.doc.song.chains[1].modules[0]
    assert sampler_slot.sample == "warehouse/kick.wav"


def test_adopt_omits_empty_chains_and_sends(tmp_path):
    observed, catalog, kits, media_root = _observed(tmp_path)
    adopted = adopt_preset("012-Vellichor", observed, catalog=catalog, kits=kits, media_root=media_root)
    assert len(adopted.doc.song.chains) == 2  # not 4 -- B and D are silent
    assert len(adopted.doc.song.sends) == 1  # not 2 -- p2 is silent


def test_adopt_round_trips_through_compile_byte_identically(tmp_path):
    observed, catalog, kits, media_root = _observed(tmp_path)
    adopted = adopt_preset("012-Vellichor", observed, catalog=catalog, kits=kits, media_root=media_root)

    recompiled = compile_song(
        adopted.doc.song, catalog=catalog, kits=kits, media_root=media_root, bindings=adopted.bindings
    )
    assert json.loads(recompiled.files["params.json"]) == observed


def test_adopt_refuses_an_unknown_module(tmp_path):
    observed, catalog, kits, media_root = _observed(tmp_path)
    observed["a1"]["moduleType"] = "instruments/synth/mystery-unknown"
    with pytest.raises(ReverseMapError) as exc:
        adopt_preset("012-Vellichor", observed, catalog=catalog, kits=kits, media_root=media_root)
    assert exc.value.code == "UNKNOWN_MODULE"


def test_adopt_refuses_mod_bus_routing(tmp_path):
    observed, catalog, kits, media_root = _observed(tmp_path)
    observed["a1"]["mod-mapping"] = {"bus": {"1": ["struct"]}}
    with pytest.raises(ReverseMapError) as exc:
        adopt_preset("012-Vellichor", observed, catalog=catalog, kits=kits, media_root=media_root)
    assert exc.value.code == "MOD_BUS_UNREPRESENTABLE"


def test_adopt_refuses_a_reserved_cc(tmp_path):
    observed, catalog, kits, media_root = _observed(tmp_path)
    observed["a1"]["midi-mapping"] = {"cc": {"1": ["struct"]}}  # CC 1 on channel 0 -> reserved CC 1
    with pytest.raises(ReverseMapError) as exc:
        adopt_preset("012-Vellichor", observed, catalog=catalog, kits=kits, media_root=media_root)
    assert exc.value.code == "RESERVED_MIDI_VALUE_DRIFT"


def test_adopt_refuses_a_gap_within_a_chain(tmp_path):
    # a1 occupied, a2 -empty-, a3 occupied -- the schema has no way to write
    # "skip this slot" in the middle of a chain's modules: list.
    observed, catalog, kits, media_root = _observed(tmp_path)
    observed["a3"] = dict(observed["a2"])  # move warp's occupant to a3
    observed["a2"] = {"moduleType": "-empty-", "params": {"thru_gain": 100}, "midi-mapping": {"cc": {}}, "mod-mapping": {"bus": {}}}
    with pytest.raises(ReverseMapError) as exc:
        adopt_preset("012-Vellichor", observed, catalog=catalog, kits=kits, media_root=media_root)
    assert exc.value.code == "UNREPRESENTABLE_SLOT_GAP"


def test_adopt_refuses_a_gap_in_sends(tmp_path):
    # p1 -empty-, p2 occupied -- 'sends:' has no index-0 placeholder either.
    observed, catalog, kits, media_root = _observed(tmp_path)
    observed["p2"] = dict(observed["p1"])
    observed["p1"] = {"moduleType": "-empty-", "params": {"thru_gain": 100}, "midi-mapping": {"cc": {}}, "mod-mapping": {"bus": {}}}
    with pytest.raises(ReverseMapError) as exc:
        adopt_preset("012-Vellichor", observed, catalog=catalog, kits=kits, media_root=media_root)
    assert exc.value.code == "UNREPRESENTABLE_SLOT_GAP"


def test_adopt_refuses_a_sample_from_the_shared_folder(tmp_path):
    observed, catalog, kits, media_root = _observed(tmp_path)
    observed["c1"]["params"]["samp_source"] = 25  # shared samples/ folder
    observed["c1"]["params"]["samp_select"] = 0.0
    with pytest.raises(ReverseMapError) as exc:
        adopt_preset("012-Vellichor", observed, catalog=catalog, kits=kits, media_root=media_root)
    assert exc.value.code == "SAMPLE_FOLDER_UNREPRESENTABLE"
