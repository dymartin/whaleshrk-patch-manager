# Module Catalog

Metadata only: module identity and source. No patch binaries or Pure Data
source.

Lives in `.rig/catalog/`, generated. `.rig/modules.lock` pins versions. Both are
committed. `rig catalog update` is the only rebuild path; ordinary builds and
pushes never discover live data. CI regenerates from the frozen fixture and
fails on diff. Each build records generator/schema version.

## Sources

Two provenance types:

- **`@orhack`** — modules shipped inside ORHACK 0.52b.
- **Community** — Patchstorage uploads, keyed by upload slug.

Prompt.md's third type, "stock Organelle default patches," is invalid: those are
standalone `main.pd` patches, not chain-slot ORAC modules.

Discovery is the union of Patchstorage platform `3371` and tag `1483`, deduped —
145 candidates as measured.

An upload contributes **one catalog entry per module it contains**, however
many. What is excluded is not a size but a kind: archives redistributing the
whole rack (`orac-2-0-for-organelle`, `instant-input-orac-2-0`, `orac`, ORHACK
itself). See [decisions.md](decisions.md) #60.

## Keys

```
slug(module.json "display") @ source
```

`@orhack` for built-ins, the Patchstorage upload slug for community modules.
Qualification is unconditional — every key carries its source, so there is no
"who wins" rule and adding a colliding module never renames an existing key.

Two slugification rules, both found by measurement:

- `+` maps to `-plus`. Otherwise "Braids"/"Braids +" collide, as do
  "Plaits"/"Plaits +".
- Skip `module.json` files nested inside another module's directory. Otherwise
  `effects/delay/spiraldelay/module` collides with its own parent. This also
  matches what `loadModuleDir` registers.

With those, keys are unique across the measured catalog. Without the `@source`
qualifier, 34 keys covering 69 entries collide — mostly ORHACK built-ins against
standalone re-uploads of the same module (`plateverb`, `clouds` vs `clds-pd`,
`samplement`). With it, zero.

### Measured catalog size

Re-derived against the gate below, both slug rules applied:

| | |
|---|---|
| Patchstorage candidates | 145 |
| pass the gate | 122 |
| of those, single-module uploads | 120, contributing 120 |
| of those, module packs | 2, contributing 15 |
| ORHACK built-ins, selectable | 65 |
| **catalog entries** | **200** |

Rejected: 14 not modules, 5 wrong-architecture, 3 rack redistributions, 1
malformed JSON.

The earlier "32 of 190" figure predates the gate: it counted wrong-architecture
uploads, counted `-empty-` as a module, and applied neither slug rule.

The two packs are `sequencers-bpm` (Arp Seq, Click, Clock, PolyBeats, Punchy,
Sampler24, Seq) and `orac-cvtools` (eight CV in/out modules). Verified at the
measured install categories — `sequencers` and `utility/audio` — none of the 15
collides with a built-in runtime path.

## Parameter names

`slug(label)` from `module.json`, with an index suffix following declaration
order where a module repeats a label. Derived at ingest, recorded in the catalog
entry alongside the real parameter id, min, max, default and type.

Defaults are pinned per module version — a module update changing a default must
surface as a reviewable change, not silent drift.

## Validation gate

Ingest rejects rather than catalogues. The counts above are what this gate
produced against the 145 real candidates.

**Hard reject:**

- Archive lacks `<dir>/module.json` **and** `<dir>/module.pd`. Catches
  mis-tagged plain Organelle patches — 14 of 145.
- Archive carries a `main.pd` at its package root. `main.pd` is the rack entry
  point and no chain-slot module has one, so this separates rack
  redistributions from module packs mechanically: all three measured
  redistributions ship `orac/main.pd`, neither pack ships one. A `main.pd`
  deeper inside a module directory is that module's own business — warn, do not
  reject.
- `module.json` does not parse.
- Any bundled external fails the ABI check. Evidentiary status differs per
  criterion, and the difference matters:

  | Criterion | Status |
  |---|---|
  | `EM_ARM` (0x28) | Enforced, and the only one observed rejecting real data — every wrong-arch hit in the 145-candidate sample was x86 |
  | ELF32 | Enforced, never observed firing — no ELF64 binary appeared in the sample |
  | hard-float (`e_flags & 0x400`) | Enforced, never observed firing — no ARM binary in the sample was soft-float |
  | EABI5 | **Not gated.** Logged during ingest and found uniformly version 5 |
  | little-endian | Enforced: `e_ident[EI_DATA] == ELFDATA2LSB` |

- Reject archive traversal, absolute paths, symlinks, case-colliding entries,
  and configured expanded-size/file-count limits.
- Reject duplicate runtime `moduleType` paths, including community paths
  shadowing built-ins. Runtime loads by path, not catalog key.
- Reject modules reading/writing unmodelled preset sidecars, detected as below.

### Detecting preset sidecars

The rule needs a method, because sidecar files are written by Pure Data code
inside the module, not by anything the preset system declares.

Scan every `.pd` file in the archive for `read`/`write` messages whose argument
path contains `presets` — the same scan that produced the built-in inventory in
[platform/state.md](platform/state.md). Resolve `$0`/`$1`-style substitutions
textually; a pattern that cannot be resolved counts as unmodelled.

Any resulting pattern that is not one of the five modelled built-in patterns
rejects the module. A module with no such message is stateless and passes. The
compiler can only produce a deterministic sidecar set for patterns it has
templates for, so an unmodelled one means a preset whose device state is
whatever the previously loaded preset left behind.

This is a *textual* scan, deliberately conservative: dynamic path construction
it cannot resolve rejects rather than warns.

The ABI check is a one-byte test catching real shipping breakage. Every
wrong-arch hit found was the same x86 `tb_peakcomp~` / `ds_peakcomp~` pair,
propagated into `bus-comp`, `strip`, `percussions+`, `8rac` — and ORHACK itself.

**Warn, do not reject:** `DT_NEEDED` entries outside the known-good library set
and not bundled in the archive.

The known-good set is not hand-written — it is derived, from the pinned rootfs's
own libraries and the shared objects ORHACK ships in `externals/`. Measured
across ORHACK 0.52b's 64 ELF binaries:

| From the rootfs | Bundled by ORHACK |
|---|---|
| `libc.so.6`, `libm.so.6`, `libstdc++.so.6`, `libgcc_s.so.1`, `libatomic.so.1`, `libpthread.so.0`, `libdl.so.2`, `libasound.so.2`, `libusb-1.0.so.0`, `libcairo.so.2` | `libcjson.so`, `liboscpack.so`, `libmec-*.so`, `libpicodecoder.so`, `libeigenapi.so`, `libsplite.so`, `libportaudio.so`, `librtmidi.so` |

A dependency satisfied by a library inside the candidate archive is also fine.
Anything else warns: it will resolve on the device only by luck.

**Strip on install:** `__MACOSX/`, `._*` AppleDouble files, `.DS_Store`, editor
swap files, `.dll` binaries. Real archives contain all of these.

A bundled `abl_link~.pd_linux` is a special case: Organelle_OS renames it to
`.orig` on every patch launch (see [platform/runtime.md](platform/runtime.md)),
so shipping one means a card write per launch and a module whose external
silently never loads. Strip it, and treat a module needing it as unsupported.

Passing is necessary, not sufficient. It gives `static-only` confidence. Only a
hardware check raises that, and only for load cost and load errors; see
[validation.md](validation.md).

## Versioning

`revision` is author-authored free text and unusable. Track `updated_at` plus
the detail endpoint's file `id`, verified with a content hash of the archive.

Change detection is cheap: two list calls cover every candidate's `updated_at`;
only changed entries need a detail fetch.

Push installs exactly what `.rig/modules.lock` names and never auto-upgrades. It
reports available updates. Upgrading is an explicit command producing a
reviewable repo diff — this supersedes Prompt.md, which specified auto-install.

## Install layout and category

Community modules install to
`<card>/media/orhack/user-modules/<category>/<name>/`, and **that path is the
`moduleType`**. Archives carry no category, so the catalog assigns it.

Role cannot be derived from the patch — signal I/O does not discriminate
instrument from effect (see [platform/modules.md](platform/modules.md)).
Category is mapped from the upload's Patchstorage category:

| Patchstorage | ORHACK folder |
|---|---|
| synthesizer | `instruments/synth` |
| sampler | `instruments/sampler` |
| sequencer | `sequencers` |
| effect | `effects/mod` |
| utility, sound, other, composition | `utility/audio` |

**Uploads carry multiple categories** — 28 of 100 sampled `orac`-platform
patches do, and 27 of those map to conflicting folders. Precedence, most
specific first:

```
sampler > sequencer > synthesizer > effect > utility/sound/other/composition
```

The first category present wins, making ingest deterministic and re-runnable.

Categories are a property of the *upload*, so every module in a pack inherits
one — `sequencers-bpm` maps all seven to `sequencers`, including Sampler24.
Every entry carries a `category_override` for when the mapping guesses badly, so
a pack member can be moved alone. A bad guess costs only a module filed oddly in
the device browser; `loadModuleDir` does not interpret the path.

Because the path *is* the `moduleType`, changing a category changes module
identity. Treat it like a version bump.

ORAC would let user modules shadow built-ins at the same path; ingest rejects
that collision because catalog keys cannot disambiguate runtime paths.

## Tags

Each entry carries a `tags` field, populated at ingest from Patchstorage tags
and categories. Unused by the CLI; it exists so the deferred chain
auto-assembly skill (see [overview.md](overview.md)) is buildable without
re-ingesting the catalog.
