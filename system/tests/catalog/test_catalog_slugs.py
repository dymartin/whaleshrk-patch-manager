"""Slug and key derivation -- docs/catalog.md "Keys" and "Parameter names"."""

from rig.catalog.slugs import module_key, param_names, slug


def test_basic_slug():
    assert slug("Analog Mono") == "analog-mono"


def test_plus_maps_to_plus_word():
    # Otherwise "Braids"/"Braids +" and "Plaits"/"Plaits +" collide once
    # generic punctuation stripping drops the "+" -- see docs/catalog.md.
    assert slug("Braids +") == "braids-plus"
    assert slug("Plaits +") == "plaits-plus"


def test_plus_rule_prevents_collision():
    assert slug("Braids") != slug("Braids +")
    assert slug("Plaits") != slug("Plaits +")


def test_module_key_is_qualified_by_source():
    assert module_key("Braids", "orhack") == "braids@orhack"
    assert module_key("Braids", "some-upload-slug") == "braids@some-upload-slug"


def test_param_names_no_repeats_gets_no_suffix():
    assert param_names(["Cutoff", "Resonance"]) == ["cutoff", "resonance"]


def test_param_names_repeated_label_gets_declaration_order_suffix():
    labels = ["Amount", "Offset", "Amount", "Offset", "Amount"]
    assert param_names(labels) == ["amount-1", "offset-1", "amount-2", "offset-2", "amount-3"]


def test_param_names_first_occurrence_of_a_repeat_is_also_suffixed():
    # "amount-1" not bare "amount" -- every occurrence of a repeated label is
    # suffixed, matching "amount-1 ... amount-16" in the brief.
    labels = ["Amount", "Amount"]
    assert param_names(labels) == ["amount-1", "amount-2"]
