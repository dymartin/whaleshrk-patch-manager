# Open Questions

**Unknowns only.** Everything settled lives in the doc that owns it — design
calls in [decisions.md](decisions.md), platform findings in
[platform/](platform/README.md), ingest rules in [catalog.md](catalog.md), tiers
and coverage in [validation.md](validation.md).

No product design call is open, and no validation design call is open. The suite
was scoped down on 2026-08-02; see [decisions.md](decisions.md) #61-#68.

## Confirm on first device contact

First device contact happened 2026-08-08 and closed the first two entries. Both
are recorded in the doc that owns them; neither changed any design.

- ~~`pd -version`~~ — **observed**, matches the recipe. See
  [validation.md](validation.md).
- ~~`locale -a`~~ — **observed**, and it settles the question rather than
  confirming it: `en_US.UTF-8` is absent from the image, so ORAC's `setlocale`
  always fails and `C` collation is the only reachable path. See
  [platform/midi.md](platform/midi.md).

Still open:

- **Default content of `<slot>-slot-tracker.txt`, `<slot>-seq<n>x.txt`
  (`sequencers/{overdrum,overflow,clips}`) and `<slot>-{len,notes,vel}.txt`
  (`sequencers/polystep`).** Neither shipped preset carries any of these for a
  slot's own live occupant (decision #69). For `overdrum`/`overflow`, source
  reading confirms both are read unconditionally on every load (not gated
  behind a user action -- see decision #69's citation), so this is not merely
  "unobserved", it is a real gap: the compiler refuses to compile a song that
  places any of the four sequencer types at all, even though `Init` verifies
  a template for *part* of what `overdrum`/`overflow` read. Saving a preset
  with each module freshly placed, then reading what the device wrote, would
  either supply the missing templates or show the files are recreated on
  demand and compile can go back to emitting only the verified families.

## Waiting on first real numbers, not on a decision

The hardware check ships with no absolute CPU or load-time gate. Its first run
on a subject records a baseline and warns about nothing. Whether an absolute
ceiling is ever worth adding is a question for after a few runs exist — a guess
made now would either block a working song or never fire.
