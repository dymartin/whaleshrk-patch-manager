# MIDI

## CC mapping

The `midi-mapping.cc` key is **not** a CC number:

```
key = midi_channel * 128 + cc_number
```

Channel is 1-16 as emitted by Pd's `ctlin`, so valid keys run 128-2175. CC
scaling is linear over the parameter's full range:
`value = min + (midi/127) * (max-min)`.

Mapping is **rack-global**, keyed by `(channel, cc)` — nothing scopes a mapping
to the chain its module sits in. Independence between chains comes entirely from
chains using distinct channels.

## Program Change

MEC scans preset directories once at startup with `scandir(..., alphasort)`,
keeping only subdirectories that contain a `params.json`. Incoming Program
Change is used directly as a zero-based vector index; out of range is logged and
ignored. There is no MIDI load-by-name command. Channel 16 is reserved for this
control path.

Two consequences the compiler depends on:

- **Numeric prefixes must be fixed-width.** `"10-x"` sorts before `"2-x"`, so an
  unpadded prefix desynchronises the index from the program value for everything
  above 9. Pad to three digits. Silent placeholders fill the gaps below the
  highest program in use, keeping the vector contiguous.
- **`Init` sorts last.** Digits precede letters, so the protected `Init`
  directory always lands after the managed presets and never displaces a song's
  index.

### The scan order is locale-independent for this scheme

`alphasort` compares with `strcoll`, so the sort depends on `LC_COLLATE`.

`Rack::loadSettings` and `KontrolRack_loadresources` each call
`setlocale(LC_ALL, "en_US.UTF-8")` immediately before their `scandir`. Nothing
else in the process sets a locale — Pd 0.53.1's only `setlocale` call is in
`z_libpd.c`, which is not part of the `pd` binary.

**Observed 2026-08-08:** `locale -a` on the S2 returns `C`, `C.utf8`,
`en_GB.utf8`, `POSIX`. **`en_US.UTF-8` is not generated**, so that `setlocale`
always fails, returns `NULL` and changes nothing. The effective collation is
`C` — not one of two possible outcomes, the only reachable one. `en_GB.utf8`
exists but nothing requests it.

The `en_US.UTF-8` analysis below is kept as the counterfactual, because the
source still asks for that locale: an image that ran `locale-gen` for it would
silently switch collation.

Under `C`, `strcoll` is bytewise `strcmp`. Under glibc's `en_US.UTF-8`,
collation comes from `iso14651_t1`, whose primary weight order places the ten
digits in one contiguous block immediately before the Latin block. Zero-padded
3-digit prefixes therefore order identically in both, and `Init` follows the
digit block in both.

The divergence is in everything that is *not* the prefix. Under `en_US.UTF-8`,
space, hyphen and underscore carry `IGNORE` at the first three levels, and case
is only a third-level difference; under `C` each is a byte sorting before digits
and letters. So ordering is guaranteed stable only between names that differ
inside the fixed-width digit prefix — which every managed preset does.

The practical hazard: a foreign preset directory whose name begins with
punctuation sorts *before* the managed block under `C` and *inside the letters*
under `en_US.UTF-8`, shifting every program index in the first case. It has to
contain a `params.json` to enter the vector at all, which excludes junk like
`.Trash-1000`.

### Presets created during a session are appended, not sorted in

`Rack::savePreset` appends an unknown preset id with `push_back`. A preset saved
on the device therefore sits at the **end** of the Program Change vector until
the next patch restart, when the scan re-sorts it into place. Any index the tool
reasons about is the sorted one, so device-created presets make live Program
Change disagree with the repo until a restart.

## CC 100 / 101 / 102 change and overwrite presets

Traced `mainctrlhandler.pd` → `mother.pd` → `main.pd`:

```
ctlin -> spigot (open only when CC number == r-midi-save-preset-cc)
      -> midisel2 (channel filter by r-midi-ch)
      -> >= 64 -> change -1 -> s osavepreset
main.pd:  r osavepreset -> sel 1 -> msg "savecurrentpreset" -> KontrolRack
```

With stock values: **a CC 102 of value ≥ 64 on MIDI channel 16 overwrites the
currently loaded preset on the device.** CC 100 and CC 101 select previous /
next preset by the same route.

There is no master disable. `r-midi-pgmgate` gates MIDI *program change*, not
these CCs. The only levers are `r-midi-ch` and the three CC numbers themselves,
and no numeric range includes an "off" value.

Consequences to design around:

- Never assign a chain to the same channel as `r-midi-ch`, and never let
  `r-midi-ch` be `0` (omni), which would make every channel a save trigger.
- Never map CC 100, 101 or 102 in a module `midi:` block on that channel.
- A DAW that happens to send CC 102 there destroys a pushed preset silently, and
  the drift shows up only on the next pull.

Project policy: keep `r-midi-ch = 16` and `r-midi-pgmgate = 1` for song-loading
Program Change. Forbid chain channels and module CC mappings on channel 16, and
never emit CC 100/101/102 there.

Flip side worth remembering: CC 100/101 is a legitimate way to advance a setlist
from the DAW. Out of scope, but it is the mechanism if that is ever wanted.

## The physical keyboard has one global destination

Keys arrive over OSC from the firmware — `r oscIn` → `routeOSC /key` →
`key <n> <v>` → KontrolRack — and are routed by the router's "Active" page:
`r-main-dest` (0-14) selects a single global active destination, gated by
`r-midi-notegate` (default 0, off). One destination for the whole rack, not a
per-chain gate like audio and MIDI note in. A song's top-level `keyboard` field
selects the initial chain; the compiler enables the note and control gates and
targets that chain's first slot. Channel 16 / CC 20 is the fixed global active-
destination selector for changing it while playing.
