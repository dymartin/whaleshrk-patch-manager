# Pull

Pull turns drift into reviewable PRs.

1. Read every preset directory on the card.
2. Diff each `params.json` against `.rig/state/last-pushed/<song>.json`. The
   stored snapshot is the baseline, not a recompile — otherwise a changed
   catalog default reports as phantom drift and buries real edits.
3. Match managed presets to songs by the directory name **recorded** in
   `<song>.meta.json`, never by reconstructing it from the song file and never
   by setlist order. Reconstruction breaks on a repo-side rename that has not
   been pushed yet, and pull-before-push makes that the normal order. Ignore
   compiler-owned gap placeholders.

   A recorded preset absent from the card produces a warning and nothing else:
   pull never removes a song file, because the repo is authoritative for song
   existence and the device only for parameter values. If **every** recorded
   preset is missing, abort — that is a wiped or foreign card, not news about
   one song.
4. Per drifted song: reverse-map only what moved, edit the song YAML in place
   preserving comments, commit to its own branch, open a PR via `gh`.
5. Ignore card presets no recorded song claims. The repo is authoritative for
   whether a song exists; the device is not. Songs are hand-authored, and
   parameters are then experimented with on the device — that direction, never
   the reverse.
6. Ignore media entirely.

One branch and PR per drifted song; unrelated songs never share reviews.

**Branch identity is deterministic:** `pull/<song-slug>`, a pure function of
the song, with no timestamp or counter. A later pull force-pushes that branch
and reuses its open PR, replacing earlier unmerged drift. A timestamped name
would accumulate stale branches and duplicate PRs instead.

A song that cannot be cleanly reverse-mapped — for example referencing a module
absent from the catalog — aborts for that song only, with no partial write.
Every other drifted song still processes.

## What drift covers

Captured and reverse-mapped into a song field: all chain-module parameters,
module `midi:` CC mappings, per-slot `send:` amounts, `note-thru`, router
settings (per-chain input/output gain, balance/width, MIDI channel), and
sample selection.

**Module placement is captured only as a precondition, not as an edit.**
Every occupied or empty slot's `moduleType` must match what the song already
declares before any of its parameter drift is trusted; a mismatch (a
different module physically occupying the slot, or a slot the song leaves
undeclared now holding something) aborts that song with `MODULE_IDENTITY_DRIFT`.
This is not a missing-schema-field case — `rig.song.model`'s `ModuleSlot.key`/
`ModuleUse.key` is exactly where a module-identity change would land.
Capturing it would mean re-deriving that slot's whole parameter set against
the newly-observed module (an emission, not an edit to what moved), and scope
was deliberately kept narrower than that because the rig's owner does not
edit module placement on the device.

**Sample *selection* is captured; sample *files* are not.** `samp_source` and
`samp_select` are ordinary parameters, so a sampler pointed at a different file
reverse-maps to a changed `sample:` field like any other drift. What pull
ignores is the media tree itself. `samp_source` selecting the shared
`samples/`, `loops/` or `synths/` folders (25-27) has no kit-alias form in the
schema at all (`docs/platform/samples.md`) and aborts that song with
`SAMPLE_FOLDER_UNREPRESENTABLE` rather than guessing.

**Mod-bus routing and CC mappings outside a chain module slot have no song
field to receive them**, even though the device's `params.json` can carry
both (`mod-mapping.bus` on any slot; `midi-mapping.cc` on `f1`-`f3`, `m1`-`m3`,
`p1`-`p2` — `midi:` is a chain-module-only field, see `rig.song.model`). Drift
there aborts that song with `UNSUPPORTED_DRIFT` instead of being silently
dropped. The same abort catches drift on the router's compiler-pinned safety
fields (`r-midi-ch`, `r-midi-pgmgate`, `r-chin-midigate-N` —
[../platform/routing.md](../platform/routing.md) "Traps") and on `s2` transport
params (decision #26: no song field exists for tempo/clock) — both worth a
human looking at rather than the tool guessing.

**A decoded value that `rig.song.validate` would hard-reject is never
written.** CC 1/74, channel 16, and any channel outside a field's valid
range are all hard validation errors, but the device can hold them anyway —
that's the nature of drift, the device diverging from anything the compiler
would produce. Writing one straight into `midi: {channel:}` or a module's
`midi:` block would hand back a song file that parses but fails validation
later, in a more confusing place than where the problem was actually found;
that aborts the song with `RESERVED_MIDI_VALUE_DRIFT` instead.

**Program is not reverse-mapped.** A preset is matched to its song by the
*recorded* directory name (decision #55), never by comparing prefixes, so a
changed numeric prefix means the recorded name is missing from the card
(warns and is skipped, above) rather than drift this step ever sees.

Not captured: sequencer patterns, morpher banks, media files. See
[../decisions.md](../decisions.md) #1 and #5.

**The drift baseline is written by push**, into
`.rig/state/last-pushed/<song>.json` (the compiled `params.json`, byte-exact)
and `<song>.meta.json` (the directory name and program as pushed). A song
that has never been pushed therefore has no baseline and cannot drift; that
is the correct reading, since the repo defined it and the device has not been
told about it yet.

**Chain letters are honoured, not recomputed.** Declaration order alone will
not reproduce an existing assignment — a 3-module chain on D would be
reassigned to C by the capacity rule, and the next pull would report drift on
a song nobody touched. So `.rig/state/chains/<song>.json` records each
name→letter binding and **the compiler honours a recorded binding instead of
assigning a letter**. Fresh assignment applies only to unbound chains. If a
later edit makes a bound chain outgrow its letter, that is a hard compile
error. Renaming a chain moves its binding — see
[maintenance.md](maintenance.md).

**Sample selection is reverse-mapped, not defaulted.** A `samplement` module
carries `samp_source` and `samp_select`; pull turns those back into a
`sample:` field:

1. `samp_source` → folder via the decode table in
   [../platform/samples.md](../platform/samples.md); `kit-N` → alias by reverse
   lookup in `.rig/kits.yaml`.
2. `samp_select` → index by inverting the position formula against the repo
   folder's current listing. Safe to invert, because push keeps the device and
   repo folders in lockstep.
3. `samp_source` of `0` or `-1` means nothing selected — emit no `sample:`
   field.

Skipping this is silent data loss: with no `sample:` field, decision #13 fills
`samp_source` from its catalog default of `0`, and the next push replaces a
working sampler chain with silence.

The PR body states that names were derived and invites renaming before merge.
Renaming a chain is safe as long as the binding moves with it — see
[maintenance.md](maintenance.md).
