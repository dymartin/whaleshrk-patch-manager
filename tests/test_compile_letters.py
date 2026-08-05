"""Chain letter assignment -- the five worked examples from Prompt/02-schema.md
"Chain letters", plus the cold-rebuild invariant."""

from __future__ import annotations

import pytest

from rig.compile.letters import ChainSlots, LetterAssignmentError, assign_letters


def slots(*pairs: tuple[str, int]) -> list[ChainSlots]:
    return [ChainSlots(name=n, slot_count=c) for n, c in pairs]


def test_four_three_slot_chains_get_a_c_b_d_in_declaration_order():
    chains = slots(("one", 3), ("two", 3), ("three", 3), ("four", 3))
    assert assign_letters(chains, {}) == {"one": "A", "two": "C", "three": "B", "four": "D"}


def test_one_four_slot_among_three_slot_chains():
    chains = slots(("pads", 3), ("lead", 4), ("bass", 3), ("fx", 3))
    result = assign_letters(chains, {})
    assert result["lead"] == "B"
    assert result["pads"] == "A"
    assert result["bass"] == "C"
    assert result["fx"] == "D"


def test_two_four_slot_and_two_three_slot_chains():
    chains = slots(("lead", 4), ("pads", 3), ("bass", 4), ("fx", 3))
    result = assign_letters(chains, {})
    assert result["lead"] == "B"
    assert result["bass"] == "D"
    assert result["pads"] == "A"
    assert result["fx"] == "C"


def test_three_four_slot_chains_is_a_compile_error():
    chains = slots(("a", 4), ("b", 4), ("c", 4))
    with pytest.raises(LetterAssignmentError) as exc_info:
        assign_letters(chains, {})
    assert exc_info.value.code == "CHAINS_NEEDING_4_SLOTS_EXCEEDED"


def test_bound_chain_keeps_its_letter_new_four_slot_chain_takes_the_other():
    chains = slots(("old", 3), ("new", 4))
    result = assign_letters(chains, {"old": "D"})
    assert result["old"] == "D"
    assert result["new"] == "B"


def test_bound_chain_outgrowing_its_letter_is_an_error():
    chains = slots(("pads", 4))
    with pytest.raises(LetterAssignmentError) as exc_info:
        assign_letters(chains, {"pads": "A"})
    assert exc_info.value.code == "BOUND_CHAIN_OUTGROWN"


def test_cold_rebuild_from_full_bindings_reproduces_them():
    chains = slots(("pads", 3), ("lead", 4), ("bass", 3), ("fx", 4))
    bindings = {"pads": "A", "lead": "B", "bass": "C", "fx": "D"}
    assert assign_letters(chains, bindings) == bindings
