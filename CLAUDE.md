# CLAUDE.md

## Context

* whaleshrk-patch-manager: CLI, treats whaleshrk band's live synth rig (Critter & Guitari Organelle S2, running ORHACK) as version-controlled config.
* One YAML file per song = full patch chain. User experience is friendly YAML, black box under the hood.
* Push compiles YAML into ORHACK's on-device JSON config and writes to the SD card over keyed SSH by default; USB mass storage is an explicit fallback. Repo = source of truth on push.
* Pull detects drift, matched by ORHACK preset name (never order/slot — presets are name-keyed). Drifted song reverse-mapped to YAML, committed to new branch, PR'd via `gh` CLI. One PR per drifted song.
* Musicians only touch friendly YAML — no raw device IDs, CC numbers, or Pure Data internals exposed.

## General Principles

* `/ponytail` for coding: simple, clear, no bloat.
* `/caveman full` for user conversations.
* `/caveman lite` for docs: highest-level prose, but never drop a verified constant, table, formula or decision reference.
* `/grill-me` for all open design calls.
* Sonnet 5 for subagents.

## Documentation

* system/docs/ = living knowledge base. Segment + index for fast lookup.
* Read system/docs/README.md before every session. Use indexed documentation based on task.
* Prompt/ = per-phase build briefs, one per Prompt/PLAN.md phase. Keep in step with system/docs/; docs win on conflict.
* Update docs on: architecture change, behavior change, new persistent knowledge, ops procedure change, useful debug findings.
* Skip transient debug steps/one-off investigations unless reusable.
* No doc bloat. Cut irrelevant/wrong info.
* Docs cover intent, invariants, interfaces, architecture, ops knowledge. Skip detail likely to change.

## Continuous Self Improvement

* Same mistake twice: add concrete rule to this `CLAUDE.md` that prevents it.
* Strengthen existing guidance over narrow one-off rules.

## Code

* Comments: intent, constraints, assumptions, rationale. Always for readers with zero session history. Not code history.
* No comment refs to fixes, past implementations, conversations, session context.
* Delete dead code, don't comment it out.
* Reuse existing abstractions over new ones.
* No new dependencies without clear justification.

## Planning

* Plans: enough detail for deterministic work, no speculation.
* Flag unverifiable assumptions.
* Debugging: separate verified facts from hypotheses.
* No hardware feedback channel exists yet — verify platform/module behavior off-hardware, by manually reading actual ORHACK/ORAC/module source. Never assume behavior.
* The hardware check (Prompt/PLAN.md Phase 10) will become a real feedback channel, for load time, CPU, Pd load errors and ALSA underruns only. Until it lands, source reading is the only evidence. Never cite a planned tier as if it had already run.

## Review

* After plan, second-pass review for: gaps in technical knowledge, missing requirements, unclear design decisions, conflicting info, wrong assumptions.
* After non-trivial change, second-pass review (separate reasoning pass/subagent) for: bugs, missing edge cases, simplification opportunities, doc updates.
* Skip extra review for low-risk changes — cost outweighs benefit.

## Communication

* User-facing: outcomes, behavior, design rationale — not implementation detail.
* Internal planning: implementation-oriented. External: high level.

## Git

* Never commit unless told.
* No AI/Claude/tool attribution in commit messages.
