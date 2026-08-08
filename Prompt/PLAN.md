# Implementation Plan

Read [docs/README.md](docs/README.md) first. This plan carries the build order
and the verification each step owes, not the architecture.

Per-phase build briefs, ready to hand to an implementer, live in
[Prompt/](Prompt/README.md).

Phases 0-8 build the CLI and need no hardware. Phase 9 is lint and CI; Phase
10 is the hardware check and is the only phase that touches an S2. Phase 11 is
the deferred Claude skill.

## Phase 0 — Skeleton

Python package `rig`, managed by `uv`. Dependencies: `ruamel.yaml`, `typer`,
`httpx`; stdlib for `zipfile`, `struct`, `pathlib`, `subprocess`.

Fixtures every later phase tests against:

- an in-memory transport implementing [docs/transport.md](docs/transport.md),
  plus a fixture card built from the real ORHACK 0.52b archive;
- **synthetic module archives**, built in-process with `zipfile` — one clean,
  and one per gate branch (bad ELF arch, unsafe archive path, malformed
  `module.json`, rack redistribution, unmodelled sidecar). A corpus of real
  uploads is deliberately *not* committed; see decision #71.

Every socket is blocked for the whole pytest session, so no test can reach
Patchstorage.

*Verified by:* fixture card loads, fake transport round-trips files, each gate
branch fires on its own archive.

## Phase 1 — Catalog

Ingest ORHACK built-ins and, per `rig catalog add SLUG`, individual
Patchstorage uploads. See [docs/catalog.md](docs/catalog.md).

- Slug lookup: Patchstorage has no lookup-by-slug filter, so resolving one
  walks the platform `3371` / tag `1483` list, stopping once every wanted slug
  is found. A lookup mechanism only — just the named uploads are ingested.
- Validation gate: `module.json` + `module.pd` present, JSON parses, ELF ABI
  check on every bundled external; reject unsafe archives, runtime path
  collisions, unmodelled preset sidecars. The check order in
  [docs/catalog.md](docs/catalog.md) is load-bearing.
- Key derivation, parameter derivation, category mapping with the fixed
  precedence and per-entry `category_override`.
- Populate `tags` from Patchstorage tags and categories. Unused by the CLI;
  required so Phase 11 needs no re-ingest.
- Emit `.rig/catalog/` entries, `.rig/modules.lock`, and the upload archive
  itself into `modules/<slug>@v<revision>.zip`, byte-identical (decision #72).
  Refuse a same-revision archive whose bytes differ; warn past 5MB.

*Verified by:* one synthetic archive per gate branch fires exactly that branch;
a clean archive ingests; two uploads shipping the same display name produce
distinct qualified keys; no community entry shadows a built-in runtime path.
Never against the live API.

## Phase 2 — Schema

Song model and parser per [docs/schema.md](docs/schema.md). Use ruamel
round-trip mode from the start; Phase 6 requires preserved comments.

Hard errors, never silent truncation: unknown module keys, unknown parameter
names, out-of-range values, duplicate chain names, duplicate `program` values
across songs, every capacity cap, a bound chain outgrowing its letter, and a
module `midi:` entry using channel-implied shorthand on an omni chain.

Parse `program`, mono-input and chain-mix fields, per-module `note-thru`, and
`.rig/kits.yaml`; enforce channel-16 reservation and portable case-insensitive
names.

*Verified by:* round-trip of a commented song file is byte-identical; each
validation failure has a test.

## Phase 3 — Compiler

Song model → preset directory. Core push logic.

- Fixed system slots `s1 = routers/hybrid`, `s2 = clocks/transport`, transport
  defaults (`midiin = 1`, `midiout = 0`). Module identity is fixed; `s1`'s
  parameter block is still fully written — every chain's `input:`, note channel
  and per-slot `send:` compiles into it.
- Undeclared chain, send, master and mod-source slots emit `-empty-`.
- Chain letters and note channels per [docs/schema.md](docs/schema.md);
  recorded bindings in `.rig/state/chains/` leave the pool first.
- Module key → `moduleType`; parameter name → id; unmentioned params from pinned
  catalog defaults. CC encoding `channel * 128 + cc`.
- Preset directory name = **zero-padded 3-digit** program prefix + sanitised
  song name. Emit gap placeholders for every unused program value below the
  highest one in use. Enable Program Change on reserved channel 16.
- Compile mono input L, per-chain gains, balance/width to both output pans.
- Sample resolution `<alias>/<file>` → `samp_source` + midpoint `samp_select`,
  using the folder encoding in
  [docs/platform/samples.md](docs/platform/samples.md).
- Retarget pinned ORHACK `Init` sidecar templates to occupied stateful slots;
  mirror with deletions.
- Emit `params.json` matching the device's own formatting — sorted module ids,
  tab-indented — so diffs against device output are clean.

*Verified by:* compiling a song and diffing against a hand-built expected
preset. Byte-comparison is scoped to `params.json` only — the shipped `jam` and
`Init` presets carry sidecars for `-empty-` slots, so a *correct* compiler never
reproduces their directory listings. Listing comparisons are informative, never
a pass/fail gate.

Separately assert directory-name ordering: sorting the emitted names with plain
`strcmp` must place each preset at the index equal to its `program` value.

## Phase 4 — Transport

Protocol, `UsbMassStorage`, card detection by structure (`data/orhack/` and
`Patches/0RHACK/` both present). Protocol includes `rename` and durable `flush`.
Refuse on zero or multiple candidates.

*Verified by:* fake and USB implementations pass one shared conformance suite.

## Phase 5 — Push

Composes phases 1-4, per [docs/workflows/push.md](docs/workflows/push.md).

- Preflight: reconcile installed modules against the lock **by content hash**,
  installing missing and replacing mismatched. Module content comes from the
  committed `modules/` archives, digest-verified — push reaches no network and
  checks for no updates (decision #72). Refuse a *selective* push when the lock
  changed since the last push. A locked module whose archive is missing, fails
  its digest, or no longer holds that module aborts the push.
- Verify ORHACK structure/manifest without installing it.
- Classify card presets against `.rig/state/last-pushed/*.meta.json`: recorded
  with a live song file → write, renaming the directory if the recorded name
  differs; recorded with the song file deleted → remove on a plain push;
  unrecorded → refuse, `--force` deletes. Never touch `Init`.
- Detect an un-commanded chain rename — orphaned binding plus unbound chain —
  and refuse, naming the fix.
- Mirror media playback folders with deletions, excluding `recordings/` and
  `media/samples/`.
- Stage with journal, backups, flushes, hash verification. Recover an
  interrupted transaction before any new push.
- Repair `rack.json`'s `currentPreset` only if this push left it dangling.
- Write `.rig/state/last-pushed/` — snapshot and `.meta.json` — plus chain
  bindings, only after card verification.

*Verified by:* push to a fixture card, assert the resulting tree exactly; assert
rollback leaves the card unchanged; assert every refusal path. Rename, delete
and `currentPreset` repair each need a seeded-card test, since all three are
comparisons against recorded state rather than pure functions of the repo.

## Phase 6 — Reverse mapper

`params.json` → edits applied to an existing song file, preserving comments and
formatting. Inverse of Phase 3 for everything drift covers: samples, program
prefix, gains, balance/width, note-through.

Aborts for a song that cannot be cleanly reverse-mapped — for example one
referencing a module absent from the catalog — with no partial write.

*Verified by:* property test — compile a song, mutate the preset, reverse-map,
confirm only the mutated values changed and all comments survived.

## Phase 7 — Pull

- Read every preset; match songs by the directory name recorded in
  `.rig/state/last-pushed/<song>.meta.json`, never by reconstructing it from the
  song file. Ignore gap placeholders.
- A recorded preset missing from the card warns and is skipped; pull never
  removes a song file. **All** recorded presets missing aborts the run.
- Diff against `.rig/state/last-pushed/`.
- Per drifted song: branch `pull/<song-slug>` (deterministic, no timestamp),
  apply reverse-mapped edits, commit, force-push, reuse the existing open PR if
  one exists — otherwise open one via `gh`.
- Ignore presets no recorded song claims — pull never mints a song file
  (decision #74).
- Ignore media.

*Verified by:* fixture card with seeded drift produces the expected branch and
PR set, with `gh` stubbed.

`gh` is a runtime prerequisite for real pull runs and is not installed on the
development machine as of 2026-08-02. Tests stub it; the command must fail with
a clear message when it is absent.

## Phase 8 — Lint and CLI surface

Implement the error/warning policy in [docs/schema.md](docs/schema.md) and wire
the full command set from [docs/workflows/](docs/workflows/README.md): `push`,
`pull`, `lint`, `catalog add`, `catalog update`, `upgrade`, `rename-chain`.

`rig rename-chain` rewrites the song file and its name-keyed
`.rig/state/chains/` binding in one commit.

`rig upgrade` is repo-only — `modules.lock` and `.rig/catalog/`, never
`last-pushed/`. It refuses when a parameter slug used by any song changes the id
behind it; unused slugs remap freely. This needs the catalog's recorded slug→id
pairs from Phase 1, so it cannot be stubbed.

`--dry-run` on every mutating command reports the exact planned change set and
touches nothing. `push` and `pull` dry-runs require the mounted card and apply
the real command's preconditions and refusals; `rig lint` is the offline check.

Song rename and deletion need no command — they fall out of the Phase 5 preset
classification.

*Verified by:* one test per command asserting exit codes and that `--dry-run`
leaves both card and repo byte-identical. Plus a slug→id reorder fixture that
`rig upgrade` must refuse, and a hand-renamed chain that push must refuse.

## Phase 9 — Lint and CI

See [docs/validation.md](docs/validation.md). No report artifact, no tiers,
no digest verification — decision #73.

- `rig lint [SONG...]` runs the Phase 2 schema and lint rules over every song,
  plus the Phase 1 catalog gate over every archive in `modules/` that the lock
  pins. Prints findings, exits non-zero on error. No symbol or Pd-object
  resolution — decision #68.
- Required GitHub Actions job on every pull request and push.

*Verified by:* broken-ELF, wrong-arch, unsafe-archive and unmodelled-sidecar
archive fixtures each fail; a locked module with no committed archive, and one
failing its pinned digest, each fail; a good repo passes.

## Phase 10 — Hardware check

Its own command, run by hand from the laptop against the S2 on the same
network. No CI, no runner, no attestation, and **no report artifact** — it
prints its measurements (decision #73). Full spec in
[docs/validation.md](docs/validation.md).

1. **Device session.** Connect to the OS 5.1 web app on port 8080: the
   `/log_stream` websocket for events and the `/terminal` websocket for `/proc`
   sampling. Say so and stop when the device is unreachable. Record
   `pd -version` and `locale -a` on the first successful connection and update
   the two confirm-on-contact entries in
   [docs/open-questions.md](docs/open-questions.md).
2. **Load timing.** Send Program Change on channel 16, wait for
   `preset loaded  : <name>`, take the laptop-clock delta. Three repetitions per
   song, median reported.
3. **CPU and errors.** Sample the Pd process over a fixed idle window, then
   again under a fixed note pattern on each chain's channel. Count ALSA
   underruns and Pd load-error lines from the same stream.
4. **Verdict.** Fail on any load error or underrun. Print load time and CPU
   per song alongside the stimulus profile version they were taken under.
5. **Prove it is read-only.** The command sends only Program Change and notes —
   never CC 102, never a save. Assert this by hashing the card before and after
   a run.

*Verified by:* a stubbed device session replays recorded log streams — a clean
run, a run with a load-error line, and a run with an underrun — each producing
the intended verdict; an unreachable device says so and records nothing.

## Phase 11 — Chain auto-assembly skill

Deferred Prompt.md requirement: a Claude skill that builds catalog chains from
fuzzy tone/vibe/mood descriptions.

Depends on Phases 1-8. Design must settle direct `songs/<name>.yaml` writes vs.
proposed diffs, the descriptor vocabulary, whether ingest-populated `tags` are
discriminating enough to search the whole catalog, and how slot classes and
capacities are enforced.

Phase 1 populates `tags` so this needs no catalog re-ingest.

## Assumptions flagged

- Preset persistence behaviour is modelled on `mec` C++ source. Safe: ORHACK's
  compiled binaries are byte-identical to upstream ORAC's.
- Program Change indexing no longer assumes a locale. ORAC requests
  `en_US.UTF-8` and falls back to `C`; zero-padded 3-digit prefixes order
  identically under both, and `Init` follows the digits under both. See
  [docs/platform/midi.md](docs/platform/midi.md). What is *not* guaranteed is
  the position of a foreign preset directory whose name starts with punctuation.
- Static ELF validation is necessary, not sufficient. Nothing between the
  archive and the device checks a module, by decision #61 — a module can pass
  ingest and fail on the S2, and Phase 10 is what reports it, at rehearsal
  rather than on a pull request.
- Audio quality, silence and thermals are never checked by any tool. The band's
  ears are the oracle. See #63.
