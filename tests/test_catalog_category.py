"""Category precedence -- docs/catalog.md "Category mapping", decision #32."""

import pytest

from rig.catalog.category import UnrecognizedCategoryError, resolve_category


def test_single_category_maps_directly():
    assert resolve_category(["synthesizer"]) == "instruments/synth"
    assert resolve_category(["sampler"]) == "instruments/sampler"
    assert resolve_category(["sequencer"]) == "sequencers"
    assert resolve_category(["effect"]) == "effects/mod"


def test_utility_group_all_map_to_utility_audio():
    for slug in ["utility", "sound", "other", "composition"]:
        assert resolve_category([slug]) == "utility/audio"


def test_sampler_wins_over_everything():
    # Real measured case: candidate 105149's categories include effect,
    # sampler, sequencer, synthesizer, utility -- sampler is most specific.
    assert resolve_category(["effect", "sampler", "sequencer", "synthesizer", "utility"]) == (
        "instruments/sampler"
    )


def test_precedence_ignores_json_order():
    assert resolve_category(["utility", "effect"]) == "effects/mod"
    assert resolve_category(["effect", "utility"]) == "effects/mod"


def test_case_insensitive():
    assert resolve_category(["Sampler"]) == "instruments/sampler"


def test_no_recognized_category_is_a_hard_error():
    with pytest.raises(UnrecognizedCategoryError):
        resolve_category([])
    with pytest.raises(UnrecognizedCategoryError):
        resolve_category(["some-unknown-category"])
