# Orchestrator brief — build `whaleshrk-patch-manager`

**You are the controller.** Execute this build with
`superpowers:subagent-driven-development`: one fresh **Sonnet 5** implementer
subagent per task, a task review after each, a whole-branch review at the end.

Invoke the skill now, then follow it exactly. This file supplies what the skill
asks you to construct: the task list, the briefs, the global constraints, and the
project context. Everything below is yours to hand out — never paste this whole
file into a dispatch.

## Start here

1. Invoke `superpowers:subagent-driven-development`.
2. Create the isolated workspace per `superpowers:using-git-worktrees`. Do not
   implement on `main` without explicit consent.
3. Treat **`../Prompt/PLAN.md`** as the PLAN_FILE for workspace and ledger paths
   (`scripts/sdd-workspace ../Prompt/PLAN.md`). Check for an existing ledger and resume
   at the first task with no `complete` line.
4. Create one todo per task from the table below.
5. Run the skill's pre-flight conflict scan across all twelve briefs plus the
   Global Constraints in this file. Batch anything you find into one question
   before dispatching Task 0.

## Tasks

Twelve tasks, **strictly sequential**. Each brief is already extracted — skip
`scripts/task-brief` and pass the brief path directly.

| Task | Brief | Implementer model | Depends on | Hardware |
|---|---|---|---|---|
| 0 | [00-skeleton.md](00-skeleton.md) | Sonnet 5 | — | no |
| 1 | [01-catalog.md](01-catalog.md) | Sonnet 5 | 0 | no |
| 2 | [02-schema.md](02-schema.md) | Sonnet 5 | 1 | no |
| 3 | [03-compiler.md](03-compiler.md) | Sonnet 5 | 1, 2 | no |
| 4 | [04-transport.md](04-transport.md) | Sonnet 5 | 0 | no |
| 5 | [05-push.md](05-push.md) | Sonnet 5 | 1, 2, 3, 4 | no |
| 6 | [06-reverse-mapper.md](06-reverse-mapper.md) | Sonnet 5 | 2, 3 | no |
| 7 | [07-pull.md](07-pull.md) | Sonnet 5 | 5, 6 | no |
| 8 | [08-cli.md](08-cli.md) | Sonnet 5 | 1-7 | no |
| 9 | [09-static-validation.md](09-static-validation.md) | Sonnet 5 | 1, 2, 8 | no |
| 10 | [10-hardware-check.md](10-hardware-check.md) | Sonnet 5 | 9 | **yes** |
| 11 | [11-chain-skill.md](11-chain-skill.md) | Sonnet 5 | 1-8 | no |

**Never dispatch two implementers in parallel.** Task 4 is the only one that
could run early; the ordering cost is not worth the conflict risk.

**Task 10 requires the S2 on the same network.** Its stubbed-replay tests run
anywhere; the live run does not. If no device is reachable, have the implementer
land the code and the replay fixtures, record `Task 10: parked — live run
pending hardware` in the ledger, and continue to Task 11.

**Task 11 has open design calls.** Its brief lists four. Present them to the
human partner and get rulings before dispatching an implementer.

## Dispatching an implementer

Per the skill's contract, each dispatch contains only:

1. One line on where the task fits.
2. The brief path — "read this first; it is your requirements, and its exact
   values are to be used verbatim."
3. The **Global Constraints** block below, verbatim.
4. Interfaces and decisions from earlier tasks the brief cannot know — the
   transport protocol signature, the catalog entry shape, the song model's public
   API. Keep it to interfaces, never prior-task narrative.
5. Your resolution of any ambiguity you spotted in the brief.
6. The report-file path and the report contract.

Model policy for this build:

| Role | Model |
|---|---|
| Implementer, every task | **Sonnet 5** |
| Task reviewer | **Sonnet 5** |
| Fix rounds 4-5 | Opus 5 — one tier up, per the skill |
| Final whole-branch review | Opus 5 — most capable, per the skill |

## Global Constraints

Hand this block to every implementer and every reviewer, verbatim.

> 1. **No hardware feedback channel exists** until Task 10 lands. Verify every
>    platform claim by reading ORHACK / ORAC / `mec` / Organelle_OS source, or
>    the shipped data. Never assume device behaviour. Never cite a planned tier
>    as if it had already run.
> 2. **Separate verified facts from hypotheses** in every note and comment.
> 3. **Never silently truncate or default.** Every capacity, collision and
>    out-of-range condition in `docs/schema.md` is a hard error with a distinct
>    message.
> 4. **The repo is the source of truth on push; the device is authoritative only
>    for parameter values.** Pull may change what a song says, never whether it
>    exists.
> 5. **Musicians see only friendly YAML.** No slot ids, no `moduleType` paths, no
>    parameter ids, no `kit-N`, no encoded CC keys, no chain letters.
> 6. **Determinism:** a song file plus `.rig/modules.lock` plus
>    `.rig/state/chains/` fully determines the compiled output.
> 7. **Comments state intent, constraints, assumptions and rationale**, written
>    for a reader with zero session history. Never reference fixes, past
>    implementations or conversations. Delete dead code; do not comment it out.
> 8. **Reuse existing abstractions.** No new dependency without clear
>    justification — the sanctioned set is `ruamel.yaml`, `typer`, `httpx`, plus
>    stdlib.
> 9. **Never commit anything the user did not ask for, and never add AI or tool
>    attribution to a commit message.**
> 10. **Update `docs/`** when architecture, behaviour, an interface or an ops
>     procedure changes. Skip transient debug notes. No doc bloat.

## Controller housekeeping

- Ledger lines follow the skill's format. Add one extra convention for this
  build: when a task changes `docs/`, append
  `Task <N>: docs touched — <files>` so the final review can check the knowledge
  base stayed true.
- Task 1's asserted counts, Task 3's byte-comparison scope and Task 10's
  read-only card-hash assertion are the three places where a plausible-looking
  shortcut silently breaks the guarantee. Give reviewers those three by name in
  the constraints lens for the tasks that touch them.
- Two device facts are unobserved (`pd -version`, `locale -a`). Task 10 replaces
  them in `docs/open-questions.md` and `docs/validation.md`. Until then, no task
  may treat them as observed.

---

# Project context

A CLI (`rig`) that treats the whaleshrk band's live rig — a Critter & Guitari
Organelle S2 running ORHACK 0.52b, an ORAC fork — as version-controlled config.

- One YAML file per song describes that song's whole patch chain.
- `rig push` compiles YAML into the device's on-device JSON preset format and
  writes it to the SD card over USB mass storage.
- `rig pull` reads the card, detects drift against a stored baseline,
  reverse-maps it into the song YAML, and opens one PR per drifted song.

## Stack

Python package `rig`, managed by `uv`. Dependencies: `ruamel.yaml` (round-trip
mode — pull rewrites song files in place preserving comments), `typer`, `httpx`.
Stdlib for `zipfile`, `struct`, `pathlib`, `subprocess`, `hashlib`, `json`.

Runtime prerequisite for real `pull` runs: the `gh` CLI. Not installed on the
development machine as of 2026-08-02; tests stub it.

## Target module layout

Hold to this. Later tasks assume it.

```
rig/
  cli.py              typer app, all commands
  catalog/            patchstorage client, archive gate, ELF, ingest, lock
  song/               model, ruamel parser, validation, lint
  compile/            compiler, letter assignment, samples, sidecars, params.json
  transport/          Transport protocol, UsbMassStorage, InMemory, card detect
  push/               reconcile, classify, mirror, journalled transaction
  pull/               reverse mapper, adoption emitter, branch/PR driver
  validate/           report schema, static tier, hardware session
tests/
fixtures/             frozen catalog, fixture card, recorded log streams
```

## Knowledge base map

Briefs name the doc that owns each fact. When a brief and a doc disagree, the
doc wins — and the brief gets fixed.

| Doc | Owns |
|---|---|
| `../docs/overview.md` | Goals, non-goals, the guarantee and its edges |
| `../docs/schema.md` | Song YAML, capacities, letter assignment, lint policy |
| `../docs/catalog.md` | Ingest, keys, validation gate, category mapping, versioning |
| `../docs/media.md` | Samples, kit aliases, the positional hazard |
| `../docs/transport.md` | Transport interface, card identification |
| `../docs/repo-layout.md` | Directory structure, what is generated |
| `../docs/validation.md` | Both validation tiers, subject, stimulus profile |
| `../docs/decisions.md` | 68 numbered decisions with rationale — cite by number |
| `../docs/open-questions.md` | The only remaining unknowns |
| `../docs/workflows/push.md` | Push sequence |
| `../docs/workflows/pull.md` | Drift, PRs, adoption |
| `../docs/workflows/maintenance.md` | `rename-chain`, `upgrade` |
| `../docs/platform/state.md` | Preset format, sidecar `.txt`, dangling `currentPreset` |
| `../docs/platform/routing.md` | Slot topology, chain inputs, full `s1` surface, transport |
| `../docs/platform/midi.md` | CC key encoding, Program Change indexing, CC 100/101/102 |
| `../docs/platform/modules.md` | `module.json`, label collisions, role is underivable |
| `../docs/platform/samples.md` | `samp_source` encoding, position formula |
| `../docs/platform/card.md` | Install layout, `deploy.sh`, buffered writes |
| `../docs/platform/runtime.md` | Pd 0.53.1, launch line, external resolution |
| `../docs/platform/surfaces.md` | Log stream, `preset loaded` event, web API, OSC |
| `../docs/platform/patchstorage.md` | API behaviour, silently-ignored params |

## Flagged assumptions

Carried from `../Prompt/PLAN.md`. Treat each as stated, not as settled fact.

- **Preset persistence behaviour is modelled on `mec` C++ source.** Safe:
  ORHACK's compiled binaries are byte-identical to upstream ORAC's — 30 of 40
  shared files identical, zero mismatches — so `mec` is an accurate model of the
  shipped code.
- **Program Change indexing no longer assumes a locale.** ORAC requests
  `en_US.UTF-8` and falls back to `C`; zero-padded 3-digit prefixes order
  identically under both, and `Init` follows the digits under both. What is *not*
  guaranteed is the position of a foreign preset directory whose name starts with
  punctuation — under `C` it sorts before the managed block and shifts every
  program index.
- **Static ELF validation is necessary, not sufficient.** Nothing between the
  archive and the device checks a module (#61). A module can pass ingest and fail
  on the S2; Task 10 is what reports it, at rehearsal rather than on a pull
  request.
- **Audio quality, silence and thermals are never checked by any tool** (#63).
  The band's ears are the oracle. No report may be read as "this sounds right".
- **Two device facts are unobserved** and confirmed on first contact in Task 10:
  `pd -version` and `locale -a`. Neither blocks a task.

## Facts every task needs

- **Preset = directory** under `<card>/data/orhack/presets/<Name>/` containing
  `params.json`. Name-keyed. No slot or index order.
- **`params.json`** is keyed by slot id, holds every parameter of every module
  (no deltas), module ids sorted, tab-indented. Identical rack state produces a
  byte-identical file.
- **24 slots:** `a1-a3` `b1-b4` `c1-c3` `d1-d4` chains; `p1` `p2` sends;
  `f1` `f2` `f3` master; `m1-m3` mod sources; `s1` `s2` system.
- **Chain capacity is asymmetric:** A=3, B=4, C=3, D=4.
- **`s1 = routers/hybrid`, `s2 = clocks/transport`** always. Module identity is
  fixed; `s1`'s *parameters* are the compile target for every chain's `input:`,
  note channel and per-slot `send:`.
- **CC key = `channel * 128 + cc`**, channels 1-16, valid keys 128-2175.
- **Program Change indexes an `alphasort` scan** of preset directories holding a
  `params.json`. Prefixes must be zero-padded to 3 digits; gaps below the
  highest program in use need placeholder presets.
- **Channel 16 is reserved.** It carries song Program Change and ORAC's
  preset-control CCs — CC 102 ≥ 64 on channel 16 overwrites the loaded preset.
- **Samples are positional.** `samp_source` selects a folder, `samp_select`
  a normalised position. No filename is ever stored. Any file-count change in a
  folder remaps every sample in it.
- **Card is identified by structure**: `data/orhack/` and `Patches/0RHACK/`
  both present. Zero or multiple candidates: refuse.
- **`Init` is protected by rule, never by filesystem permissions** — the card is
  usually `vfat`/`exfat` where mode bits are meaningless.
- **Card writes are buffered** (`-o async,noatime`). Every push ends with an
  explicit flush; operator guidance is "eject, don't yank".
