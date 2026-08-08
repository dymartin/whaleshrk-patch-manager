# Phase 0 — Skeleton and fixtures

## Goal

A `uv`-managed Python package `rig`, plus the fixtures every later phase tests
against.

## Read first

`../docs/README.md`, `../docs/repo-layout.md`, `../docs/transport.md`,
`../docs/platform/card.md`, `../docs/platform/README.md` (provenance table).

## Deliverables

1. `pyproject.toml` — package `rig`, `uv`-managed, console script `rig`.
   Dependencies exactly: `ruamel.yaml`, `typer`, `httpx`. Dev: `pytest`.
2. `rig/` package skeleton matching the layout in [README.md](README.md).
3. `rig/cli.py` — a typer app with every command registered as a stub that
   exits non-zero with "not implemented". Command surface is fixed now so later
   phases only fill bodies:
   ```
   rig push [SONG...] [--dry-run] [--force]
   rig pull [SONG...] [--dry-run]
   rig lint [SONG...]
   rig catalog add SLUG...
   rig catalog update [--dry-run]
   rig upgrade MODULE... [--dry-run]
   rig rename-chain SONG OLD NEW
   ```
4. **Fixture card** under `fixtures/card/`, built from the real ORHACK 0.52b
   archive. Directory shape is `deploy.sh`'s, per `../docs/platform/card.md`:
   ```
   media/orhack/kits/kit-1 … kit-24
   media/orhack/recordings/
   media/orhack/samples/{,loops/,synths/}
   media/orhack/user-modules/
       clocks  effects/{comp,delay,drive,filter,mod,reverb}
       instruments/{drum,sampler,synth}  mod-sources  routers
       sequencers  utility/{audio,cv,midi,visual}
   data/orhack/presets/Init/            (params.json + its 224+154 sidecars)
   data/orhack/rack.json
   Patches/0RHACK/
   ```
   Keep the shipped `Init` and `jam` presets intact — Phase 3 pins its sidecar
   templates from `Init`, and Phase 3's byte-comparison scope depends on knowing
   these two carry sidecars for `-empty-` slots.
5. **In-memory transport** implementing the `../docs/transport.md` protocol
   verbatim: `exists list read write delete mkdir rename flush`. It is the test
   double for every later phase; Phase 4 makes it pass a shared conformance
   suite alongside `UsbMassStorage`.
6. **Synthetic module archives**, built in-process with `zipfile`: one clean
   archive, plus one per gate branch (bad ELF arch, unsafe archive path,
   malformed `module.json`, rack redistribution, unmodelled sidecar).

## Why no corpus of real uploads

An earlier revision froze all 145 Patchstorage candidates under
`fixtures/catalog/` so Phase 1's asserted counts could not be invalidated by
upstream edits. That cost 101MB and 5,269 tracked files in every clone and CI
checkout, to exercise six gate branches 145 times over — and the counts it
protected stopped being a target once the catalog became a shopping list.
Deleted; see `../docs/decisions.md` #71.

Hermetic tests still hold: every socket is blocked for the whole pytest
session, and the gate now runs over synthetic archives plus whatever real
archives `modules/` carries.

## Verification

- Fixture card loads through the in-memory transport.
- Fake transport round-trips files: `write` then `read` returns identical bytes;
  `rename` moves; `delete` removes; `list` reflects all three.
- Frozen catalog replays offline with the network unreachable.
- `rig --help` lists all commands.

## Done when

All four verifications pass and no test touches the network.
