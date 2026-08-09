# Slots, routing and the router

## Slot topology

All wiring lives inside `routers/hybrid/module.pd`. **The router is the rack** —
replacing it removes the four-chain layout, mixer, sends and input routing
together, so `s1` is effectively pinned to `routers/hybrid`.

| Slots | Wrapper | Signal I/O | Role |
|---|---|---|---|
| `a1-a3` `b1-b4` `c1-c3` `d1-d4` | `fullmodule` | 8 | Chain slots |
| `p1` | `premodule` | 6 | Send FX 1 (can feed P2) |
| `p2` | `postmodule` | 4 | Send FX 2 |
| `f1` `f2` | `premastermodule` | 4 | Master FX |
| `f3` | `mastermodule` | 4 | Master FX + multitrack capture |
| `m1-m3` `s1` `s2` | `auxmodule` | **0** | No audio path at all |

Chain capacity: **A=3, B=4, C=3, D=4**.

`s1` and `s2` are **system slots, not free slots**. Both shipped presets (`Init`
and `jam`) hold `s1 = routers/hybrid` and `s2 = clocks/transport`, and neither
is ever `-empty-` — unlike `f1`-`f3`, `p1`-`p2` and the chain slots, which vary
between the two. The compiler must always emit both.

Signal flow is strictly series within a chain (`chainin N → a1 → a2 → a3`). No
parallel branches. Parallelism comes three ways:

- Multiple instruments in one chain **sum**. `fullmodule` mixes the slot's dry
  input with the module output; with no `thru_gain` parameter the wrapper
  defaults it to 100.
- Every chain slot has parallel send taps to `p1` and `p2`.
- The four chains run in parallel into the mixer.

A module placed in an aux slot (`m1-m3`, `s1`, `s2`) receives no audio. Silent —
the device reports nothing.

**No DSP gating exists:** no `switch~` or `block~` in wrappers, router, or
`-empty-`. All 24 slots always run; two module instances always cost twice the
DSP. Share cross-chain FX through a send slot.

## Chain inputs

Source: `subpatches/chainin.pd`, traced through actual Pd connections.

`chainin` carries audio L/R, `notein`, `bendin`, `ctlin` and `touchin`
**simultaneously**, with independent gates. A chain can take guitar audio and
MIDI notes at once — it is not a selector.

**Audio path.** `inlet~ inL` / `inlet~ inR` → `*~` scaled by
`r-chin-l-gain-N / 100` (smoothed through `lop~ 5`) → `o_2pan` positioned by
`r-chin-l-pan-N` / `r-chin-r-pan-N` → chain.

There is no separate audio enable. **Gain *is* the gate**, and its declared
default is `0` — audio input is muted until something writes a non-zero gain.
Range is 0-200, so `100` is unity and above that is boost.

**Pan defaults keep the two inputs hard-apart:** `r-chin-l-pan-N` defaults to
`0` (hard left) and `r-chin-r-pan-N` to `1` (hard right). A *mono* source into
input L therefore lands hard left unless its pan is also moved. Anything
compiling a `guitar: true`-style field has to decide gain **and** pan.

**MIDI note path.** `notein` → `midisel3` (channel filter) → `spigot` whose gate
inlet is driven by `r-chin-midigate-N` (default `1`).

**Control path is *not* gated.** `ctlin`, `bendin` and `touchin` go through
their own `midisel3` instances into a `spigot 1` **whose right (gate) inlet is
never connected**, so it is permanently open. `r-chin-midigate-N` is wired to
that spigot's *left* (data) inlet instead — an upstream slip, which means
toggling the gate injects a stray value into the ctrl outlet, and means

> `r-chin-midigate-N` gates **notes only**. Control changes reach the chain
> regardless of it.

The compiler always enables the gate. Disabling it later still permits CC
automation.

**CC 1 and CC 74 are hardwired.** `ctlin` feeds `route 74 1`, and the four
control sources pack to fixed indices: bend → `0`, CC 1 → `1`, CC 74 → `2`,
aftertouch → `3`. These are per-chain module modulation. Reserve both CC numbers
rather than using them for parameter automation.

Channel filtering applies to controls as well as notes — the same
`r-chin-midich-N` feeds every `midisel3` — so per-chain CC independence is real.

`r thru_gain-$1` appears in `chainin.pd` with no connections. Dead receive.

### Omni is a voice split, not a merge

Source: `subpatches/midisel3.pd`.

`r-chin-midich-N` of `0` means omni: a non-matching channel falls through a
`spigot` gated by `midiCh == 0`.

But omni does a second thing. Each message is packed as `[value, value, voice]`,
and the `voice` element is chosen by `sel 0` on the channel parameter:

| `r-chin-midich-N` | `voice` element |
|---|---|
| 1-16 (specific) | forced to `0` |
| `0` (omni) | the **incoming channel number**, 1-16 |

The patch comments *"send on voice 0 if ! multi channel"*.

So an omni chain is MPE-style: notes arriving on channels 1-16 are distributed
across voice indices 1-16, not merged onto one voice. A module with fewer voices
than the channels in use can silently drop or misroute material. **Omni is not a
drop-in "receive everything" setting** — treat it as a routing mode, and only
point genuinely single-channel material at it.

## Full `s1` parameter surface

`routers/hybrid` declares far more than the per-chain block. The compiler owns
`s1` entirely, so it owns all of this, and every value it does not write takes
the `module.json` default.

| Group | Parameters | Defaults |
|---|---|---|
| Per chain slot (a1-a3, b1-b4, c1-c3, d1-d4) | `r-gain-<slot>` 0-100, `r-notethru-<slot>` bool, `r-sendP1-<slot>` 0-100, `r-sendP2-<slot>` 0-100 | 100, 0, 0, 0 |
| Send returns | `r-gain-p1\|p2` 0-200, `r-hpf-p1\|p2` 0-250, `r-bypass-p1\|p2` bool, `r-sendP2-p1` 0-100 | 100, 0, 0, 0 |
| Master FX | `r-gain-f1\|f2\|f3` 0-100, `r-bypass-f1\|f2\|f3` bool, `r-multitrack-f3` bool | 100, 0, **1** |
| Per chain (N=1-4) | `r-chin-midigate-N`, `r-chin-midich-N` 0-16, `r-chout-midich-N` 0-16, `r-chin-l/r-gain-N` 0-200, `r-chout-gain-N` 0-100, four pans | 1; **1,2,3,3**; 0; **0**; 100; 0/1/0/1 |
| Global | `screensaverState`, `screensaverGfx`, `screensaverTime` 1-60, `latencyComp` | 1, 1, 5, 1 |
| Active destination | `r-main-dest` 0-14, `r-midi-ch` 0-16, `r-midi-module-cc` 0-120 | 0, **16**, 0 |
| Pedals / aux | `r-midi-auxcc`, `r-midi-fscc`, `r-midi-expcc` | 69, 64, 4 |
| Preset control | `r-midi-pgmgate`, `r-midi-ppreset-cc`, `r-midi-npreset-cc`, `r-midi-save-preset-cc` | 1, 100, 101, **102** |
| Active gates | `r-midi-notegate`, `r-midi-ctrlgate` | 0, 0 |

The compiler pins `r-midi-module-cc` to 20. When a song declares `keyboard`, it
sets `r-main-dest` to that chain's first slot and enables both active gates.

The four pans per chain are `r-chin-l-pan-N`, `r-chin-r-pan-N`,
`r-chout-l-pan-N`, `r-chout-r-pan-N` — type `pan`, range 0-1, labelled "A In L
Pan", "A Out L Pan" and so on. Both sides default to the same hard-apart pair:
L pan `0`, R pan `1`. The **output** pair is what `mix.balance` and `mix.width`
compile into; see [../schema.md](../schema.md).

`r-notethru-<slot>` (default off) is a per-slot note pass-through — notes reach
the next slot in the chain. A chain whose second module also reads notes needs
it on.

`r-chin-midich-4`'s declared default is `3`, duplicating chain C — an upstream
slip. The compiler writes every chain's channel explicitly, so it never inherits
this. ORHACK's `jam` preset saves `4` there, a preset-level fix over the broken
default.

## Transport / clock (`s2`)

`clocks/transport` holds 48 parameters. Eight are musical, forty are sequencer
pattern slots (`p1_a` … `p10_d`, one per pattern per chain).

```
bpm            60-200, default 120
set_signature  3-7,    default 4
swing8 swing16 chaos metronome
midiin         default 1   slaves to incoming MIDI clock
midiout        default 0   does not send clock
```

`module.pd` uses `midirealtimein`, noting *"MIDI 248 = clock; 250 = start;
251 = continue."* With `midiin` on, the rig follows the DAW's clock, start and
continue.

**MIDI realtime clock carries tempo, start and stop — it does not transmit time
signature.** No such message exists, so `set_signature` is always a device-side
value.
