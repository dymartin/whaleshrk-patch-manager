# External catalog constraints

Implementation, storage formats, commands, and validation rules live in
`system/rig/catalog/`. This file keeps only evidence learned from upstream data.

## Patchstorage identity

Patchstorage revision labels are not reliable identities. In the surveyed ORAC
uploads, authors reused labels heavily and could replace an upload without
changing its revision. The stable observations available from the API are the
upload file id and update timestamp; downloaded bytes need their own digest.

The API has no lookup-by-slug endpoint. Unknown query parameters are silently
ignored, so a client that assumes server-side filtering can accidentally fetch
the entire catalog. See [platform/patchstorage.md](platform/patchstorage.md).

## Real archive shapes

Upstream uploads include single modules, multi-module packs, complete rack
redistributions, malformed JSON, non-ARM binaries, nested helper modules, and
desktop debris. A module is identified by a directory containing both
`module.json` and `module.pd`; ORAC stops descending once it registers such a
directory. A `main.pd` outside every module directory indicates a rack or patch
rather than a loadable module pack.

Observed archives also contain `__MACOSX/`, AppleDouble files, `.DS_Store`, swap
files, Windows DLLs, and `abl_link~.pd_linux`. Organelle OS renames the latter to
`.orig` during patch launch, so bundling it causes a card write and does not
provide the expected external.

## Runtime namespace

Community and built-in modules ultimately share one `moduleType` namespace.
Six surveyed community uploads reused a built-in directory name in the same
category, so an archive's raw folder name is not globally unique.

Patchstorage category is the only upstream role hint. Signal inputs and outputs
do not reliably distinguish instruments, effects, sequencers, or utilities;
the measured built-in tree contains counterexamples in both directions.

## Binary compatibility evidence

The Organelle S2 runtime expects little-endian ARM32 ELF with hard-float EABI.
Surveyed uploads included x86 and ARM soft-float externals. EABI version was
uniformly 5 in the sample, but a dependency listed in `DT_NEEDED` may still be
absent from the device even when the ELF header itself is compatible.

The known device/runtime libraries observed in the pinned image include:

- system: `libc`, `libm`, `libstdc++`, `libgcc_s`, `libatomic`, `libpthread`,
  `libdl`, `libasound`, `libusb-1.0`, and `libcairo`
- ORHACK: `libcjson`, `liboscpack`, `libmec-*`, `libpicodecoder`,
  `libeigenapi`, `libsplite`, `libportaudio`, and `librtmidi`

Static compatibility cannot establish Pd API compatibility, CPU cost, or audio
correctness; those remain runtime properties.
