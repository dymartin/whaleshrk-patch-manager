# Open Questions

**Unknowns only.** Everything settled lives in the doc that owns it — design
calls in [decisions.md](decisions.md), platform findings in
[platform/](platform/README.md), ingest rules in [catalog.md](catalog.md), tiers
and coverage in [validation.md](validation.md).

No product design call is open, and no validation design call is open. The suite
was scoped down on 2026-08-02; see [decisions.md](decisions.md) #61-#68.

## Confirm on first device contact

Both are answered well enough to build on; neither is observed, and neither
blocks a phase. Both are one-liners through the web terminal
([platform/surfaces.md](platform/surfaces.md)).

- **`pd -version`.** [validation.md](validation.md) pins Pd 0.53.1 from the OS
  build recipe, which never pulls backports. Replace with the observed string.
- **`locale -a`.** ORAC requests `en_US.UTF-8` before every preset scan and
  falls back to `C`. [platform/midi.md](platform/midi.md) shows preset order is
  the same either way, so this only settles which of two proven paths is live.

## Waiting on first real numbers, not on a decision

The hardware check ships with no absolute CPU or load-time gate. Its first run
on a subject records a baseline and warns about nothing. Whether an absolute
ceiling is ever worth adding is a question for after a few runs exist — a guess
made now would either block a working song or never fire.
