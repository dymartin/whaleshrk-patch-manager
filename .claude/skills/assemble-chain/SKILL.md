---
name: assemble-chain
description: Build or revise a song's ORHACK chains from fuzzy tone, vibe, mood, role, or routing descriptions. Use when the musician asks for a sound, chain, patch, or song rig without naming every module.
argument-hint: "<song slug or name> <sound description>"
---

# Assemble chain

Turn the musician's description into friendly `songs/<slug>.yaml`. Write the
song directly, run lint, and show the resulting diff. Never touch the card,
push, commit, or add modules.

## Read

Read `docs/schema.md`, every `.rig/catalog/*.json`, `.rig/kits.yaml` when it
exists, and the target song when it exists. Read other songs only to choose an
unused `program` or to reuse an established local pattern.

## Interpret

Accept free-form tone, vibe, mood, role, input, and routing language. Rank
catalog entries using only their `display`, `key`, `tags`, `category`,
`category_override`, `moduleType`, and parameter names/labels. Semantic matches
are allowed; unsupported capabilities are not. Prefer an exact tag or name,
then category/module path, then a conservative semantic match. Prefer modules
already used by another song when two candidates fit equally.

Derive role from catalog metadata, never signal I/O:

- `instruments/` and `sequencers/` belong in chain slots.
- `effects/` belong after a sound source, in a send, or in master.
- `mod-sources/` belong only in `mod-sources`.
- `utility/` belongs only where its display, tags, and parameters support the
  requested job.

If no catalog entry supports a required capability, stop and name the missing
capability. Do not browse Patchstorage or substitute an imagined module.

## Assemble

Use catalog defaults unless the description clearly asks for a parameter
change. Use only friendly keys and parameter slugs from the catalog. Never emit
slot letters, module ids, raw encoded CC keys, `moduleType`, or `kit-N`.

For a new song, use the requested name, a portable lowercase filename slug,
the lowest unused program in `0..127`, and short chain names based on musical
role. Default `input: {guitar: false}` unless guitar/audio input was requested.
For an existing song, preserve everything the request does not change,
including comments and formatting.

Pre-check these hard limits before writing:

- at most 4 chains;
- at most 4 modules in a chain, no more than two 4-module chains;
- at most 2 sends, 3 master effects, and 3 mod sources;
- sends contain effects; master contains effects or clearly supported utility;
- aux slots receive no audio, so never place an instrument in sends, master, or
  mod-sources.

Keep chains in series. Use a send when one effect must be shared across chains;
do not duplicate it unless the description requires independent processing.

## Verify

Write `songs/<slug>.yaml`, then run:

```powershell
uv run rig lint <slug>
git diff -- songs/<slug>.yaml
```

Lint failure means the result is not done: fix the YAML and rerun it. If the
request cannot fit the capacities, leave the file unchanged and explain the
smallest constraint that must change.

Use these acceptance cases when changing this skill:

1. `dark ambient guitar with a shared long reverb` produces a guitar-input
   chain and one effect send, not an instrument in an aux slot.
2. `two contrasting synth voices, both through the same delay` produces two
   instrument chains and one shared send, within all caps.
3. `four independent four-module chains` is rejected before writing because
   only two chains can hold four modules.
