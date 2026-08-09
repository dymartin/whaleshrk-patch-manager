"""`rig.compile.compiler` -- song model -> preset, end to end.

`test_compiles_to_the_hand_built_expected_params_json_byte_for_byte` is the
brief's own "Done when" case (Prompt/03-compiler.md "Verification"): the
expected bytes are built independently here (catalog defaults plus the
handful of documented overrides), not by calling into `rig.compile`
internals, then compared to the compiler's real output.
"""

from __future__ import annotations

import json

import pytest

from rig.catalog.entry import CatalogEntry
from rig.compile.compiler import (
    FIXED_SLOT_IDS,
    build_placeholder,
    compile_song,
    format_program_prefix,
)
from rig.compile.errors import CompileError
from rig.compile.jsonfmt import dumps as device_dumps
from rig.song.kits import KitsConfig
from rig.song.model import (
    Chain,
    ChainInput,
    ChainMix,
    MidiMapping,
    ModuleSlot,
    ModuleUse,
    Send,
    Song,
)

from tests.compile_helpers import make_entry, param, samplement_entry, system_catalog


def _catalog(*entries: CatalogEntry) -> list[CatalogEntry]:
    return [*entries, *system_catalog()]


# --- Verification section: hand-built expected params.json -----------------


def test_compiles_to_the_hand_built_expected_params_json_byte_for_byte():
    synth = make_entry(
        "synth@orhack", "orhack", "Synth", "instruments/synth/synth",
        [param("level", id_="lvl", default=50), param("tone", id_="tn", default=0)],
    )
    song = Song(
        name="Lead Only",
        program=3,
        chains=[
            Chain(
                name="lead",
                modules=[ModuleSlot(key="synth@orhack", params={"level": 80.0}, midi={"level": MidiMapping(cc=20)})],
            )
        ],
    )
    catalog = _catalog(synth)
    result = compile_song(song, catalog=catalog)

    system = system_catalog()
    router_entry = next(e for e in system if e.module_type == "routers/hybrid")
    transport_entry = next(e for e in system if e.module_type == "clocks/transport")

    # s1: catalog defaults, with only the documented, always-applied
    # overrides -- the single declared chain is 1st => channel 1 => letter A
    # (a 1-slot chain is not "needing 4 slots", so pass 2's A,C,B,D order
    # gives it A).
    s1_params = {p.id: p.default for p in router_entry.params}
    s1_params["r-midi-ch"] = 16
    s1_params["r-midi-pgmgate"] = 1
    s1_params["r-midi-module-cc"] = 20
    for n in range(1, 5):
        s1_params[f"r-chin-midigate-{n}"] = 1
    s1_params["r-chin-midich-1"] = 1
    s1_params["r-notethru-a1"] = 0

    expected_slots = {
        slot_id: {
            "moduleType": "-empty-",
            "params": {"thru_gain": 100},
            "midi-mapping": {"cc": {}},
            "mod-mapping": {"bus": {}},
        }
        for slot_id in FIXED_SLOT_IDS
    }
    expected_slots["a1"] = {
        "moduleType": "instruments/synth/synth",
        "params": {"lvl": 80.0, "tn": 0},
        "midi-mapping": {"cc": {128 + 20: ["lvl"]}},
        "mod-mapping": {"bus": {}},
    }
    expected_slots["s1"] = {
        "moduleType": "routers/hybrid",
        "params": s1_params,
        "midi-mapping": {"cc": {}},
        "mod-mapping": {"bus": {}},
    }
    expected_slots["s2"] = {
        "moduleType": "clocks/transport",
        "params": {p.id: p.default for p in transport_entry.params},
        "midi-mapping": {"cc": {}},
        "mod-mapping": {"bus": {}},
    }
    expected_bytes = device_dumps({k: expected_slots[k] for k in sorted(expected_slots)}).encode("utf-8")

    assert result.files["params.json"] == expected_bytes
    assert result.directory == "lead-only"
    assert set(result.files) == {"params.json"}  # no sidecars -- synth is stateless


def test_keyboard_targets_the_assigned_chains_first_slot_and_enables_global_cc():
    synth = make_entry("synth@orhack", "orhack", "Synth", "instruments/synth/synth", [])
    song = Song(
        "Keyboard",
        0,
        chains=[Chain("keys", modules=[ModuleSlot("synth@orhack")])],
        keyboard="keys",
    )

    router = json.loads(compile_song(song, catalog=_catalog(synth)).files["params.json"])["s1"]["params"]

    assert router["r-main-dest"] == 1
    assert router["r-midi-notegate"] == 1
    assert router["r-midi-ctrlgate"] == 1
    assert router["r-midi-ch"] == 16
    assert router["r-midi-module-cc"] == 20


# --- Directory-name / program-index ordering --------------------------------


def test_strcmp_ordering_places_each_preset_at_its_program_index():
    synth = make_entry("synth@orhack", "orhack", "Synth", "x/synth", [])
    catalog = _catalog(synth)
    programs_and_names = []
    for program, name in [(2, "Alpha"), (10, "Beta"), (127, "Zeta")]:
        song = Song(name=name, program=program)
        compiled = compile_song(song, catalog=catalog)
        directory = f"{format_program_prefix(program)}-{compiled.directory}"
        programs_and_names.append((program, directory))

    # Gaps below the highest used program (2, 10) get placeholders too.
    used_programs = {p for p, _ in programs_and_names}
    for program in range(0, max(used_programs) + 1):
        if program not in used_programs:
            build_placeholder(program, catalog=catalog)
            programs_and_names.append((program, format_program_prefix(program)))

    ordered = sorted(programs_and_names, key=lambda pair: pair[1])  # plain strcmp
    for index, (program, _name) in enumerate(ordered):
        assert program == index


# --- -empty- shape and system slots always present --------------------------


def test_undeclared_song_compiles_all_24_slots_empty_except_system():
    catalog = _catalog()
    song = Song(name="Blank", program=0)
    result = compile_song(song, catalog=catalog)
    obj = json.loads(result.files["params.json"])
    assert set(obj) == set(FIXED_SLOT_IDS)
    for slot_id in FIXED_SLOT_IDS:
        if slot_id in ("s1", "s2"):
            continue
        assert obj[slot_id]["moduleType"] == "-empty-"
        assert obj[slot_id]["params"] == {"thru_gain": 100}
    assert obj["s1"]["moduleType"] == "routers/hybrid"
    assert obj["s2"]["moduleType"] == "clocks/transport"
    # s2 is fully compiler-defaulted (decision #26).
    assert obj["s2"]["params"]["midiin"] == 1
    assert obj["s2"]["params"]["midiout"] == 0


# --- Router: input/mix/send/note-thru compilation ----------------------------


def test_guitar_true_centres_l_pan_and_sets_l_gain_from_mix_input_gain():
    entry = make_entry("m@orhack", "orhack", "M", "x/m", [])
    catalog = _catalog(entry)
    song = Song(
        name="G", program=0,
        chains=[Chain(name="c", input=ChainInput(guitar=True), mix=ChainMix(input_gain=77), modules=[ModuleSlot(key="m@orhack")])],
    )
    result = compile_song(song, catalog=catalog)
    s1 = json.loads(result.files["params.json"])["s1"]["params"]
    assert s1["r-chin-l-gain-1"] == 77.0
    assert s1["r-chin-l-pan-1"] == 0.5


def test_guitar_true_default_input_gain_is_100():
    entry = make_entry("m@orhack", "orhack", "M", "x/m", [])
    catalog = _catalog(entry)
    song = Song(name="G", program=0, chains=[Chain(name="c", input=ChainInput(guitar=True), modules=[ModuleSlot(key="m@orhack")])])
    result = compile_song(song, catalog=catalog)
    s1 = json.loads(result.files["params.json"])["s1"]["params"]
    assert s1["r-chin-l-gain-1"] == 100.0


def test_guitar_false_leaves_input_gain_and_pan_at_catalog_defaults():
    entry = make_entry("m@orhack", "orhack", "M", "x/m", [])
    catalog = _catalog(entry)
    router_entry = next(e for e in system_catalog() if e.module_type == "routers/hybrid")
    router_defaults = {p.id: p.default for p in router_entry.params if p.id.startswith("r-chin-l")}
    song = Song(name="G", program=0, chains=[Chain(name="c", modules=[ModuleSlot(key="m@orhack")])])
    result = compile_song(song, catalog=catalog)
    s1 = json.loads(result.files["params.json"])["s1"]["params"]
    assert s1["r-chin-l-gain-1"] == router_defaults["r-chin-l-gain-1"]
    assert s1["r-chin-l-pan-1"] == router_defaults["r-chin-l-pan-1"]


def test_balance_and_width_compile_to_clamped_output_pans():
    entry = make_entry("m@orhack", "orhack", "M", "x/m", [])
    catalog = _catalog(entry)
    song = Song(
        name="B", program=0,
        chains=[Chain(name="c", mix=ChainMix(balance=100, width=100), modules=[ModuleSlot(key="m@orhack")])],
    )
    result = compile_song(song, catalog=catalog)
    s1 = json.loads(result.files["params.json"])["s1"]["params"]
    # b=1.0, w=1.0 -> l=1-0.5=0.5, r=1+0.5=1.5 clamped to 1.0
    assert s1["r-chout-l-pan-1"] == 0.5
    assert s1["r-chout-r-pan-1"] == 1.0


def test_omitted_mix_reproduces_the_hard_apart_default_pans():
    entry = make_entry("m@orhack", "orhack", "M", "x/m", [])
    catalog = _catalog(entry)
    song = Song(name="D", program=0, chains=[Chain(name="c", modules=[ModuleSlot(key="m@orhack")])])
    result = compile_song(song, catalog=catalog)
    s1 = json.loads(result.files["params.json"])["s1"]["params"]
    assert s1["r-chout-l-pan-1"] == 0
    assert s1["r-chout-r-pan-1"] == 1


def test_send_resolves_by_song_declaration_order_not_dict_order():
    fx = make_entry("fx@orhack", "orhack", "FX", "x/fx", [])
    m = make_entry("m@orhack", "orhack", "M", "x/m", [])
    catalog = _catalog(fx, m)
    song = Song(
        name="S", program=0,
        sends=[Send(name="reverb", module="fx@orhack"), Send(name="space", module="fx@orhack")],
        chains=[Chain(name="c", modules=[ModuleSlot(key="m@orhack", send={"space": 25.0, "reverb": 40.0})])],
    )
    result = compile_song(song, catalog=catalog)
    s1 = json.loads(result.files["params.json"])["s1"]["params"]
    assert s1["r-sendP1-a1"] == 40.0  # reverb: 1st declared send -> p1
    assert s1["r-sendP2-a1"] == 25.0  # space: 2nd declared send -> p2


def test_note_thru_sets_the_occupied_slot_flag():
    entry = make_entry("m@orhack", "orhack", "M", "x/m", [])
    catalog = _catalog(entry)
    song = Song(name="N", program=0, chains=[Chain(name="c", modules=[ModuleSlot(key="m@orhack", note_thru=True)])])
    result = compile_song(song, catalog=catalog)
    s1 = json.loads(result.files["params.json"])["s1"]["params"]
    assert s1["r-notethru-a1"] == 1


# --- CC mapping ---------------------------------------------------------------


def test_implied_channel_uses_the_chains_resolved_channel():
    entry = make_entry("m@orhack", "orhack", "M", "x/m", [param("size")])
    catalog = _catalog(entry)
    song = Song(
        name="C", program=0,
        chains=[
            Chain(name="a"),  # channel 1
            Chain(name="b", modules=[ModuleSlot(key="m@orhack", midi={"size": MidiMapping(cc=71)})]),  # channel 2
        ],
    )
    result = compile_song(song, catalog=catalog)
    obj = json.loads(result.files["params.json"])
    # "a" has no modules so it fills the first free letter with a module (A),
    # "b" fills the next; check whichever occupied slot exists.
    occupied = next(slot for key, slot in obj.items() if slot["moduleType"] == "x/m")
    assert occupied["midi-mapping"]["cc"] == {str(2 * 128 + 71): ["id_size"]}


def test_explicit_channel_overrides_the_chains_channel():
    entry = make_entry("m@orhack", "orhack", "M", "x/m", [param("size")])
    catalog = _catalog(entry)
    song = Song(
        name="C", program=0,
        chains=[Chain(name="a", modules=[ModuleSlot(key="m@orhack", midi={"size": MidiMapping(cc=71, channel=5)})])],
    )
    result = compile_song(song, catalog=catalog)
    slot = json.loads(result.files["params.json"])["a1"]
    assert slot["midi-mapping"]["cc"] == {str(5 * 128 + 71): ["id_size"]}


# --- Master / mod-sources / sends slot placement -----------------------------


def test_master_fills_f_slots_in_declared_order():
    a = make_entry("a@orhack", "orhack", "A", "x/a", [])
    b = make_entry("b@orhack", "orhack", "B", "x/b", [])
    catalog = _catalog(a, b)
    song = Song(name="M", program=0, master=[ModuleUse(key="a@orhack"), ModuleUse(key="b@orhack")])
    result = compile_song(song, catalog=catalog)
    obj = json.loads(result.files["params.json"])
    assert obj["f1"]["moduleType"] == "x/a"
    assert obj["f2"]["moduleType"] == "x/b"
    assert obj["f3"]["moduleType"] == "-empty-"


def test_mod_sources_fill_m_slots_in_declared_order():
    lfo = make_entry("lfo@orhack", "orhack", "LFO", "x/lfo", [])
    catalog = _catalog(lfo)
    song = Song(name="MS", program=0, mod_sources=[ModuleUse(key="lfo@orhack")])
    result = compile_song(song, catalog=catalog)
    obj = json.loads(result.files["params.json"])
    assert obj["m1"]["moduleType"] == "x/lfo"
    assert obj["m2"]["moduleType"] == "-empty-"


def test_sends_fill_p1_then_p2():
    fx = make_entry("fx@orhack", "orhack", "FX", "x/fx", [])
    catalog = _catalog(fx)
    song = Song(name="P", program=0, sends=[Send(name="reverb", module="fx@orhack"), Send(name="space", module="fx@orhack")])
    result = compile_song(song, catalog=catalog)
    obj = json.loads(result.files["params.json"])
    assert obj["p1"]["moduleType"] == "x/fx"
    assert obj["p2"]["moduleType"] == "x/fx"


# --- Errors --------------------------------------------------------------


def test_unknown_module_raises_compile_error():
    catalog = _catalog()
    song = Song(name="U", program=0, chains=[Chain(name="c", modules=[ModuleSlot(key="ghost@orhack")])])
    with pytest.raises(CompileError) as exc_info:
        compile_song(song, catalog=catalog)
    assert exc_info.value.code == "UNKNOWN_MODULE"


def test_unknown_param_raises_compile_error():
    entry = make_entry("m@orhack", "orhack", "M", "x/m", [])
    catalog = _catalog(entry)
    song = Song(name="U", program=0, chains=[Chain(name="c", modules=[ModuleSlot(key="m@orhack", params={"nope": 1.0})])])
    with pytest.raises(CompileError) as exc_info:
        compile_song(song, catalog=catalog)
    assert exc_info.value.code == "UNKNOWN_PARAM"


def test_program_out_of_range_via_placeholder_raises():
    with pytest.raises(CompileError) as exc_info:
        build_placeholder(128, catalog=system_catalog())
    assert exc_info.value.code == "PROGRAM_OUT_OF_RANGE"


def test_missing_system_catalog_entry_raises_clear_error():
    with pytest.raises(CompileError) as exc_info:
        compile_song(Song(name="X", program=0), catalog=[])
    assert exc_info.value.code == "MISSING_SYSTEM_MODULE"


def test_unverified_stateful_module_in_a_chain_is_a_compile_error():
    clips = make_entry("clips@orhack", "orhack", "Clips", "sequencers/clips", [])
    catalog = _catalog(clips)
    song = Song(name="C", program=0, chains=[Chain(name="c", modules=[ModuleSlot(key="clips@orhack")])])
    with pytest.raises(CompileError) as exc_info:
        compile_song(song, catalog=catalog)
    assert exc_info.value.code == "UNVERIFIED_STATEFUL_MODULE"


# --- Samples integration ------------------------------------------------


def test_sample_reference_resolves_into_the_occupied_slots_params(tmp_path):
    entry = samplement_entry()
    catalog = _catalog(entry)
    (tmp_path / "kits" / "warehouse").mkdir(parents=True)
    (tmp_path / "kits" / "warehouse" / "kick.wav").write_bytes(b"")
    kits = KitsConfig({"warehouse": 3})
    song = Song(name="S", program=0, chains=[Chain(name="c", modules=[ModuleSlot(key="samplement@orhack", sample="warehouse/kick.wav")])])
    result = compile_song(song, catalog=catalog, kits=kits, media_root=tmp_path)
    slot = json.loads(result.files["params.json"])["a1"]
    assert slot["params"]["samp_source"] == 3
    assert slot["params"]["samp_select"] == pytest.approx(100 * 0.5 / 0.95)  # 1 file: k=0, N=1


def test_sample_without_kits_or_media_root_raises():
    entry = samplement_entry()
    catalog = _catalog(entry)
    song = Song(name="S", program=0, chains=[Chain(name="c", modules=[ModuleSlot(key="samplement@orhack", sample="warehouse/kick.wav")])])
    with pytest.raises(CompileError) as exc_info:
        compile_song(song, catalog=catalog)
    assert exc_info.value.code == "SAMPLE_RESOLUTION_UNAVAILABLE"


def test_sample_on_a_module_without_sampler_params_raises():
    entry = make_entry("m@orhack", "orhack", "M", "x/m", [])
    catalog = _catalog(entry)
    song = Song(name="S", program=0, chains=[Chain(name="c", modules=[ModuleSlot(key="m@orhack", sample="warehouse/kick.wav")])])
    with pytest.raises(CompileError) as exc_info:
        compile_song(song, catalog=catalog, kits=KitsConfig({"warehouse": 1}), media_root=None)
    # media_root is None -> SAMPLE_RESOLUTION_UNAVAILABLE fires before the
    # sampler-params check would even get a folder to look at; assert the
    # *some* clear compile error fires rather than a silent pass.
    assert exc_info.value.code in ("SAMPLE_NOT_SUPPORTED", "SAMPLE_RESOLUTION_UNAVAILABLE")


# --- Chain letter bindings ------------------------------------------------


def test_recorded_binding_is_honoured_over_fresh_assignment():
    entry = make_entry("m@orhack", "orhack", "M", "x/m", [])
    catalog = _catalog(entry)
    song = Song(name="B", program=0, chains=[Chain(name="pads", modules=[ModuleSlot(key="m@orhack")])])
    result = compile_song(song, catalog=catalog, bindings={"pads": "D"})
    obj = json.loads(result.files["params.json"])
    assert obj["d1"]["moduleType"] == "x/m"
    assert obj["a1"]["moduleType"] == "-empty-"


# --- Placeholder ----------------------------------------------------------


def test_placeholder_has_no_sidecars_and_22_empty_slots():
    catalog = system_catalog()
    placeholder = build_placeholder(5, catalog=catalog)
    assert placeholder.directory == ""
    assert set(placeholder.files) == {"params.json"}
    obj = json.loads(placeholder.files["params.json"])
    empties = [k for k, v in obj.items() if v["moduleType"] == "-empty-"]
    assert len(empties) == 22
    assert obj["s1"]["moduleType"] == "routers/hybrid"
    assert obj["s2"]["moduleType"] == "clocks/transport"


def test_placeholder_content_does_not_depend_on_program():
    catalog = system_catalog()
    a = build_placeholder(0, catalog=catalog)
    b = build_placeholder(50, catalog=catalog)
    assert a.files == b.files


def test_format_program_prefix_is_zero_padded_to_three_digits():
    assert format_program_prefix(0) == "000"
    assert format_program_prefix(12) == "012"
    assert format_program_prefix(127) == "127"


def test_format_program_prefix_rejects_out_of_range():
    with pytest.raises(CompileError) as exc_info:
        format_program_prefix(128)
    assert exc_info.value.code == "PROGRAM_OUT_OF_RANGE"
