"""Parameter tuple parsing -- docs/catalog.md "Parameter derivation".

Shapes verified against real module.json content: the 6-tuple is universal
except `bool`, which uses a 4-tuple with implicit min/max (measured across
all 67 built-in module.json files, zero exceptions), plus one real 5-element
`bool` anomaly (candidate 163108, "vj-fm").
"""

import pytest

from rig.catalog.params import ParamParseError, parse_parameters


def test_standard_six_tuple():
    params = parse_parameters("Test", [["pct", "thru_gain", "Audio Thru Gain", 0, 100, 100]])
    assert len(params) == 1
    p = params[0]
    assert p.id == "thru_gain"
    assert p.label == "Audio Thru Gain"
    assert p.type == "pct"
    assert (p.min, p.max, p.default) == (0, 100, 100)
    assert p.name == "audio-thru-gain"


def test_bool_four_tuple_gets_implicit_min_max():
    params = parse_parameters("Test", [["bool", "wdelay_exprq", "Expr Quant", 1]])
    p = params[0]
    assert (p.min, p.max, p.default) == (0, 1, 1)


def test_bool_five_tuple_anomaly_uses_last_element_as_default():
    # Real data: candidate 163108 "vj-fm".
    params = parse_parameters(
        "Test", [["bool", "l1m2_is_velocity_sensitive", "Velocity?", 0, 0]]
    )
    p = params[0]
    assert (p.min, p.max, p.default) == (0, 1, 0)


def test_missing_parameters_key_is_zero_parameters():
    # Real data: candidate 103456 "seq3" -- module.json has no "parameters" key.
    assert parse_parameters("Test", None) == []
    assert parse_parameters("Test", []) == []


def test_repeated_label_gets_index_suffix():
    raw = [
        ["pct", "m_amt_p1", "Amount", 0, 100, 100],
        ["pct", "m_amt_p2", "Amount", 0, 100, 100],
    ]
    params = parse_parameters("Morpher", raw)
    assert [p.name for p in params] == ["amount-1", "amount-2"]
    assert [p.id for p in params] == ["m_amt_p1", "m_amt_p2"]


def test_unknown_type_is_a_hard_error():
    with pytest.raises(ParamParseError):
        parse_parameters("Test", [["frobnicate", "x", "X", 0, 1, 0]])


def test_non_bool_wrong_length_is_a_hard_error():
    with pytest.raises(ParamParseError):
        parse_parameters("Test", [["int", "x", "X", 0, 1]])  # missing default


def test_malformed_tuple_is_a_hard_error():
    with pytest.raises(ParamParseError):
        parse_parameters("Test", [["int", "x"]])
    with pytest.raises(ParamParseError):
        parse_parameters("Test", ["not-a-list"])
