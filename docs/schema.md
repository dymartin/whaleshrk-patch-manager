# Song Schema

One musician-facing file per song: `songs/<slug>.yaml`. No device slot ids,
`kit-N`, raw CC keys, or `moduleType` paths.

## Shape

```yaml
song: Vellichor
program: 12                         # MIDI PC 12 on channel 16

sends:
  reverb:                          # -> p1
    module: plateverb@orhack
    size: 70
  space:                           # -> p2
    module: clouds@orhack

master:                            # -> f1, f2, f3 in order
  - marginal@orhack: { low: 40 }
  - bus-comp@orhack

mod-sources:                       # -> m1, m2, m3; empty unless declared
  - lfo@orhack: { speed-1: 30 }

chains:
  - name: pads                     # 1st declared -> MIDI channel 1
    input: { guitar: false }       # 4 modules -> compiler assigns chain B
    mix: { output-gain: 90, balance: 50 }
    modules:
      - rings@orhack:
          structure: 45
          midi: { structure: 74 }  # channel 1 implied
          note-thru: true
      - warp@orhack:
          drive: 30
          send: { reverb: 40 }
      - spiraldelay@orhack:
          send: { space: 25 }
      - eq-iv@orhack

  - name: guitar                   # 2nd declared -> MIDI channel 2
    input: { guitar: true }        # 2 modules -> compiler assigns chain A
    mix: { input-gain: 100, output-gain: 100, balance: 50, width: 100 }
    modules:
      - warp@orhack:
          drive: 55
          send: { reverb: 20 }
      - samplement@orhack:
          sample: warehouse/kick_808.wav
```

## What the song file does not contain

**System slots — module identity only.** The compiler always emits
`s1 = routers/hybrid` and `s2 = clocks/transport`. Both are structural — the
router *is* the rack, and neither is ever `-empty-` in any shipped preset. No
song field chooses what occupies `s1` or `s2`.

This fixes module identity, not parameters. `s1` holds router per-chain state —
`r-chin-midich-N`, `r-chin-l/r-gain-N`, the pans, every `r-sendP1/P2-<slot>`. So
`input:`, `midi: { channel: }` and per-module `send:` compile *into* `s1`'s
params. Those fields are the supported way to reach them; there is no direct
`s1:` block.

**Two of Prompt.md's four "input types" are not inputs.** Only guitar audio and
MIDI note in are per-chain gates on the device:

- *Sample playback* is a module — `samplement@orhack` in a chain slot, selected
  like any other rather than gated.
- *The Organelle's physical keyboard* routes to a single global active
  destination via the router's `r-main-dest`, gated off by default. Not
  per-chain, so it has no schema field. See [platform/midi.md](platform/midi.md).

**Tempo and clock.** `clocks/transport` compiles to defaults with `midiin = 1`,
so the rig slaves to the DAW's MIDI clock for tempo, start and continue. Nothing
tempo-related appears in a song file. `set_signature` stays at its default of
4 — MIDI clock cannot transmit time signature, and signature is inert with
sequencers out of scope and `metronome` at 0.

## Rules

**Program** is the raw MIDI Program Change value `0`-`127`. Channel 16 is
reserved for preset control. Two songs sharing a `program` is a hard compile
error — the device would index one of them unreachably.

Device directories carry the program value **zero-padded to three digits**
(`000-`…`127-`), because MEC sorts the directory scan as text and uses the
resulting index as the Program Change number. Unpadded, `10-tide` sorts before
`2-vellichor` and every song above program 9 loads the wrong preset. See
[platform/midi.md](platform/midi.md).

Silent placeholders fill unused program values below the highest one in use, so
the index stays aligned. A placeholder holds only a `params.json` with
`s1 = routers/hybrid`, `s2 = clocks/transport` and every other slot `-empty-`:
structurally valid, audibly silent, free of sidecars, so loading one cannot
leave stale arrays behind.

`Init` is protected; it sorts after every digit-prefixed directory, so it never
displaces a song's index. Pull strips prefixes and ignores placeholders.

**Song name** is sanitised to a portable, case-insensitive filename. Names must
not collide after sanitisation.

**Chains** are named freely. Declaration order determines the MIDI channel
(1st → channel 1). The compiler assigns device letters separately and
capacity-aware: chains needing 4 slots get B or D, others get A or C. Letters
and channels are decoupled deliberately — adding a module can change a chain's
letter, and a shifting MIDI channel would silently break the DAW mapping.

Assignment runs in two passes, both in declaration order:

1. Chains needing 4 slots claim **B**, then **D**.
2. Every remaining chain claims the next free letter in the fixed order
   **A, C, B, D**.

Pass 2 uses all four letters — a 3-slot chain sits happily in a 4-slot letter,
and restricting it would strand chains while B or D sat empty.

| Chains | Assignment |
|---|---|
| four ≤3-slot | 1→A, 2→C, 3→B, 4→D |
| one 4-slot, three ≤3-slot | 4-slot→B; others→A, C, D |
| two 4-slot, two ≤3-slot | 4-slot→B, D; others→A, C |
| three 4-slot | compile error |
| one bound to D, plus a new 4-slot chain | bound chain keeps D; new 4-slot chain takes B |

**A recorded binding wins, and leaves the pool before either pass runs.** The
device stores no chain names, so push records the name→letter binding; pull uses
it to attribute drift, and the compiler assigns letters only where no binding
exists. That is what lets an adopted song keep the letters the device actually
had — see [workflows/pull.md](workflows/pull.md).

Renaming a chain must rewrite its binding in the same commit, since the binding
is name-keyed. A bound chain outgrowing its letter is a hard compile error.

The rules are total: every capacity-valid input has one assignment, and a cold
rebuild from the binding store reproduces it.

## Capacity limits

All are hard compile errors, never silent truncation:

| Limit | Cap |
|---|---|
| Chains | 4 |
| Songs sharing one `program` | 1 |
| Modules per chain | 3, or 4 on the two 4-slot chains |
| Chains needing 4 slots | 2 |
| Sends | 2 |
| Master FX | 3 |
| Mod sources | 3 |
| Kit aliases in `.rig/kits.yaml` | 24 |

Any slot in these groups a song does not declare compiles to `-empty-`.

**Modules** are keyed `slug(display)@source`. `@orhack` is the built-in set;
community modules use their Patchstorage slug. See [catalog.md](catalog.md).

**Parameters** use `slug(label)` from `module.json`. Where a module repeats a
label, an index suffix follows declaration order (`amount-1` … `amount-16`).
Anything unmentioned compiles to the catalog default for the pinned version.

**`midi:`** maps parameters to CC numbers, in either form:

```yaml
midi:
  size: 74                        # channel implied from the chain
  damping: { channel: 1, cc: 20 } # explicit channel
```

The implied form keeps the same CC number independent across chains. Reserve
CC 1 and 74 — the device consumes them per-chain already.

**On an omni chain the implied form is a compile error.** The CC key space is
`channel * 128 + cc` for channels 1-16; channel `0` is not a value Pd's `ctlin`
ever emits, so a key built from it could never match a real message and the
automation would be silently dead. Every `midi:` entry on an omni chain must
state its channel.

**`send:`** sets that slot's send amount (0-100) to a named send. Amounts are
per slot, not per chain, so a distorted slot can feed the reverb while the
reverb-tail slot does not.

**`note-thru:`** forwards notes to the next chain slot. Default `false`; `true`
on the last module is a lint.

**`mix:`** exposes per-chain mixing:

- `input-gain`: mono physical input L, `0`-`200`; input R stays muted and input
  pan stays centred.
- `output-gain`: whole-chain gain, `0`-`100`.
- `balance`: stereo centre, `0`-`100`, default `50`.
- `width`: optional signed stereo width, `-100`-`100`, default `100`; negative
  swaps left/right. Balance and width must keep both device pans within `0`-`1`.
  Pull derives both, preserving arbitrary pan pairs.

With `b = balance / 100` and `w = width / 100`, the output pans are
`r-chout-l-pan-N = b - w/2` and `r-chout-r-pan-N = b + w/2`, both clamped to
`0`-`1`; pull uses the inverse. The input pans (`r-chin-l/r-pan-N`) are set by
`input:`, not `mix:` — see [platform/routing.md](platform/routing.md).

`input: { guitar: true }` writes L gain from `mix.input-gain` (default `100`),
centres L pan, and mutes R. `false` mutes both physical inputs.

**`sample:`** references `<kit-alias>/<filename>`. The compiler resolves it to a
positional value against the repo's sample folder. See [media.md](media.md).

**MIDI is always enabled** on every chain. Each chain's note-input channel comes
from its declaration position (1st → 1, 2nd → 2, …), compiling to
`r-chin-midich-N`.

A chain may override that:

```yaml
chains:
  - name: pads                  # 1st -> channel 1
  - name: drones
    midi: { channel: 0 }        # omni: receives every channel
  - name: guitar                # 3rd -> channel 3
```

Channel `0` is omni — the chain accepts note material on any channel, for global
parts. An override never renumbers the other chains.

Two chains resolving to the same numbered channel is a lint, since it destroys
their independence. Omni is exempt: an omni chain overlaps every numbered chain
by definition, and that is its purpose. Two omni chains are likewise not a
collision.

This **note input** filter differs from module `midi:` channels, which select
CC-mapping keys; see [platform/midi.md](platform/midi.md) for why they are
separate mechanisms.

Channel 16 is forbidden for chain notes and module `midi:` mappings. It carries
song Program Change and ORAC's unavoidable preset-control CCs.

## Lint policy

Errors cover deterministic breakage/destruction: wrong slot class; CC 1/74;
channel-16 conflicts; invalid or missing samples or kits; non-finite values;
undeclared sends; unsafe, reserved, overlong or case-colliding paths; duplicate
runtime module paths; unsafe archives.

Warnings cover valid but suspicious choices: instrument after effect, shared
numbered channel, multi-target CC, unused send, empty chain, unselected sampler,
above-unity gain, narrow width, ignored non-`.wav` media, final-slot
`note-thru`. Warn about repeated DSP-heavy modules only with measured cost data.

## Invariants

- Nothing in a song file is a device identifier.
- A song file plus `.rig/modules.lock` fully determines the compiled output,
  including chain-letter assignment — the capacity rules and the
  declaration-order tie-break are total.
- Sequencer patterns and morpher banks never appear. They are compiler-owned.
- Round-tripping preserves comments and formatting (ruamel.yaml round-trip mode).
