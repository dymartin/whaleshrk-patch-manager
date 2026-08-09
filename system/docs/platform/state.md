# State and presets

## Where state lives

The Organelle firmware symlinks on every patch launch:

```
/tmp/patch → $USER_DIR/Patches/<PatchName>
/tmp/media → $USER_DIR/media
/tmp/data  → $USER_DIR/data
```

`USER_DIR` is `/usbdrive` when mounted, else `/sdcard`. ORHACK's `orac.json`
points at `/tmp/data/orhack`, so device state persists to the card. `orac.json`
is **not** the live config — it holds only `dataDir`, `mediaDir`,
`userModuleDir`.

| Path | Contents |
|---|---|
| `<card>/data/orhack/rack.json` | `{"currentPreset": "<name>"}` — nothing else. Keyed by directory *name*; see [Dangling `currentPreset`](#dangling-currentpreset) |
| `<card>/data/orhack/presets/<Name>/params.json` | Full rack state |
| `<card>/data/orhack/presets/<Name>/*.txt` | Sequencer + morpher state |
| `<card>/media/orhack/user-modules/` | Community module install target |
| `<card>/media/orhack/samples/`, `samples/loops/`, `samples/synths/`, `kits/kit-1..24` | Sampler playback sources |
| `<card>/media/orhack/recordings/` | Multitrack capture output — device-owned |
| `<card>/media/samples/` | Shared Organelle dir, written by the sampler — device-owned |

## Preset format

A preset is a **directory**, discovered as any `presets/` subdirectory
containing `params.json`; its directory name is its name. Presets are
name-keyed, with no slot or index order. Creating a directory creates a preset.

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

Saving writes **every** parameter of every module — no deltas, no omitted
defaults. Module ids are sorted, output is tab-indented. Identical rack state
produces a byte-identical file, so diffing is reliable.

On load, a slot whose live module type differs from the preset's `moduleType` is
swapped to match. `moduleType` is a path resolved against `userModuleDir` first,
then the built-in `modules/` directory.

Loading writes nothing. `rack.json` is written only by an explicit
`savesettings`, and `params.json` only by `savePreset`.

## State outside `params.json`

Five built-in modules persist state as loose `.txt` files inside the preset
directory: `sequencers/{overflow,overdrum,polystep,clips}` and
`mod-sources/morpher`. The Pure Data modules write them directly; the preset
system knows nothing about them.

Complete pattern inventory, from scanning every `read`/`write` of a `presets/`
path in the module tree:

| Module | Patterns |
|---|---|
| `mod-sources/morpher` | `p<N>.txt` (banks 1-16, 100 floats each) |
| `sequencers/clips` | `<slot>-slot-tracker.txt`, `<slot>-seq<n>x.txt` |
| `sequencers/overdrum` | `loop-<slot>-<track>.txt`, `metric-<slot>-<track>.txt`, `step-seq-note-…`, `step-seq-vel-…`, plus slot-tracker and seq |
| `sequencers/overflow` | as overdrum, plus `step-seq-length-<slot>-<track>-p<N>.txt` |
| `sequencers/polystep` | `<slot>-len.txt`, `<slot>-notes.txt`, `<slot>-vel.txt` |

**Every pattern is keyed by slot position, never by module identity.** Swap
`overdrum` for `polystep` in the same slot and the new module reads whatever the
old one left in those arrays. Adding files without clearing old state reproduces
that staleness bug.

**Failure mode when absent:** Pd's `array read` on a missing file logs an error
and leaves the array untouched — holding whatever the *previously loaded preset*
put there. A preset directory containing only `params.json` therefore does not
define device state.

The pinned ORHACK 0.52b `Init` preset contains 224
canonical `a1` sidecars contain no embedded slot name, so filenames can be
retargeted to any occupied supported stateful slot. The 16 `p<N>.txt` morpher
files are global.

Occupancy and sidecar presence are independent. `Init` has **every** chain slot
`-empty-`, yet ships 224 sidecars each for `a1`, `b1`, `c1` and 154 for `d1`.

## Dangling `currentPreset`

Startup order is fixed by `main.pd`: `loadbang` drives a `t b b` whose right
outlet fires first into `s rackloaded`, making every slot subpatch register the
module type hardcoded in the patch file; the left outlet then sends
`loadsettings rack`.

That hardcoded layout is **not** empty:

| Slots | Type declared in `main.pd` |
|---|---|
| `a1` | `sequencers/sequences` — path does not exist |
| `a2` | `instruments/modular/plaits+` — path does not exist |
| `m1` `m2` `m3` | `mod-sources/lfo`, `mod-sources/random`, `mod-sources/morpher` |
| `s1` `s2` | `routers/hybrid`, `clocks/transport` |
| everything else | `-empty-` |

`Rack::loadSettings` reads `currentPreset` from `rack.json`, builds the preset
list by scan, and calls `loadFilePreset` on the name unconditionally — the name
is never checked against the scanned list. A valid preset overwrites all 24
slots, because a saved preset always contains all of them; that is what normally
hides the two bad paths.

A dangling name aborts before any of that. `loadFilePreset` finds no
`params.json`, logs `unable to load preferences file`, and returns. So a
dangling pointer is not a startup failure and not a silent device — it boots
into the table above, with a working router and transport, no fallback to
`Init`, and `rack.json` untouched. Program Change indices are unaffected,
because the missing name was never in the scanned vector.

Two live consequences:

- **Next/prev preset both jump to index 0.** The search for the current name
  fails, leaving the target index at its `0` initialiser.
- **Saving materialises the default rack under the missing name.** The device
  `mkdir`s the directory and writes the live rack into it, including `a1` and
  `a2` at their two nonexistent module types, producing a preset that will not
  load correctly afterwards.

Upstream ORAC has the same two bad paths. A dangling `currentPreset` leaves the
bad slots live.
