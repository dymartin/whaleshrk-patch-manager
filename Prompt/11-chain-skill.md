# Phase 11 — Chain auto-assembly skill

## Goal

A Claude skill that builds catalog chains from fuzzy tone / vibe / mood
descriptions. The last outstanding Prompt.md requirement, deliberately deferred
until the CLI works (#24).

## Read first

`../docs/overview.md` ("Planned, not built"), `../docs/catalog.md` ("Tags"),
`../docs/schema.md` (capacities and slot classes), `../docs/decisions.md` #24.

## Prerequisites

Phases 1-8, complete and passing. This phase adds no device behaviour and needs
no hardware.

Phase 1 already populates each catalog entry's `tags` from Patchstorage tags and
categories, so **no catalog re-ingest is required**.

## Design calls to settle before building

Do not start implementation until each is decided and written into
`../docs/decisions.md`:

1. **Output form** — direct writes to `songs/<name>.yaml`, or proposed diffs the
   musician applies. Weigh it against the repo-is-source-of-truth invariant and
   the one-PR-per-song rule.
2. **Descriptor vocabulary** — what a musician is allowed to say, and how it maps
   onto catalog metadata.
3. **Whether ingest-populated `tags` are discriminating enough** to search all
   200 entries. If not, decide what additional metadata ingest must produce, and
   whether that forces a re-ingest after all.
4. **How slot classes and capacities are enforced** — chains 4, modules per
   chain 3 (or 4 on B and D), 4-slot chains 2, sends 2, master FX 3, mod sources
   3. A generated chain that violates any of these must be rejected before it
   reaches a song file, not caught later by the compiler.

## Constraints that already hold

- Role **cannot** be derived from a patch. Signal I/O does not discriminate
  instrument from effect — `(2 in, 2 out)` occurs across effects, utility,
  instruments, sequencers and mod-sources alike. Any classification comes from
  catalog metadata.
- Output must be valid friendly YAML: no module ids, no CC keys, no `kit-N`, no
  `moduleType` paths, no slot letters.
- Aux slots (`m1-m3`, `s1`, `s2`) carry **no audio path at all**. A module placed
  there receives nothing, silently, with no device-side report.
- **No DSP gating exists.** All 24 slots always run; two instances of a module
  always cost twice the DSP. Share cross-chain FX through a send slot.
- Signal flow inside a chain is strictly series. Parallelism comes only from
  summing multiple instruments in one chain, per-slot send taps to `p1`/`p2`, and
  the four chains running in parallel into the mixer.

## Done when

The four design calls are recorded as decisions, the skill produces
capacity-valid friendly YAML for a set of descriptor test cases, and `rig lint`
passes on every generated song.
