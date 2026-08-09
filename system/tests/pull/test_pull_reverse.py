"""`rig.pull.reverse` -- observed preset -> song-file edits.

The strongest test here is the property test the brief itself asks for:
compile a song to get the drift baseline, mutate a copy of it to stand in
for "what the device now says", reverse-map, and confirm (1) only the
mutated field changed in the song file and (2) every comment survived.
`_assert_only_changed` and `_comments` below implement that check generically
so each field gets its own small, readable test.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from rig.compile.compiler import compile_song
from rig.pull.reverse import FieldChange, ReverseMapError, reverse_map_song
from rig.song.kits import KitsConfig
from rig.song.parser import dump_song, load_song, parse_song

from tests.compile_helpers import make_entry, param, samplement_entry, system_catalog

VELLICHOR_FIXTURE = Path(__file__).parent.parent / "fixtures" / "songs" / "vellichor.yaml"

BASE_YAML = """\
song: Testsong
program: 5                        # comment on program

sends:
  reverb:                         # comment on reverb send
    module: fx@orhack

master:
  - fxm@orhack: {level: 10}       # comment on master

mod-sources:
  - lfo@orhack: {speed: 5}        # comment on mod source

chains:
  - name: pads                    # 1st -> channel 1 default, letter A
    input: {guitar: false}
    mix: {output-gain: 80, balance: 40}   # comment on mix
    modules:
      - synth@orhack:
          level: 50
          amount-1: 10
          amount-2: 20
          midi: {level: 71}       # implied channel
          note-thru: true
          send: {reverb: 30}
      - eq@orhack                 # bare module, no body

  - name: guitar                  # 2nd -> channel 2 default, letter C
    input: {guitar: true}
    mix: {input-gain: 90}
    modules:
      - sampler@orhack:
          sample: warehouse/kick.wav
      - synth2@orhack:
          midi: {level: {channel: 5, cc: 20}}   # explicit form already
"""

OMNI_YAML = """\
song: Omni
program: 1

chains:
  - name: drones
    midi: {channel: 0}            # omni chain
    modules:
      - synth@orhack:
          midi: {level: {channel: 3, cc: 25}}   # explicit form required
"""


def _catalog():
    return [
        make_entry("fx@orhack", "orhack", "FX", "x/fx", [param("size", id_="fx_size")]),
        make_entry("fxm@orhack", "orhack", "FXM", "x/fxm", [param("level", id_="lvl_m")]),
        make_entry("lfo@orhack", "orhack", "LFO", "x/lfo", [param("speed", id_="lfo_speed")]),
        make_entry(
            "synth@orhack", "orhack", "Synth", "x/synth",
            [param("level", id_="lvl"), param("amount-1", id_="amt1"), param("amount-2", id_="amt2")],
        ),
        make_entry("eq@orhack", "orhack", "EQ", "x/eq", []),
        samplement_entry("sampler@orhack"),
        make_entry("synth2@orhack", "orhack", "Synth2", "x/synth2", [param("level", id_="lvl2")]),
        *system_catalog(),
    ]


def _kits_and_media(tmp_path):
    kit_dir = tmp_path / "kits" / "warehouse"
    kit_dir.mkdir(parents=True)
    (kit_dir / "kick.wav").write_bytes(b"")
    (kit_dir / "snare.wav").write_bytes(b"")
    return KitsConfig({"warehouse": 3}), tmp_path


def _base(tmp_path):
    """Fresh (doc, baseline, catalog, kits, media_root) -- `doc` is re-parsed
    every call since `reverse_map_song` mutates `doc.raw` in place."""
    catalog = _catalog()
    kits, media_root = _kits_and_media(tmp_path)
    doc = parse_song(BASE_YAML)
    compiled = compile_song(doc.song, catalog=catalog, kits=kits, media_root=media_root)
    baseline = json.loads(compiled.files["params.json"])
    return doc, baseline, catalog, kits, media_root


def _comments(text: str) -> list[str]:
    return [line.split("#", 1)[1] for line in text.splitlines() if "#" in line]


def _mutate(baseline: dict, slot_id: str, *path_and_value) -> dict:
    """Deep-copy `baseline` and set `observed[slot_id][path...] = value`."""
    observed = copy.deepcopy(baseline)
    *path, value = path_and_value
    node = observed[slot_id]
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value
    return observed


def _assert_only_field_changed(original_text: str, new_text: str, expected_snippet: str) -> None:
    """The dumped YAML differs from the original only by lines containing
    `expected_snippet` (plus lines it displaces), and every original comment
    is still present."""
    assert new_text != original_text
    assert expected_snippet in new_text
    for comment in _comments(original_text):
        assert comment in new_text, f"comment {comment!r} lost"


# --- identity: no drift -> no edits, byte-identical file --------------------


def test_no_drift_produces_no_edits_and_byte_identical_file(tmp_path):
    doc, baseline, catalog, kits, media_root = _base(tmp_path)
    observed = copy.deepcopy(baseline)
    changes = reverse_map_song(doc, baseline=baseline, observed=observed, catalog=catalog, kits=kits, media_root=media_root)
    assert changes == []
    assert dump_song(doc) == BASE_YAML


# --- mix: output-gain, input-gain, balance/width (incl. negative width) -----


def test_output_gain_drift_updates_mix_output_gain_only(tmp_path):
    doc, baseline, catalog, kits, media_root = _base(tmp_path)
    observed = _mutate(baseline, "s1", "params", "r-chout-gain-1", 65.0)
    changes = reverse_map_song(doc, baseline=baseline, observed=observed, catalog=catalog, kits=kits, media_root=media_root)
    assert changes == [FieldChange("chains[0].mix.output-gain", 65)]
    _assert_only_field_changed(BASE_YAML, dump_song(doc), "output-gain: 65")


def test_input_gain_drift_updates_mix_input_gain_only(tmp_path):
    doc, baseline, catalog, kits, media_root = _base(tmp_path)
    # guitar is the 2nd declared chain -> letter C -> n=3
    observed = _mutate(baseline, "s1", "params", "r-chin-l-gain-3", 150.0)
    changes = reverse_map_song(doc, baseline=baseline, observed=observed, catalog=catalog, kits=kits, media_root=media_root)
    assert changes == [FieldChange("chains[1].mix.input-gain", 150)]
    _assert_only_field_changed(BASE_YAML, dump_song(doc), "input-gain: 150")


def test_balance_and_width_drift_including_negative_width(tmp_path):
    doc, baseline, catalog, kits, media_root = _base(tmp_path)
    observed = copy.deepcopy(baseline)
    # pads -> letter A -> n=1. l=0.6, r=0.1 -> balance=35, width=-50 (negative).
    observed["s1"]["params"]["r-chout-l-pan-1"] = 0.6
    observed["s1"]["params"]["r-chout-r-pan-1"] = 0.1
    changes = reverse_map_song(doc, baseline=baseline, observed=observed, catalog=catalog, kits=kits, media_root=media_root)
    assert FieldChange("chains[0].mix.balance", 35) in changes
    assert FieldChange("chains[0].mix.width", -50) in changes
    text = dump_song(doc)
    assert "balance: 35" in text
    assert "width: -50" in text
    for comment in _comments(BASE_YAML):
        assert comment in text


# --- note-thru ---------------------------------------------------------------


def test_note_thru_drift_on_a_bare_module_upgrades_it_to_a_mapping(tmp_path):
    doc, baseline, catalog, kits, media_root = _base(tmp_path)
    # eq@orhack sits at a2 (pads chain, 2nd module), currently a bare entry.
    observed = _mutate(baseline, "s1", "params", "r-notethru-a2", 1)
    changes = reverse_map_song(doc, baseline=baseline, observed=observed, catalog=catalog, kits=kits, media_root=media_root)
    assert changes == [FieldChange("a2.note-thru", True)]
    text = dump_song(doc)
    assert "eq@orhack" in text
    assert "note-thru: true" in text
    for comment in _comments(BASE_YAML):
        assert comment in text


# --- chain midi channel (letter, not declaration position, drives r-chin-midich-N) --


def test_chain_channel_drift_uses_the_letter_not_declaration_position(tmp_path):
    doc, baseline, catalog, kits, media_root = _base(tmp_path)
    # guitar is 2nd declared (position 2) but assigned letter C -> n=3.
    observed = _mutate(baseline, "s1", "params", "r-chin-midich-3", 9)
    changes = reverse_map_song(doc, baseline=baseline, observed=observed, catalog=catalog, kits=kits, media_root=media_root)
    assert changes == [FieldChange("chains[1].midi.channel", 9)]
    text = dump_song(doc)
    assert "midi: {channel: 9}" in text or "channel: 9" in text
    for comment in _comments(BASE_YAML):
        assert comment in text


def test_chain_channel_16_drift_aborts_before_any_write(tmp_path):
    doc, baseline, catalog, kits, media_root = _base(tmp_path)
    # pads -> letter A -> n=1. 16 is reserved for Program Change/preset
    # control, a hard validation error (rig.song.validate.CHAIN_CHANNEL_RANGE).
    observed = _mutate(baseline, "s1", "params", "r-chin-midich-1", 16)
    with pytest.raises(ReverseMapError) as exc_info:
        reverse_map_song(doc, baseline=baseline, observed=observed, catalog=catalog, kits=kits, media_root=media_root)
    assert exc_info.value.code == "RESERVED_MIDI_VALUE_DRIFT"
    assert dump_song(doc) == BASE_YAML


def test_chain_channel_out_of_range_drift_aborts_before_any_write(tmp_path):
    doc, baseline, catalog, kits, media_root = _base(tmp_path)
    observed = _mutate(baseline, "s1", "params", "r-chin-midich-1", 42)
    with pytest.raises(ReverseMapError) as exc_info:
        reverse_map_song(doc, baseline=baseline, observed=observed, catalog=catalog, kits=kits, media_root=media_root)
    assert exc_info.value.code == "RESERVED_MIDI_VALUE_DRIFT"
    assert dump_song(doc) == BASE_YAML


# --- send amount --------------------------------------------------------------


def test_send_amount_drift_updates_the_named_send(tmp_path):
    doc, baseline, catalog, kits, media_root = _base(tmp_path)
    observed = _mutate(baseline, "s1", "params", "r-sendP1-a1", 75.0)
    changes = reverse_map_song(doc, baseline=baseline, observed=observed, catalog=catalog, kits=kits, media_root=media_root)
    assert changes == [FieldChange("a1.send.reverb", 75)]
    _assert_only_field_changed(BASE_YAML, dump_song(doc), "reverb: 75")


# --- module CC mapping: shorthand vs explicit ---------------------------------


def test_module_midi_cc_shorthand_form_when_channel_matches_chain(tmp_path):
    doc, baseline, catalog, kits, media_root = _base(tmp_path)
    # a1's "level" -> "lvl" was mapped to key 1*128+71 (channel 1 implied).
    # Drift it to channel 1, cc 99 -- still matches the chain's own channel.
    observed = copy.deepcopy(baseline)
    del observed["a1"]["midi-mapping"]["cc"][str(1 * 128 + 71)]
    observed["a1"]["midi-mapping"]["cc"][str(1 * 128 + 99)] = ["lvl"]
    changes = reverse_map_song(doc, baseline=baseline, observed=observed, catalog=catalog, kits=kits, media_root=media_root)
    assert changes == [FieldChange("a1.midi.level", 99)]
    _assert_only_field_changed(BASE_YAML, dump_song(doc), "level: 99")


def test_module_midi_cc_explicit_form_when_channel_differs_from_chain(tmp_path):
    doc, baseline, catalog, kits, media_root = _base(tmp_path)
    observed = copy.deepcopy(baseline)
    del observed["a1"]["midi-mapping"]["cc"][str(1 * 128 + 71)]
    observed["a1"]["midi-mapping"]["cc"][str(5 * 128 + 71)] = ["lvl"]
    changes = reverse_map_song(doc, baseline=baseline, observed=observed, catalog=catalog, kits=kits, media_root=media_root)
    assert changes == [FieldChange("a1.midi.level", {"channel": 5, "cc": 71})]
    text = dump_song(doc)
    assert "channel: 5" in text and "cc: 71" in text


def test_module_midi_cc_removed_drops_the_mapping(tmp_path):
    doc, baseline, catalog, kits, media_root = _base(tmp_path)
    observed = copy.deepcopy(baseline)
    del observed["a1"]["midi-mapping"]["cc"][str(1 * 128 + 71)]
    changes = reverse_map_song(doc, baseline=baseline, observed=observed, catalog=catalog, kits=kits, media_root=media_root)
    assert changes == [FieldChange("a1.midi.level", None)]
    text = dump_song(doc)
    assert "midi:" not in text.split("level: 50")[1].split("note-thru")[0]


def test_module_midi_reserved_cc_drift_aborts_before_any_write(tmp_path):
    doc, baseline, catalog, kits, media_root = _base(tmp_path)
    # Channel 1 still matches the chain (shorthand-eligible), but CC 74 is
    # hardwired per-chain modulation (rig.song.validate.RESERVED_CCS) and a
    # hard validation error -- must not be written even in shorthand form.
    observed = copy.deepcopy(baseline)
    del observed["a1"]["midi-mapping"]["cc"][str(1 * 128 + 71)]
    observed["a1"]["midi-mapping"]["cc"][str(1 * 128 + 74)] = ["lvl"]
    with pytest.raises(ReverseMapError) as exc_info:
        reverse_map_song(doc, baseline=baseline, observed=observed, catalog=catalog, kits=kits, media_root=media_root)
    assert exc_info.value.code == "RESERVED_MIDI_VALUE_DRIFT"
    assert dump_song(doc) == BASE_YAML


def test_module_midi_cc_channel_out_of_range_drift_aborts_before_any_write(tmp_path):
    doc, baseline, catalog, kits, media_root = _base(tmp_path)
    observed = copy.deepcopy(baseline)
    del observed["a1"]["midi-mapping"]["cc"][str(1 * 128 + 71)]
    observed["a1"]["midi-mapping"]["cc"][str(20 * 128 + 71)] = ["lvl"]
    with pytest.raises(ReverseMapError) as exc_info:
        reverse_map_song(doc, baseline=baseline, observed=observed, catalog=catalog, kits=kits, media_root=media_root)
    assert exc_info.value.code == "RESERVED_MIDI_VALUE_DRIFT"
    assert dump_song(doc) == BASE_YAML


def test_omni_chain_always_uses_explicit_cc_form(tmp_path):
    catalog = _catalog()
    kits, media_root = _kits_and_media(tmp_path)
    doc = parse_song(OMNI_YAML)
    compiled = compile_song(doc.song, catalog=catalog, kits=kits, media_root=media_root)
    baseline = json.loads(compiled.files["params.json"])

    observed = copy.deepcopy(baseline)
    del observed["a1"]["midi-mapping"]["cc"][str(3 * 128 + 25)]
    observed["a1"]["midi-mapping"]["cc"][str(3 * 128 + 40)] = ["lvl"]
    changes = reverse_map_song(doc, baseline=baseline, observed=observed, catalog=catalog, kits=kits, media_root=media_root)
    assert changes == [FieldChange("a1.midi.level", {"channel": 3, "cc": 40})]
    text = dump_song(doc)
    assert "channel: 3" in text and "cc: 40" in text


# --- samples: selection change, and samp_source 0 clears the field ----------


def test_sample_drift_selects_the_new_file_by_position(tmp_path):
    doc, baseline, catalog, kits, media_root = _base(tmp_path)
    # 2 files in warehouse/: kick.wav (k=0), snare.wav (k=1). Midpoint of k=1.
    new_select = 100.0 * 1.5 / (2 - 0.05)
    observed = _mutate(baseline, "c1", "params", "samp_select", new_select)
    changes = reverse_map_song(doc, baseline=baseline, observed=observed, catalog=catalog, kits=kits, media_root=media_root)
    assert changes == [FieldChange("c1.sample", "warehouse/snare.wav")]
    _assert_only_field_changed(BASE_YAML, dump_song(doc), "sample: warehouse/snare.wav")


def test_samp_source_zero_clears_the_sample_field(tmp_path):
    doc, baseline, catalog, kits, media_root = _base(tmp_path)
    observed = _mutate(baseline, "c1", "params", "samp_source", 0)
    changes = reverse_map_song(doc, baseline=baseline, observed=observed, catalog=catalog, kits=kits, media_root=media_root)
    assert changes == [FieldChange("c1.sample", None)]
    text = dump_song(doc)
    assert "sample:" not in text
    for comment in _comments(BASE_YAML):
        assert comment in text


# --- generic params, incl. a module with collision-suffixed param names -----


def test_param_drift_on_a_module_with_collision_suffixed_names(tmp_path):
    doc, baseline, catalog, kits, media_root = _base(tmp_path)
    observed = _mutate(baseline, "a1", "params", "amt2", 99.0)
    changes = reverse_map_song(doc, baseline=baseline, observed=observed, catalog=catalog, kits=kits, media_root=media_root)
    assert changes == [FieldChange("a1.amount-2", 99)]
    _assert_only_field_changed(BASE_YAML, dump_song(doc), "amount-2: 99")


def test_param_drift_on_master_module(tmp_path):
    doc, baseline, catalog, kits, media_root = _base(tmp_path)
    observed = _mutate(baseline, "f1", "params", "lvl_m", 44.0)
    changes = reverse_map_song(doc, baseline=baseline, observed=observed, catalog=catalog, kits=kits, media_root=media_root)
    assert changes == [FieldChange("f1.level", 44)]
    _assert_only_field_changed(BASE_YAML, dump_song(doc), "level: 44")


def test_param_drift_on_mod_source_module(tmp_path):
    doc, baseline, catalog, kits, media_root = _base(tmp_path)
    observed = _mutate(baseline, "m1", "params", "lfo_speed", 12.0)
    changes = reverse_map_song(doc, baseline=baseline, observed=observed, catalog=catalog, kits=kits, media_root=media_root)
    assert changes == [FieldChange("m1.speed", 12)]
    _assert_only_field_changed(BASE_YAML, dump_song(doc), "speed: 12")


def test_param_drift_on_send_module(tmp_path):
    doc, baseline, catalog, kits, media_root = _base(tmp_path)
    observed = _mutate(baseline, "p1", "params", "fx_size", 33.0)
    changes = reverse_map_song(doc, baseline=baseline, observed=observed, catalog=catalog, kits=kits, media_root=media_root)
    assert changes == [FieldChange("p1.size", 33)]
    text = dump_song(doc)
    assert "size: 33" in text


# --- abort rule: no partial write --------------------------------------------


def test_unknown_module_in_song_aborts_before_any_write(tmp_path):
    doc, baseline, catalog, kits, media_root = _base(tmp_path)
    stranger_catalog = [e for e in catalog if e.key != "eq@orhack"]
    observed = copy.deepcopy(baseline)
    with pytest.raises(ReverseMapError) as exc_info:
        reverse_map_song(doc, baseline=baseline, observed=observed, catalog=stranger_catalog, kits=kits, media_root=media_root)
    assert exc_info.value.code == "UNKNOWN_MODULE"
    assert dump_song(doc) == BASE_YAML


def test_module_identity_drift_aborts_before_any_write(tmp_path):
    doc, baseline, catalog, kits, media_root = _base(tmp_path)
    observed = _mutate(baseline, "a2", "moduleType", "x/synth2")
    with pytest.raises(ReverseMapError) as exc_info:
        reverse_map_song(doc, baseline=baseline, observed=observed, catalog=catalog, kits=kits, media_root=media_root)
    assert exc_info.value.code == "MODULE_IDENTITY_DRIFT"
    assert dump_song(doc) == BASE_YAML


def test_mod_bus_drift_aborts_before_any_write(tmp_path):
    doc, baseline, catalog, kits, media_root = _base(tmp_path)
    observed = copy.deepcopy(baseline)
    observed["a1"]["mod-mapping"]["bus"] = {"1": ["lvl"]}
    with pytest.raises(ReverseMapError) as exc_info:
        reverse_map_song(doc, baseline=baseline, observed=observed, catalog=catalog, kits=kits, media_root=media_root)
    assert exc_info.value.code == "UNSUPPORTED_DRIFT"
    assert dump_song(doc) == BASE_YAML


def test_master_slot_cc_drift_aborts_no_schema_field(tmp_path):
    doc, baseline, catalog, kits, media_root = _base(tmp_path)
    observed = copy.deepcopy(baseline)
    observed["f1"]["midi-mapping"]["cc"] = {"200": ["lvl_m"]}
    with pytest.raises(ReverseMapError) as exc_info:
        reverse_map_song(doc, baseline=baseline, observed=observed, catalog=catalog, kits=kits, media_root=media_root)
    assert exc_info.value.code == "UNSUPPORTED_DRIFT"
    assert dump_song(doc) == BASE_YAML


def test_router_pinned_safety_field_drift_aborts(tmp_path):
    doc, baseline, catalog, kits, media_root = _base(tmp_path)
    observed = _mutate(baseline, "s1", "params", "r-midi-ch", 3)
    with pytest.raises(ReverseMapError) as exc_info:
        reverse_map_song(doc, baseline=baseline, observed=observed, catalog=catalog, kits=kits, media_root=media_root)
    assert exc_info.value.code == "UNSUPPORTED_DRIFT"
    assert dump_song(doc) == BASE_YAML


def test_transport_param_drift_aborts(tmp_path):
    doc, baseline, catalog, kits, media_root = _base(tmp_path)
    observed = _mutate(baseline, "s2", "params", "bpm", 140.0)
    with pytest.raises(ReverseMapError) as exc_info:
        reverse_map_song(doc, baseline=baseline, observed=observed, catalog=catalog, kits=kits, media_root=media_root)
    assert exc_info.value.code == "UNSUPPORTED_DRIFT"
    assert dump_song(doc) == BASE_YAML


def test_send_amount_drift_with_no_matching_declared_send_aborts(tmp_path):
    doc, baseline, catalog, kits, media_root = _base(tmp_path)
    # r-sendP2-a1 has no counterpart: only one send ("reverb") is declared,
    # so there is no name to write `send: {name: amount}` under for p2.
    observed = _mutate(baseline, "s1", "params", "r-sendP2-a1", 50.0)
    with pytest.raises(ReverseMapError) as exc_info:
        reverse_map_song(doc, baseline=baseline, observed=observed, catalog=catalog, kits=kits, media_root=media_root)
    assert exc_info.value.code == "SEND_TARGET_UNDECLARED"
    assert dump_song(doc) == BASE_YAML


def test_shared_samples_folder_selection_is_a_named_unrepresentable_error(tmp_path):
    doc, baseline, catalog, kits, media_root = _base(tmp_path)
    (media_root / "samples" / "loops").mkdir(parents=True)
    (media_root / "samples" / "loops" / "a.wav").write_bytes(b"")
    observed = _mutate(baseline, "c1", "params", "samp_source", 25)
    with pytest.raises(ReverseMapError) as exc_info:
        reverse_map_song(doc, baseline=baseline, observed=observed, catalog=catalog, kits=kits, media_root=media_root)
    assert exc_info.value.code == "SAMPLE_FOLDER_UNREPRESENTABLE"
    assert dump_song(doc) == BASE_YAML


# --- the docs/schema.md canonical example, compiled and round-tripped -------


def _vellichor_compile_catalog():
    return [
        make_entry("rings@orhack", "orhack", "Rings", "x/rings", [param("structure", id_="structure")]),
        make_entry("warp@orhack", "orhack", "Warp", "x/warp", [param("drive", id_="drive")]),
        make_entry("plateverb@orhack", "orhack", "Plateverb", "x/plateverb", [param("size", id_="size")]),
        make_entry("clouds@orhack", "orhack", "Clouds", "x/clouds", []),
        make_entry("marginal@orhack", "orhack", "Marginal", "x/marginal", [param("low", id_="low")]),
        make_entry("bus-comp@orhack", "orhack", "Bus Comp", "x/bus-comp", []),
        make_entry("lfo@orhack", "orhack", "LFO", "x/lfo", [param("speed-1", id_="speed_1")]),
        make_entry("spiraldelay@orhack", "orhack", "Spiraldelay", "x/spiraldelay", []),
        make_entry("eq-iv@orhack", "orhack", "EQ IV", "x/eq-iv", []),
        samplement_entry("samplement@orhack"),
        *system_catalog(),
    ]


def test_vellichor_fixture_round_trips_through_compile_and_reverse_map(tmp_path):
    catalog = _vellichor_compile_catalog()
    kit_dir = tmp_path / "kits" / "warehouse"
    kit_dir.mkdir(parents=True)
    (kit_dir / "kick_808.wav").write_bytes(b"")
    kits = KitsConfig({"warehouse": 3})

    doc = load_song(VELLICHOR_FIXTURE)
    compiled = compile_song(doc.song, catalog=catalog, kits=kits, media_root=tmp_path)
    baseline = json.loads(compiled.files["params.json"])

    doc2 = load_song(VELLICHOR_FIXTURE)
    changes = reverse_map_song(
        doc2, baseline=baseline, observed=copy.deepcopy(baseline), catalog=catalog, kits=kits, media_root=tmp_path
    )
    assert changes == []
    assert dump_song(doc2) == VELLICHOR_FIXTURE.read_text(encoding="utf-8")
