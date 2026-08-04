"""Built-in ingestion -- synthetic tree tests plus the real pinned fixture card.

docs/platform/modules.md: ORHACK's tree holds 67 module.json files, the
runtime registers 66 (`-empty-` included, since `loadModuleDir` never
descends past a directory that already has module.pd). The catalog carries
only the 65 selectable ones -- `-empty-` is the schema's own sentinel for an
unoccupied slot, never a module selected by catalog key.
"""

from __future__ import annotations

from rig.catalog.builtins import ingest_builtins, ingest_pinned_builtins
from rig.transport.memory import InMemoryTransport


def _write_module(transport, path, display, parameters=None):
    import json

    transport.write(
        f"{path}/module.json",
        json.dumps({"display": display, "parameters": parameters or []}).encode("utf-8"),
    )
    transport.write(f"{path}/module.pd", b"#N canvas 0 0 1 1 10;\n")


def test_registers_a_simple_module():
    t = InMemoryTransport()
    _write_module(t, "Patches/0RHACK/modules/effects/delay/echo", "Echo")
    entries = ingest_builtins(t)
    assert len(entries) == 1
    assert entries[0].key == "echo@orhack"
    assert entries[0].module_type == "effects/delay/echo"
    assert entries[0].source == "orhack"


def test_recursion_stops_at_first_module_pd():
    # Mirrors effects/delay/spiraldelay/module/module.json: nested inside a
    # directory that already registers as a module -- never reached.
    t = InMemoryTransport()
    _write_module(t, "Patches/0RHACK/modules/effects/delay/spiraldelay", "SpiralDelay")
    _write_module(t, "Patches/0RHACK/modules/effects/delay/spiraldelay/module", "Nested")
    entries = ingest_builtins(t)
    assert len(entries) == 1
    assert entries[0].display == "SpiralDelay"


def test_empty_sentinel_is_excluded_from_the_catalog():
    t = InMemoryTransport()
    _write_module(t, "Patches/0RHACK/modules/-empty-", "Empty")
    _write_module(t, "Patches/0RHACK/modules/effects/delay/echo", "Echo")
    _write_module(t, "Patches/0RHACK/modules/instruments/synth/rings", "Rings")
    entries = ingest_builtins(t)
    module_types = {e.module_type for e in entries}
    assert module_types == {"effects/delay/echo", "instruments/synth/rings"}


def test_pinned_fixture_card_reproduces_the_measured_built_in_count():
    entries = ingest_pinned_builtins()
    assert len(entries) == 65
    assert not any(e.module_type == "-empty-" for e in entries)
    # The nested module.json must never surface as its own catalog entry.
    assert not any(e.module_type == "effects/delay/spiraldelay/module" for e in entries)
    assert any(e.module_type == "effects/delay/spiraldelay" for e in entries)


def test_pinned_fixture_card_keys_have_no_collisions():
    entries = ingest_pinned_builtins()
    keys = [e.key for e in entries]
    assert len(keys) == len(set(keys))
