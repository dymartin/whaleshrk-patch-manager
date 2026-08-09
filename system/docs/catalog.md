# Module Catalog

**The catalog is a shopping list, not a mirror of Patchstorage.** It holds the
modules this rig actually uses. Adding one is a deliberate act: `rig catalog
add <slug>`.

Three committed pieces, each with one job:

| Path | Holds |
|---|---|
| `system/data/catalog/<key>.json` | Metadata: identity, parameters, category, tags |
| `system/data/modules.lock` | Version pin: upload slug, `updated_at`, file id, `archive_sha256`, `revision` |
| `system/modules/<slug>@v<revision>.zip` | The upload itself, byte-identical |

`rig catalog add` and `rig upgrade` are the only commands that reach the
network. Push, lint, tests and CI read the committed files and never open a
socket.

## The archive store

The upload's bytes travel with the repo. Two things depend on it:

- **Reproducibility.** [overview.md](overview.md) promises "same repo, same
  push, same rig — on any day." Pinning an upload id proves nothing once the
  author deletes or replaces that upload; retaining the bytes does. This
  reverses Prompt.md's "no vendoring" non-goal, which was written when
  vendoring meant mirroring all of Patchstorage.
- **Offline push.** A gig has no usable wifi. Push reads `system/modules/`, extracts
  to a temp dir, strips junk, and copies to the card.

Stored **unmodified**, so `archive_sha256` still verifies against what
Patchstorage published — stripping happens on the way to the card, not before
the archive is committed. Verified on every read, not just at `add` time: a
truncated clone or hand-edited archive must be caught before it reaches the
card.

`revision` names the file because it is the only human-readable version an
upload has. It is never an identity — see "Versioning". `rig catalog add`
**refuses** an archive whose revision matches one already stored but whose
bytes differ: that is an author replacing an upload without bumping it, the
silent-change case no diff would otherwise surface.

Two guardrails at `add` time: an archive past 5MB warns (every future version
of it stays in git history permanently; the median ORAC module is ~40KB), and
a slug already in the catalog refuses rather than silently re-adding.

## Sources

Two provenance types:

- **`@orhack`** — modules shipped inside ORHACK 0.52b.
- **Community** — Patchstorage uploads, keyed by upload slug.

Prompt.md's third type, "stock Organelle default patches," is invalid: those are
standalone `main.pd` patches, not chain-slot ORAC modules.

Patchstorage's API has no lookup-by-slug filter, so resolving one slug still
walks the platform `3371` / tag `1483` discovery list (stopping once every
wanted slug is found). That walk is a lookup mechanism, not an ingest scope:
only the named uploads are fetched, gated and stored.

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

With those, keys are unique across every module surveyed. Without the `@source`
qualifier, 34 keys covering 69 entries collide — mostly ORHACK built-ins against
standalone re-uploads of the same module (`plateverb`, `clouds` vs `clds-pd`,
`samplement`). With it, zero.

### The one-time ecosystem survey

The gate below was designed against the **whole** ORAC ecosystem, surveyed once:
the union of Patchstorage platform `3371` and tag `1483`, deduped, 145
candidates. Those numbers are evidence for the gate's shape, not a target the
catalog reproduces — the catalog now holds whatever this rig uses, plus 65
selectable ORHACK built-ins.

| | |
|---|---|
| Patchstorage candidates surveyed | 145 |
| passed the gate | 122 |
| of those, single-module uploads | 120, contributing 120 |
| of those, module packs | 2, contributing 15 |
| ORHACK built-ins, selectable | 65 |
| **entries, had everything been added** | **200** |

Rejected: 14 not modules, 5 wrong-architecture, 3 rack redistributions, 1
malformed JSON.

The earlier "32 of 190" figure predates the gate: it counted wrong-architecture
uploads, counted `-empty-` as a module, and applied neither slug rule.

The two packs are `sequencers-bpm` (Arp Seq, Click, Clock, PolyBeats, Punchy,
Sampler24, Seq) and `orac-cvtools` (eight CV in/out modules). At the measured
install categories — `sequencers` and `utility/audio` — none of the 15 collides
with a built-in runtime path. That held for all 135 community entries, not just
these 15 — see "Install layout and category" below for why: 6 of the other 120
single-module uploads *do* reuse a built-in's own directory name, and only
installing by qualified catalog key rather than raw archive directory name
keeps them all catalogued.

## Parameter names

`slug(label)` from `module.json`, with an index suffix following declaration
order where a module repeats a label. Derived at ingest, recorded in the catalog
entry alongside the real parameter id, min, max, default and type.

**Tuple shape is not uniform.** `[type, id, label, min, max, default]` (6
elements) holds for every type except `bool`, verified across all 67
built-in `module.json` files with no exception. `bool` carries no min/max —
`[type, id, label, default]` (4 elements) — since a boolean's range is
implicitly 0/1. One real community module (candidate 163108, "vj-fm") ships
a `bool` parameter with a spurious extra numeric element before the default;
the default is always the tuple's last element regardless of length, which
reads correctly for both shapes. `parameters` may also be entirely absent
(candidate 103456, "seq3") — a module with zero user-adjustable parameters,
not an error.

Defaults are pinned per module version — a module update changing a default must
surface as a reviewable change, not silent drift.

## Validation gate

Ingest rejects rather than catalogues, and runs on every `rig catalog add`.
The counts above are what this gate produced against the 145 surveyed
candidates.

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

### Reject ordering

The conditions above are mutually exclusive buckets — every one of the 145
surveyed candidates lands in exactly one of them or passes — but the measured
counts (14 not-a-module / 5 wrong-arch / 3 rack-redistribution / 1 bad-JSON /
122 pass) only reproduce under one specific check order. Several real
candidates only resolve to their bucket because of it, so the order is
load-bearing, not incidental. No test enforces it now that the survey corpus
is gone, which is exactly why it is recorded here: a refactor that reorders
these checks changes which archives the gate accepts, silently. Derived by
checking which order the measured buckets require:

1. **Archive safety** (traversal, absolute paths, symlinks, case collisions,
   size/count limits). Nothing in the archive's path structure — including
   whether a directory holds a module — can be trusted until the archive
   itself is safe to walk. Fires on zero real candidates; ordered first on
   engineering grounds, not because measurement required it here.
2. **Not-a-module** (no directory has both `module.json` and `module.pd`).
   Must run before the redistribution check: candidates `96836`, `105123`,
   `114274`, `189681` each ship a root `main.pd` *and* have no module
   directory anywhere. If redistribution were checked first, all four would
   misfile as rack redistributions (main.pd at the archive root, trivially
   "not inside any module directory" when there are no module directories at
   all), inflating that bucket to 7 and starving not-a-module to 10.
3. **Bad JSON** (a module's `module.json` does not parse). Independent of the
   other buckets in the measured data — the one bad-JSON candidate (`118027`,
   "sustain") has no `main.pd` and no ELF binaries — so its position relative
   to wrong-arch/redistribution doesn't move any count. Placed here because a
   candidate whose module identity cannot even be parsed has nothing left to
   gate structurally.
4. **Wrong architecture** (any bundled external fails the ELF ABI check).
   Must run before the redistribution check: `162128` (ORHACK's own archive)
   and `171653` (`8rac`) each ship a root `main.pd` *and* the x86
   `tb_peakcomp~`/`ds_peakcomp~` pair. Measured: both land in the wrong-arch
   bucket, which is only possible if wrong-arch is checked before
   redistribution.
5. **Rack redistribution** (`main.pd` whose containing directory is not itself
   a module directory, nor nested inside one — see below). By elimination,
   whatever survives steps 1-4 with a root-level `main.pd` is a genuine
   redistribution: exactly `96789`, `105149`, `169334`, the trio that ships
   literally `orac/main.pd`.
6. **Duplicate `moduleType` path** and **unmodelled preset sidecar** — the
   two module-level checks (a candidate can pass with some of its modules
   kept and others dropped; see "Module-level vs candidate-level" below).
   Ordered last because both need a module's identity (parsed `module.json`,
   category, key) already resolved, which only exists once a candidate has
   cleared every candidate-level check above. Fire on zero real modules in
   the measured 122-candidate pass set — see "Install layout and category"
   for why duplicate-path in particular is zero by construction, not by luck.

**The `main.pd`-containment test, precisely:** the brief's "at the package
root" / "deeper inside a module directory" wording is a simplification. The
actual test is containment: a `main.pd` rejects only if its directory is
neither equal to, nor a descendant of, any module directory in the archive.
Three real shapes appeared in the survey, and only containment separates them
correctly:

- `orac/main.pd` next to `orac/modules/fx/delay/` (module directories) — the
  `main.pd` directory (`orac`) is not a module directory and is not inside
  one → **reject** (the 3-candidate redistribution bucket).
- `simpledist/main.pd` in the same directory as `simpledist/module.json` —
  the `main.pd` directory *is* the module directory → **warn, pass**
  (candidates `125524`, `125848`, `163108`).
- `monocle/aptone/main.pd` where the module directory is `monocle` — the
  `main.pd` directory (`monocle/aptone`) is a *descendant* of the module
  directory → **warn, pass** (candidates `146075`, `146090`, `154907`,
  `169842`). A naïve "is the main.pd directory exactly a module directory"
  test would wrongly reject these four as redistributions.

**Module-level vs candidate-level:** the four structural checks (archive
safety, not-a-module, bad-JSON, wrong-arch) and the redistribution check are
candidate-level — any hit rejects the whole archive, contributing zero
catalog entries, which is what makes a 5-module pack like `8rac` count once
in the wrong-arch bucket rather than five times. Sidecar and duplicate-path
are module-level: the brief's sidecar text says "rejects the module"
(singular), and a duplicate path is inherently about one specific module's
target, not its whole upload — so a pack can lose one member to either check
while its siblings still catalogue. No surveyed candidate exercised this split
(zero sidecar/duplicate-path rejects in the measured data), so it is
documented as the more precise reading of the spec text rather than something
real data proves.

### Detecting preset sidecars

The rule needs a method, because sidecar files are written by Pure Data code
inside the module, not by anything the preset system declares.

Scan every `.pd` file in a module's own directory subtree for `read`/`write`
Pd message boxes whose argument path contains `presets` — the same scan that
produced the built-in inventory in [platform/state.md](platform/state.md).

**What "resolved" means, precisely.** Every one of the five built-in
patterns is a message whose path starts with the literal `$1/presets/$2/`
(`$1` = dataDir, `$2` = preset name — both framework-injected at runtime by
the same convention across every stateful module, never module-specific),
followed only by further `$N` substitutions (slot id, loop index — also
framework-injected) and fixed literal characters baked into that module's own
`.pd` file (a filename and extension). A message matching that shape is
"resolved": the compiler can synthesize the matching filename once it knows
$1/$2/$3.../slot, *regardless of which literal suffix the module chose* — the
five built-ins are the shapes that proved the mechanism exists, not an
exhaustive whitelist of literal filenames. A message that does not start with
`$1/presets/$2/`, or whose remainder contains anything other than `$N` tokens
and literal filename characters, is unresolved and rejects the module.

This distinction is load-bearing, not cosmetic: `sequencers-bpm`'s four
sequencer members (Arp Seq, Seq, PolyBeats, Punchy) each write suffixes like
`$3-punchy-seqvel.txt` or `$3-sequence-state.txt` that match none of the five
built-in templates literally, yet the pack contributes all 7 of its measured
catalog entries. A whitelist reading of "one of the five modelled patterns"
would reject them and the 200-entry survey count would not reproduce. Verified
against every real `read`/`write`-to-`presets` message in the 122 candidates
that passed the rest of the gate: all resolve under the shape rule, zero are
unmodelled.

A module with no such message is stateless and passes. This is a *textual*
scan, deliberately conservative: dynamic path construction it cannot resolve
rejects rather than warns.

**Pd wraps long box text across physical lines with no inserted separator**,
ending the logical statement on the first line whose *unescaped* `;`
terminates it (`\;` inside box text is a literal semicolon, not the
terminator). `sequencers/overflow/overflow.pd`'s `step-seq-length` read/write
messages are long enough to wrap this way; a naive per-line scan silently
dropped them instead of resolving or rejecting them, which is worse than
either. `scan_pd_text` rejoins wrapped lines before matching.

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

Passing is necessary, not sufficient: it says an archive is structurally safe
to install, never that the module sounds right or fits in the S2's CPU
budget. `rig lint` re-runs this gate over every committed archive, which is
what proves `system/data/catalog/` was generated from the archives actually present
rather than hand-edited. See [validation.md](validation.md).

## Versioning

`revision` is author-authored free text and **never an identity**: across the
145 surveyed uploads it took only 33 distinct values, with `1.0` alone
accounting for 55 of them, and authors re-upload without bumping it. Identity
is `updated_at` plus the detail endpoint's file `id`, verified with
`archive_sha256`. `revision` is carried only to name the stored archive
readably, with the collision refusal described in "The archive store" catching
the case where it lies.

Push installs exactly what `system/data/modules.lock` names, from `system/modules/`, and
never auto-upgrades — nor does it check for updates, since it no longer
reaches the network at all. `rig catalog update` re-fetches what the catalog
already names; `rig upgrade MODULE...` bumps named modules. Both produce a
reviewable repo diff, superseding Prompt.md's auto-install.

An upload that has disappeared from Patchstorage is reported by `catalog
update` and **left in place**: its archive is committed, so the rig still
works, and dropping a module a song may use is not that command's call.

## Install layout and category

Community modules install to
`<card>/media/orhack/user-modules/<category>/<name>/`. `userModuleDir`
(`/tmp/media/orhack/user-modules`) and the built-in `modules/` root are
search-path prefixes, not part of the stored value — a slot's `moduleType` is
resolved against `userModuleDir` first, then `modules/`
([platform/state.md](platform/state.md)) — so the *stored* `moduleType` is
`<category>/<name>` for a community module and the plain relative path (e.g.
`effects/delay/spiraldelay`) for a built-in. Both live in the same namespace,
which is exactly what makes "a community path shadowing a built-in" a real,
checkable collision. Archives carry no category, so the catalog assigns it.

**`<name>` is the catalog key, not the archive's own directory name.** Real
data forced this: 6 of the 135 surveyed community entries re-implement a
built-in under the same folder name in the same category — standalone
re-uploads of `polystep`, `notegen`, `samplement`, `slatra`, `superposition`
and `warble`, each shipping a directory literally named after the built-in it
mirrors. A raw-directory-name install path collides with the built-in every
time for exactly these six. Since the catalog key (`slug(display)@source`) is
already guaranteed unique — no "who wins" rule needed, see "Keys" above —
using it as the trailing path component (`effects/mod/warble@warble`) makes
every community `moduleType` unique by construction, not by a reject check
that would otherwise silently drop 6 real modules. The duplicate-path reject
condition still exists as a safety net (a Patchstorage upload slug literally
equal to `orhack` would still collide), but contributes zero rejects on real
data as a result.

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
