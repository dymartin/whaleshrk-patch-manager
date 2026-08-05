# Phase 3 — Compiler

## Goal

Song model → preset directory. The core push logic, and a pure function of the
song file plus `.rig/modules.lock` plus `.rig/state/chains/`.

## Read first

`../docs/platform/routing.md` (full `s1` surface — the single most important
table in this phase), `../docs/platform/state.md`, `../docs/platform/midi.md`,
`../docs/platform/samples.md`, `../docs/media.md`, `../docs/schema.md`,
`../docs/decisions.md` #1, #2, #10, #13, #25, #26, #40, #48, #49, #50.

## Output shape

```
<program-prefix>-<sanitised-song-name>/
  params.json
  <sidecar>.txt …          only for occupied stateful slots
```

`params.json` is keyed by slot id:

```json
{
  "a1": {
    "moduleType": "instruments/synth/rings",
    "params":       { "<paramId>": <number|string>, ... },
    "midi-mapping": { "cc": { "<key>": ["<paramId>"] } },
    "mod-mapping":  { "bus": { "<bus>": ["<paramId>"] } }
  }
}
```

**Emit every parameter of every module — no deltas, no omitted defaults.**
Module ids sorted, tab-indented. That matches what the device itself writes, so
diffs against device output are clean and hash verification works.

## Slots

All 24 always emitted: `a1-a3` `b1-b4` `c1-c3` `d1-d4` `p1` `p2` `f1` `f2` `f3`
`m1-m3` `s1` `s2`. Undeclared chain, send, master and mod-source slots emit
`-empty-`.

Fixed system slots:

- `s1 = routers/hybrid`
- `s2 = clocks/transport`, transport defaults with `midiin = 1`, `midiout = 0`.

Module identity is fixed; `s1`'s parameter block is still **fully written** —
every chain's `input:`, note channel and per-slot `send:` compiles into it.

Mod-source slots default to `-empty-` (#2). Morpher sits in `m3` in stock ORHACK
by default rather than by choice; defaulting to empty means nothing reads
morpher `.txt`, so nothing can go stale.

## `s1` parameters the compiler owns

Whole `routers/hybrid` surface, from `../docs/platform/routing.md`. Every value
the compiler does not write takes the `module.json` default.

| Group | Parameters | Defaults |
|---|---|---|
| Per chain slot (a1-a3, b1-b4, c1-c3, d1-d4) | `r-gain-<slot>` 0-100, `r-notethru-<slot>` bool, `r-sendP1-<slot>` 0-100, `r-sendP2-<slot>` 0-100 | 100, 0, 0, 0 |
| Send returns | `r-gain-p1\|p2` 0-200, `r-hpf-p1\|p2` 0-250, `r-bypass-p1\|p2` bool, `r-sendP2-p1` 0-100 | 100, 0, 0, 0 |
| Master FX | `r-gain-f1\|f2\|f3` 0-100, `r-bypass-f1\|f2\|f3` bool, `r-multitrack-f3` bool | 100, 0, **1** |
| Per chain N=1-4 | `r-chin-midigate-N`, `r-chin-midich-N` 0-16, `r-chout-midich-N` 0-16, `r-chin-l/r-gain-N` 0-200, `r-chout-gain-N` 0-100, four pans | 1; **1,2,3,3**; 0; **0**; 100; 0/1/0/1 |
| Global | `screensaverState`, `screensaverGfx`, `screensaverTime` 1-60, `latencyComp` | 1, 1, 5, 1 |
| Active destination | `r-main-dest` 0-14, `r-midi-ch` 0-16, `r-midi-module-cc` 0-120 | 0, **16**, 0 |
| Pedals / aux | `r-midi-auxcc`, `r-midi-fscc`, `r-midi-expcc` | 69, 64, 4 |
| Preset control | `r-midi-pgmgate`, `r-midi-ppreset-cc`, `r-midi-npreset-cc`, `r-midi-save-preset-cc` | 1, 100, 101, **102** |
| Active gates | `r-midi-notegate`, `r-midi-ctrlgate` | 0, 0 |

Traps:

- **`r-chin-midich-4` declares default `3`**, duplicating chain C — an upstream
  slip. Write every chain's channel explicitly so it is never inherited.
- **Write `r-chin-midigate-N = 1` always** (#9). Enabling costs nothing — a
  message-domain spigot, no DSP — and a chain with no note-reading module is
  unaffected. Note also the gate reaches only notes; `ctlin`, `bendin` and
  `touchin` pass through a permanently-open spigot regardless.
- **Keep `r-midi-ch = 16` and `r-midi-pgmgate = 1`** so Program Change loads
  songs. Never let `r-midi-ch` be `0` — omni would make every channel a
  preset-save trigger.
- **Input pan defaults are hard-apart:** `r-chin-l-pan-N = 0`, `r-chin-r-pan-N =
  1`. A mono source into input L lands hard left unless its pan moves, so
  `input: { guitar: true }` must set gain **and** centre L pan, and mute R.

## Mixing

- `mix.input-gain` → `r-chin-l-gain-N`. Input R muted, input L pan centred.
- `mix.output-gain` → `r-chout-gain-N`.
- `balance`/`width` → both output pans, `b ± w/2`, clamped 0-1.
- Per-module `send: { <name>: amount }` → `r-sendP1-<slot>` or
  `r-sendP2-<slot>`, resolved through the song's `sends:` declaration order
  (1st → `p1`, 2nd → `p2`).
- `note-thru:` → `r-notethru-<slot>`.

## CC mapping

`midi-mapping.cc` key = `channel * 128 + cc`, channel 1-16, valid keys 128-2175.
Value is a list of parameter ids. Never emit CC 1, CC 74, or anything on channel
16.

## Preset directory name

**Zero-padded 3-digit** program prefix plus the sanitised song name:
`012-vellichor`.

MEC scans preset directories once at startup with `scandir(..., alphasort)`,
keeps only subdirectories containing `params.json`, and uses incoming Program
Change **directly as a zero-based vector index**. So:

- Unpadded, `"10-x"` sorts before `"2-x"` and every song above program 9 loads
  the wrong preset.
- Unused program values below the highest one in use need gap placeholders to
  keep the vector contiguous. **Deciding which programs need one is push's job**
  (`docs/workflows/push.md`) — it is the only phase that sees the whole selected
  song set. Compile owns the *shape*: expose a function that builds one
  placeholder preset for a given program number, and let push call it.

A gap placeholder is a preset holding `s1 = routers/hybrid`, `s2 =
clocks/transport` and 22 `-empty-` slots, **with no sidecar files** (#50). It has
to be loadable — Program Change can land on one — and empty slots mean no module
reads an array, so a placeholder cannot propagate staleness.

`Init` sorts after every digit-prefixed directory under both candidate locales,
so it never displaces a song's index. Never touch it.

## Samples

`sample: <alias>/<file.wav>` resolves to `samp_source` plus `samp_select`.

`samp_source` encoding — **not** the ordering its `[-1, 27]` range suggests,
because the decoding `sel -1 0 25 26 27`'s sixth outlet is the no-match
passthrough that drives the kits path:

| `samp_source` | Folder |
|---|---|
| `-1`, `0` | nothing selected |
| `1`-`24` | `kits/kit-N`, value used literally as N |
| `25` | `samples/loops` |
| `26` | `samples/synths` |
| `27` | `samples/` root |

Position within the folder:

```
index  = int( (samp_select / 100) × (N − 0.05) )        N = count of *.wav
```

To select file `k` of `N`, emit the **midpoint** of the valid interval for
maximum float tolerance:

```
samp_select = 100 × (k + 0.5) / (N − 0.05)
```

Listing order is POSIX `glob()`, which sorts — stable given identical folder
contents. Push owns those folders, which is what makes this exact.

## Sidecars

Retarget the pinned ORHACK `Init` sidecar templates to occupied stateful slots.
`Init`'s 224 canonical `a1` sidecars contain no embedded slot name, so filenames
retarget to any occupied supported stateful slot. The 16 morpher `p<N>.txt`
files are global.

Compile emits exactly the sidecars this song's occupied slots need — nothing
more. Removing a *previous* occupant's files is **push's job**
(`docs/workflows/push.md`): mirroring with deletions requires reading what the
card already holds, which is not a compile input.

Why push must do it at all — **mirror with deletions, never additively** (#40).
Sidecars are slot-keyed, not module-keyed: swap `overdrum` for `polystep` in the
same slot and the new module reads whatever the old one left in those arrays.
Pd's `array read` on a missing file logs an error and leaves the array holding
the **previously loaded preset's** contents.

## Verification

Compile a song and diff against a hand-built expected preset.

**Byte-comparison is scoped to `params.json` only.** The shipped `jam` and `Init`
presets carry sidecars for `-empty-` slots — `Init` has every chain slot empty
yet ships 224 sidecars each for `a1`, `b1`, `c1` and 154 for `d1`; `jam` holds
roughly 800 files including a `c1-slot-tracker.txt` for an `-empty-` slot. A
*correct* compiler never reproduces their directory listings. Listing
comparisons are informative, never a pass/fail gate.

Separately assert **directory-name ordering**: sorting the emitted names with
plain `strcmp` must place each preset at the index equal to its `program` value.

## Done when

Compiled `params.json` matches the hand-built expected file byte for byte, the
`strcmp` ordering assertion passes, and sample encoding has a test per folder
class.
