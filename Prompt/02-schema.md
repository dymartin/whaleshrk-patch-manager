# Phase 2 — Song schema

## Goal

Song model plus a ruamel round-trip parser, with every validation rule as a hard
error.

## Read first

`../docs/schema.md` (owns this phase), `../docs/media.md`,
`../docs/platform/routing.md`, `../docs/platform/midi.md`,
`../docs/decisions.md` #7, #12, #14, #15, #22, #28, #30, #31, #33, #34, #41,
#46, #49.

## Use ruamel round-trip mode from the start

Phase 6 rewrites song files in place preserving comments and formatting. A
plain-load parser cannot be retrofitted.

## Song shape

`songs/<slug>.yaml`, one per song. Canonical example is the block at the top of
`../docs/schema.md` — reproduce its field set exactly:

```yaml
song: Vellichor
program: 12
keyboard: pads # optional chain name; built-in keys initially control it
sends:      { <name>: { module: <key>, <param>: <value>, ... } }   # -> p1, p2
master:     [ { <key>: {params} }, ... ]                            # -> f1, f2, f3
mod-sources:[ { <key>: {params} }, ... ]                            # -> m1, m2, m3
chains:
  - name: <free text>
    input: { guitar: <bool> }
    midi:  { channel: <0-15|omitted> }
    mix:   { input-gain:, output-gain:, balance:, width: }
    modules:
      - <key>:
          <param>: <value>
          midi: { <param>: <cc> | { channel:, cc: } }
          send: { <send-name>: <0-100> }
          note-thru: <bool>
          sample: <alias>/<file.wav>
```

## Not in the song file

- **No `s1:` or `s2:` block.** The compiler always emits `s1 = routers/hybrid`
  and `s2 = clocks/transport`. `input:`, `midi: {channel:}` and per-module
  `send:` are the supported way to reach `s1`'s parameters.
- **Nothing tempo-related.** `clocks/transport` is fully compiler-defaulted with
  `midiin = 1`; the rig slaves to the DAW's MIDI clock. `set_signature` stays 4 —
  MIDI clock cannot transmit time signature.
- **No sequencer patterns or morpher banks.** Compiler-owned (#1).
- **`keyboard:` is optional and global.** It names one non-empty chain whose
  first slot becomes the initial active destination. Channel 16 / CC 20 changes
  that destination while playing (#81).
- **No sample-playback input type.** Sample playback is a module
  (`samplement@orhack`) occupying a chain slot, selected like any other module.

## Hard errors — never silent truncation

| Rule | Detail |
|---|---|
| Unknown module key | Not in `.rig/catalog/` |
| Unknown parameter name | Not a slug for that module version |
| Out-of-range value | Against the catalog's min/max |
| Duplicate chain names within a song | |
| `keyboard` names a missing or empty chain | |
| Duplicate `program` across songs | Device would index one unreachably |
| `program` outside 0-127 | Raw MIDI Program Change value |
| Song names colliding after sanitisation | Portable, case-insensitive filenames |
| Chains > 4 | |
| Modules per chain > 3, or > 4 on a 4-slot chain | |
| Chains needing 4 slots > 2 | |
| Sends > 2 | |
| Master FX > 3 | |
| Mod sources > 3 | |
| Kit aliases in `.rig/kits.yaml` > 24 | `deploy.sh` creates exactly `kit-1`…`kit-24` |
| A bound chain outgrowing its letter | Binding is authoritative; it cannot be silently moved |
| Module `midi:` shorthand on an omni chain | Channel-implied form is dead automation there |
| Chain note channel 16, or a module `midi:` mapping on channel 16 | Reserved |
| CC 1 or CC 74 in any `midi:` block | Hardwired per-chain modulation |
| Duplicate `kit-N` assignment, or a symlink, in `.rig/kits.yaml` | |
| Invalid or missing sample / kit alias | |
| Non-finite values | |
| Undeclared send referenced by a module `send:` | |

Any slot in a capped group that a song does not declare compiles to `-empty-`.

## Chain letters

Assignment is capacity-aware, **not** declaration order, because capacity is
asymmetric (A=3, B=4, C=3, D=4). Two passes, both in declaration order:

1. Chains needing 4 slots claim **B**, then **D**.
2. Every remaining chain claims the next free letter in the fixed order
   **A, C, B, D**.

Pass 2 uses all four letters — restricting small chains to A and C would strand
them while B or D sat empty.

| Chains | Assignment |
|---|---|
| four ≤3-slot | 1→A, 2→C, 3→B, 4→D |
| one 4-slot, three ≤3-slot | 4-slot→B; others→A, C, D |
| two 4-slot, two ≤3-slot | 4-slot→B, D; others→A, C |
| three 4-slot | compile error |
| one bound to D, plus a new 4-slot chain | bound chain keeps D; new 4-slot chain takes B |

**A recorded binding in `.rig/state/chains/` wins and leaves the pool before
either pass runs.** The device stores no chain names; push records the
name→letter binding, pull uses it to attribute drift, the compiler assigns
letters only where no binding exists (#37, #58).

The rules are **total**: every capacity-valid input has exactly one assignment,
and a cold rebuild from the binding store reproduces it.

## Note channels

Independent of letters, deliberately. Adding a module can change a chain's
letter; a shifting MIDI channel would silently break the DAW mapping.

- Default = declaration position. 1st chain → channel 1, 2nd → 2, and so on.
- Explicit override allowed: `midi: { channel: N }`.
- `0` = omni.
- An override **never renumbers** the other chains.
- Two chains resolving to the same numbered channel is a **lint warning**, not
  an error. Omni is exempt — an omni chain overlaps every numbered chain by
  design, and two omni chains are likewise not a collision.

**Omni is a routing mode, not "receive everything".** `midisel3` packs each
message as `[value, value, voice]`; on a specific channel `voice` is forced to
`0`, on omni it is the **incoming channel number** 1-16. So an omni chain is
MPE-style voice-split. Point only genuinely single-channel material at it.

## Module `midi:` blocks

```yaml
midi:
  size: 71                        # channel implied from the chain
  damping: {channel: 1, cc: 20}   # explicit channel
```

Implied form keeps the same CC number independent across chains, because the
compiled key is `channel * 128 + cc` and chains use distinct channels. Mapping
is rack-global — nothing scopes a mapping to the chain its module sits in.

On an omni chain the implied form is a **compile error**: channel `0` is not a
value Pd's `ctlin` ever emits, so the key could never match a real message.

## `mix:`

| Field | Range | Default | Meaning |
|---|---|---|---|
| `input-gain` | 0-200 | 100 | Mono physical input L. Input R stays muted, input pan centred |
| `output-gain` | 0-100 | — | Whole-chain gain |
| `balance` | 0-100 | 50 | Stereo centre |
| `width` | -100-100 | 100 | Optional. Negative swaps left/right |

With `b = balance/100` and `w = width/100`:

```
r-chout-l-pan-N = b - w/2
r-chout-r-pan-N = b + w/2
```

Both clamped to the device range 0-1. **Balance and width must keep both pans
within 0-1** — validate it. Pull uses the inverse.

Input pans are set by `input:`, not by `mix:`.
`input: { guitar: true }` writes L gain from `mix.input-gain`, centres L pan,
mutes R. `false` mutes both physical inputs. Gain **is** the gate — there is no
separate audio enable, and the declared default gain is `0`.

## Other fields

- **`send:`** sets that **slot's** send amount 0-100 to a named send. Per slot,
  not per chain, so a distorted slot can feed the reverb while the reverb-tail
  slot does not.
- **`note-thru:`** forwards notes to the next chain slot. Default `false`;
  `true` on the last module is a lint warning.
- **`sample:`** references `<kit-alias>/<filename>`. Resolved by the compiler
  against the repo folder's contents at push time.
- **`.rig/kits.yaml`** maps alias → `kit-N`. Parse and validate it here. Kits
  can move slot numbers without touching any song file.

## Verification

- Round-trip of a commented song file is **byte-identical**.
- Every validation failure in the table above has its own test.
- Letter assignment reproduces all five worked examples, including the bound
  case.
- A cold rebuild from `.rig/state/chains/` reproduces the same assignment.

## Done when

The full example song in `../docs/schema.md` parses, round-trips
byte-identically, and every listed hard error fires with a distinct message.
