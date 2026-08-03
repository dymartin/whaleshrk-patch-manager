# Phase 0 — Skeleton and fixtures

## Goal

A `uv`-managed Python package `rig`, plus the two fixtures every later phase
tests against.

## Read first

`../docs/README.md`, `../docs/repo-layout.md`, `../docs/transport.md`,
`../docs/platform/card.md`, `../docs/platform/README.md` (provenance table).

## Deliverables

1. `pyproject.toml` — package `rig`, `uv`-managed, console script `rig`.
   Dependencies exactly: `ruamel.yaml`, `typer`, `httpx`. Dev: `pytest`.
2. `rig/` package skeleton matching the layout in [README.md](README.md).
3. `rig/cli.py` — a typer app with the seven commands registered as stubs that
   exit non-zero with "not implemented". Command surface is fixed now so later
   phases only fill bodies:
   ```
   rig push [SONG...] [--dry-run] [--force]
   rig pull [SONG...] [--dry-run]
   rig lint [SONG...]
   rig catalog update [--dry-run]
   rig upgrade MODULE... [--dry-run]
   rig rename-chain SONG OLD NEW
   rig validate --tier static|hardware [SONG...]
   rig validate verify-report REPORT
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
6. **Frozen catalog fixture** under `fixtures/catalog/`: all 145 Patchstorage
   candidates — list responses, detail responses, and archive content hashes —
   committed as an offline artifact. Store archives or their hashes such that
   Phase 1's gate can run without network.

## Why the catalog fixture is frozen

Live upstream edits invalidate Phase 1's asserted counts. Hermetic ingest tests
replay frozen data. Live discovery is a separate, occasional, manual check —
never part of a test run and never part of a push. See `../docs/decisions.md`
#42.

## Verification

- Fixture card loads through the in-memory transport.
- Fake transport round-trips files: `write` then `read` returns identical bytes;
  `rename` moves; `delete` removes; `list` reflects all three.
- Frozen catalog replays offline with the network unreachable.
- `rig --help` lists all commands.

## Done when

All four verifications pass and no test touches the network.
