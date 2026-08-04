"""Fixture card loads through the in-memory transport (Phase 0 verification #1).

Also pins the shipped Init/jam sidecar counts Phase 3 depends on -- see
docs/platform/state.md and Prompt/00-skeleton.md's ambiguity resolutions.
"""

import re

from rig.transport import InMemoryTransport

from .fixture_card import load_fixture_card


def _transport():
    t = InMemoryTransport()
    load_fixture_card(t)
    return t


def test_card_markers_present():
    t = _transport()
    assert t.exists("data/orhack")
    assert t.exists("Patches/0RHACK")


def test_deploy_sh_present_verbatim():
    t = _transport()
    assert t.exists("Patches/0RHACK/deploy.sh")
    assert b"chmod 555 $USER_DIR/data/orhack/presets/Init" in t.read(
        "Patches/0RHACK/deploy.sh"
    )


def test_all_24_kit_dirs_present_and_empty():
    t = _transport()
    for i in range(1, 25):
        path = f"media/orhack/kits/kit-{i}"
        assert t.exists(path)
        assert t.list(path) == []


def test_user_module_category_tree_present():
    t = _transport()
    for category in [
        "clocks",
        "effects/comp", "effects/delay", "effects/drive",
        "effects/filter", "effects/mod", "effects/reverb",
        "instruments/drum", "instruments/sampler", "instruments/synth",
        "mod-sources", "routers", "sequencers",
        "utility/audio", "utility/cv", "utility/midi", "utility/visual",
    ]:
        assert t.exists(f"media/orhack/user-modules/{category}")


def test_init_preset_has_params_json_and_full_sidecar_inventory():
    t = _transport()
    assert t.exists("data/orhack/presets/Init/params.json")

    entries = t.list("data/orhack/presets/Init")
    counts = {"a1": 0, "b1": 0, "c1": 0, "d1": 0}
    for name in entries:
        m = re.search(r"(a1|b1|c1|d1)", name)
        if m:
            counts[m.group(1)] += 1

    # Per docs/platform/state.md: Init ships every chain slot -empty-, but
    # carries the canonical sidecar inventory Phase 3 pins its templates from.
    assert counts["a1"] == 224
    assert counts["b1"] == 224
    assert counts["c1"] == 224
    assert counts["d1"] == 154


def test_jam_preset_present_and_not_trimmed():
    t = _transport()
    assert t.exists("data/orhack/presets/jam/params.json")
    # jam ships ~800 sidecar files; assert it wasn't trimmed down.
    assert len(t.list("data/orhack/presets/jam")) > 500


def test_rack_json_present():
    t = _transport()
    assert t.exists("data/orhack/rack.json")
