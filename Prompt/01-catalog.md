# Phase 1 — Catalog

## Goal

Ingest ORHACK built-ins and Patchstorage community modules into `.rig/catalog/`
and `.rig/modules.lock`.

## Read first

`../docs/catalog.md` (owns this phase), `../docs/platform/patchstorage.md`,
`../docs/platform/modules.md`, `../docs/platform/card.md`,
`../docs/platform/runtime.md`, `../docs/platform/state.md` (sidecar inventory),
`../docs/decisions.md` #11, #12, #13, #20, #23, #27, #32, #42, #60.

## Slug lookup

`rig catalog add SLUG` fetches one named upload. Patchstorage has no
lookup-by-slug filter, so finding it means walking the union of platform `3371`
and tag `1483`, deduped (145 candidates when surveyed), stopping once every
wanted slug is found. That walk is a lookup mechanism, not an ingest scope —
only the named uploads are gated and stored. See `../docs/decisions.md` #71.

**Assert result counts.** Unknown query parameters are silently ignored by the
API — `authors=<id>` returns all 17,000+ patches while `author=<id>` filters
correctly. A filter that silently does nothing must be caught by a count
assertion, not trusted.

List endpoint omits `files`; only `/patches/<id>` carries download URLs.

## Validation gate

Reject, do not catalogue.

The conditions below are mutually exclusive buckets, and the order the gate
applies them in is load-bearing — see `../docs/catalog.md` "Reject ordering"
for the derived sequence, the evidence for it, and which real candidates only
land in their measured bucket because of it.

**Hard reject:**

| Condition | Note |
|---|---|
| Archive lacks `<dir>/module.json` **and** `<dir>/module.pd` | Catches mis-tagged plain Organelle patches — 14 of the 145 surveyed |
| `main.pd` whose directory is neither a module directory nor nested inside one | Rack redistribution. All three measured ship `orac/main.pd`; neither module pack ships one. A `main.pd` in, or nested inside, a module's own directory: **warn**, do not reject — see `../docs/catalog.md` "Reject ordering" for the precise containment test and why "package root" alone under-specifies it |
| `module.json` does not parse | Real modules ship invalid JSON — at least one has an unquoted property name |
| Any bundled external fails the ABI check | Table below |
| Archive traversal, absolute paths, symlinks, case-colliding entries, expanded-size or file-count over configured limits | |
| Duplicate runtime `moduleType` path, including a community path shadowing a built-in | Runtime loads by path, not by catalog key |
| Reads/writes an unmodelled preset sidecar | Detection below |

**ELF ABI check** — read the header directly with `struct`:

| Criterion | Status |
|---|---|
| `EM_ARM` (`e_machine == 0x28`) | Enforced. The only criterion observed rejecting real data — every wrong-arch hit was x86 |
| ELF32 | Enforced, never observed firing |
| hard-float (`e_flags & 0x400`) | Enforced, never observed firing |
| little-endian (`e_ident[EI_DATA] == ELFDATA2LSB`) | Enforced |
| EABI5 | **Not gated.** Log it; uniformly version 5 across the sample |

**Warn, do not reject:** a `DT_NEEDED` entry outside the known-good set and not
bundled in the archive. The set is *derived*, not hand-written — pinned rootfs
libraries plus ORHACK's own `externals/`; the two-column table in
`../docs/catalog.md` is authoritative. A dependency satisfied inside the
candidate archive is fine.

**Strip on install:** `__MACOSX/`, `._*` AppleDouble files, `.DS_Store`, editor
swap files, `.dll`. Also strip any bundled `abl_link~.pd_linux` — Organelle_OS
renames it to `.orig` on **every** patch launch, so shipping one means a card
write per launch and an external that silently never loads. Treat a module that
needs it as unsupported.

### Detecting preset sidecars

Sidecar files are written by Pure Data code inside the module; the preset system
knows nothing about them.

Scan every `.pd` file in the archive for `read`/`write` messages whose argument
path contains `presets`. Resolve `$0`/`$1`-style substitutions **textually**. A
pattern that cannot be resolved counts as unmodelled.

Any pattern that does not resolve rejects the module — see
`../docs/catalog.md` "Detecting preset sidecars" for exactly what "resolved"
means: a message shaped like `$1/presets/$2/` plus only further `$N` tokens
and literal filename characters, which is the shape of all five modelled
built-ins (`mod-sources/morpher` and `sequencers/{overflow, overdrum,
polystep, clips}` — full pattern inventory in `../docs/platform/state.md`),
not a whitelist of their literal filenames. A real community module pack
(`sequencers-bpm`) proves the distinction matters: its members use the same
shape with novel suffixes and still resolve. A module with no such message is
stateless and passes.

Deliberately conservative: dynamic path construction that cannot be resolved
rejects rather than warns. The compiler can only produce a deterministic sidecar
set for patterns it has templates for.

## Keys

```
slug(module.json "display") @ source
```

`@orhack` for built-ins, the Patchstorage upload slug for community modules.
Qualification is **unconditional** — no "who wins" rule, and adding a colliding
module never renames an existing key. Unqualified, 34 keys covering 69 of 200
entries collide; qualified, zero.

Two slug rules, both found by measurement:

- `+` maps to `-plus`. Otherwise "Braids"/"Braids +" and "Plaits"/"Plaits +"
  collide.
- Skip `module.json` files nested inside another module's directory. Otherwise
  `effects/delay/spiraldelay/module` collides with its own parent. This also
  reproduces runtime behaviour: `loadModuleDir` recursion stops at the first
  `module.pd`, so ORHACK registers **66 built-ins including `-empty-`, 65
  selectable**, from 67 `module.json` files.

## Parameter derivation

`module.json` parameter tuples are `["<type>", "<id>", "<label>", min, max,
default]` for every type except `bool`, which omits min/max (implicit 0/1):
`["bool", "<id>", "<label>", default]`. Types: `float int bool pct freq time
pitch pan`. See `../docs/catalog.md` "Parameter names" for the measured
exceptions (a spurious extra element on one real `bool`, and a module with no
`parameters` key at all).

Parameter name = `slug(label)`, with an index suffix following **declaration
order** where a module repeats a label (`amount-1` … `amount-16`).

Record in the catalog entry, per parameter: the friendly slug, the **real
parameter id**, min, max, default, type. The slug→id pair is what makes Phase 8's
`rig upgrade` refusal possible, so it cannot be omitted.

Labels are not unique: 16 of 66 built-ins repeat them, `fission` shares labels
across 83 of 97 parameters, `morpher` has "Amount" sixteen times. Page grouping
does **not** disambiguate — `morpher` leaves 48 of 64 unpaged, `overflow` all 28,
and `progarp` collides even when paged. Declaration order is the only recovery.

Defaults are pinned per module version. An upstream default change must surface
as a reviewable catalog diff, never as silent drift (#13).

## Category mapping

Community modules install to `<card>/media/orhack/user-modules/<category>/<name>/`.
`userModuleDir` is a search-path prefix, not part of the stored value, so the
**stored `moduleType` is `<category>/<name>`**, in the same namespace a
built-in's own relative path lives in — see `../docs/catalog.md` "Install
layout and category" for why `<name>` must be the catalog key, not the
archive's own directory name (6 measured community modules reuse a built-in's
directory name verbatim, which collides on a raw-dirname install path every
time). Archives carry no category, so ingest assigns it from the upload's
Patchstorage category:

| Patchstorage | ORHACK folder |
|---|---|
| synthesizer | `instruments/synth` |
| sampler | `instruments/sampler` |
| sequencer | `sequencers` |
| effect | `effects/mod` |
| utility, sound, other, composition | `utility/audio` |

Uploads carry multiple categories — 28 of 100 sampled do, 27 of those map to
conflicting folders. Fixed precedence, most specific first:

```
sampler > sequencer > synthesizer > effect > utility/sound/other/composition
```

First category present wins. Deterministic and re-runnable.

Category is a property of the *upload*, so every module in a pack inherits one.
Every entry carries a `category_override` so a pack member can be moved alone.
Role cannot be derived from the patch — `(2 signal in, 2 signal out)` occurs
across effects, utility, instruments, sequencers and mod-sources alike.

Because the path *is* the `moduleType`, changing a category changes module
identity. Treat it like a version bump.

## Tags

Populate `tags` at ingest from Patchstorage tags and categories. Unused by the
CLI. Required so Phase 11 needs no re-ingest (#24).

## Versioning

`revision` is author-authored free text and **never an identity** — real values
include `0.00200.0220.220` and `87798176543`, and across the 145 surveyed
uploads it took only 33 distinct values with `1.0` alone covering 55. Identity
is `updated_at` plus the detail endpoint's file `id`, verified with
`archive_sha256`. Carry `revision` anyway: it names the stored archive
readably, and a same-revision-different-bytes archive is the silent-re-upload
case worth refusing (#72).

`.rig/modules.lock` pins versions and content hashes. Push installs exactly what
the lock names, from `modules/`, and never auto-upgrades (#20, supersedes
Prompt.md).

## Outputs

- `.rig/catalog/` — one generated entry per module. Committed.
- `.rig/modules.lock` — pinned versions plus content hashes. Committed.
- `modules/<slug>@v<revision>.zip` — the upload itself, byte-identical.
  Committed (`../docs/decisions.md` #72). Refuse a same-revision archive whose
  bytes differ; warn past 5MB.
- Each build records generator and schema version.

`rig catalog add` and `rig upgrade` are the only network paths. Ordinary
builds, pushes and lint runs read the committed files.

## The one-time ecosystem survey

The gate was designed against the whole ORAC ecosystem, surveyed once: 145
candidates, 122 passing (14 not-a-module, 5 wrong-arch, 3 rack-redistribution,
1 bad-JSON), which would have yielded 200 entries alongside the 65 selectable
built-ins. Those numbers are recorded in `../docs/catalog.md` as evidence for
the gate's shape — in particular why its check order is load-bearing — not as
counts anything reproduces now. No test asserts them; the corpus is gone.

## Verification

Per gate branch, one synthetic archive that fires exactly that branch and no
other. Plus: a clean archive ingests; two uploads shipping the same display
name produce distinct qualified keys; no community entry shadows a built-in
runtime path; both slug rules have a test.

Never assert counts against the live API — they change as people upload.

## Done when

Every hard-reject condition has its own archive fixture, and the ELF check
rejects the x86 `tb_peakcomp~`/`ds_peakcomp~` pair that propagates into
`bus-comp`, `strip`, `percussions+`, `8rac` — and into ORHACK itself.
