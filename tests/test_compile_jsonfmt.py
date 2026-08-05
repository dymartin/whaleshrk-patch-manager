"""`rig.compile.jsonfmt` -- ORAC's on-device params.json byte format.

`test_matches_the_shipped_init_preset_byte_for_byte` is the load-bearing
case: feeding the real, parsed `Init` preset back through `dumps` must
reproduce the exact bytes ORHACK itself wrote, which is what
`Prompt/03-compiler.md` means by "matches what the device itself writes".
"""

from __future__ import annotations

import json
from pathlib import Path

from rig.compile.jsonfmt import dumps

INIT_PARAMS = (
    Path(__file__).resolve().parent.parent
    / "fixtures"
    / "card"
    / "Patches"
    / "0RHACK"
    / "data"
    / "presets"
    / "Init"
    / "params.json"
)


def test_matches_the_shipped_init_preset_byte_for_byte():
    original = INIT_PARAMS.read_bytes()
    obj = json.loads(original)  # ordinary json.loads preserves key insertion order
    assert dumps(obj).encode("utf-8") == original


def test_whole_number_floats_render_without_a_decimal_point():
    assert dumps({"a": 100.0}) == '{\n\t"a":\t100\n}\n'


def test_fractional_floats_use_python_repr():
    assert dumps({"a": 25.641025641025642}) == '{\n\t"a":\t25.641025641025642\n}\n'


def test_negative_int_renders_plain():
    assert dumps({"samp_source": -1}) == '{\n\t"samp_source":\t-1\n}\n'


def test_empty_nested_dict_still_expands_onto_its_own_line():
    text = dumps({"cc": {}})
    assert text == '{\n\t"cc":\t{\n\t}\n}\n'


def test_key_order_is_insertion_order_not_sorted():
    text = dumps({"z": 1, "a": 2})
    assert text.index('"z"') < text.index('"a"')


def test_nested_list_of_strings():
    text = dumps({"cc": {"199": ["structure"]}})
    assert text == '{\n\t"cc":\t{\n\t\t"199":\t[\n\t\t\t"structure"\n\t\t]\n\t}\n}\n'
