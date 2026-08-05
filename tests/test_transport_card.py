"""Structural card identification -- see docs/transport.md "Card identification"
and Prompt/04-transport.md "Verification": a fixture root with both markers is
found; a root missing either is not a candidate; two candidate roots refuse;
zero candidates refuse.
"""

from __future__ import annotations

import pytest

from rig.transport import CardDetectionError, UsbMassStorage, resolve_card
from rig.transport.card import find_candidate_roots, is_card_root

from .fixture_card import FIXTURE_CARD_ROOT


def _make_root(tmp_path, name, markers):
    root = tmp_path / name
    root.mkdir()
    for marker in markers:
        (root / marker).mkdir(parents=True)
    return root


def test_frozen_fixture_card_is_a_candidate():
    assert is_card_root(FIXTURE_CARD_ROOT)


def test_root_missing_data_orhack_is_not_a_candidate(tmp_path):
    root = _make_root(tmp_path, "card", ["Patches/0RHACK"])
    assert not is_card_root(root)


def test_root_missing_patches_0rhack_is_not_a_candidate(tmp_path):
    root = _make_root(tmp_path, "card", ["data/orhack"])
    assert not is_card_root(root)


def test_root_with_neither_marker_is_not_a_candidate(tmp_path):
    root = tmp_path / "empty"
    root.mkdir()
    assert not is_card_root(root)


def test_resolve_card_with_exactly_one_candidate_returns_usb_transport(tmp_path):
    root = _make_root(tmp_path, "card", ["data/orhack", "Patches/0RHACK"])
    other = tmp_path / "not-a-card"
    other.mkdir()

    transport = resolve_card([other, root])
    assert isinstance(transport, UsbMassStorage)
    assert transport.exists("data/orhack")
    assert transport.exists("Patches/0RHACK")


def test_resolve_card_refuses_zero_candidates(tmp_path):
    other = tmp_path / "not-a-card"
    other.mkdir()
    with pytest.raises(CardDetectionError) as exc_info:
        resolve_card([other])
    assert exc_info.value.code == "NO_CARD_FOUND"


def test_resolve_card_refuses_multiple_candidates(tmp_path):
    first = _make_root(tmp_path, "card-a", ["data/orhack", "Patches/0RHACK"])
    second = _make_root(tmp_path, "card-b", ["data/orhack", "Patches/0RHACK"])
    with pytest.raises(CardDetectionError) as exc_info:
        resolve_card([first, second])
    assert exc_info.value.code == "MULTIPLE_CARDS_FOUND"


def test_zero_and_multiple_candidate_refusals_have_distinct_messages(tmp_path):
    other = tmp_path / "not-a-card"
    other.mkdir()
    first = _make_root(tmp_path, "card-a", ["data/orhack", "Patches/0RHACK"])
    second = _make_root(tmp_path, "card-b", ["data/orhack", "Patches/0RHACK"])

    with pytest.raises(CardDetectionError) as zero_exc:
        resolve_card([other])
    with pytest.raises(CardDetectionError) as multi_exc:
        resolve_card([first, second])

    assert str(zero_exc.value) != str(multi_exc.value)
    assert zero_exc.value.code != multi_exc.value.code


def test_find_candidate_roots_filters_to_only_valid_cards(tmp_path):
    card = _make_root(tmp_path, "card", ["data/orhack", "Patches/0RHACK"])
    partial = _make_root(tmp_path, "partial", ["data/orhack"])
    empty = tmp_path / "empty"
    empty.mkdir()

    assert find_candidate_roots([card, partial, empty]) == [card]
