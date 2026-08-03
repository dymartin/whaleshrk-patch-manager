# whaleshrk-patch-manager — Knowledge Base

Read `overview` first, then the task-relevant doc.

| Doc | Covers |
|---|---|
| [overview.md](overview.md) | What this is, why, goals and non-goals |
| [platform/](platform/README.md) | ORHACK/ORAC device facts. Verified, expensive to re-derive |
| [schema.md](schema.md) | Song YAML — the musicians' surface |
| [catalog.md](catalog.md) | Module catalog: ingest, keys, validation, versioning |
| [media.md](media.md) | Samples, kits, the ordinal hazard |
| [workflows/](workflows/README.md) | Push, pull, drift detection, PRs |
| [repo-layout.md](repo-layout.md) | Directory structure, what is generated |
| [transport.md](transport.md) | Device access abstraction |
| [validation.md](validation.md) | Static CI and the hand-run hardware check |
| [decisions.md](decisions.md) | Decision record with rationale |
| [open-questions.md](open-questions.md) | Remaining unknowns — read before starting any phase |

Build order: [`../Prompt/PLAN.md`](../Prompt/PLAN.md). Per-phase build briefs:
[`../Prompt/`](../Prompt/README.md). Original requirements: `../Prompt.md`;
`decisions.md` records every override.

## Ground rules

Source analysis handles deterministic checks. The S2 is the only other evidence,
and only for four things: load time, CPU, Pd load errors, ALSA underruns.
Nothing checks audio — see [validation.md](validation.md).

**Separate facts from hypotheses.** Facts come from source or shipped data;
inferences are labelled.
