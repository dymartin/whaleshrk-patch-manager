# Platform: ORHACK / ORAC / Organelle

Device facts. Verified from source and shipped data, expensive to re-derive.
Read the file that covers your task.

| Doc | Covers |
|---|---|
| [state.md](state.md) | Where state lives, preset format, sidecar `.txt` files, dangling `currentPreset` |
| [routing.md](routing.md) | Slot topology, chain inputs, the `s1` router surface, transport clock |
| [midi.md](midi.md) | CC mapping, Program Change indexing, the preset-control CCs, the keyboard |
| [modules.md](modules.md) | `module.json`, parameter traps, why role is unknowable from the patch |
| [samples.md](samples.md) | Positional sample selection |
| [card.md](card.md) | Install layout, `deploy.sh`, buffered writes |
| [runtime.md](runtime.md) | Pd version, launch line, external resolution |
| [surfaces.md](surfaces.md) | Log, preset-loaded event, web API, OSC, per-slot injection points |
| [patchstorage.md](patchstorage.md) | Catalog API behaviour |

## Provenance

Every fact in these files was read out of one of these, at these revisions:

| Source | Pinned at |
|---|---|
| ORHACK 0.52b | Patchstorage id `162128`, file id `167335`, SHA-256 `90b08bc7e58660c315d271f43a4f3bf23f8f87d6a11f76aa43d2b64612d33c3d`. No public repo |
| `TheTechnobear/Orac` | `9d02176a11ea2333e7df6bec0c0f30f677b1fb38` (2020-05-09) |
| `TheTechnobear/mec` | `940e6fcb1ee15e24e4eb5988dda5a6f8984527dc` (2024-02-12) |
| `critterandguitari/Organelle_OS` | `23f5469b9fb0b1036acb3e9f424eacf83a69aa77` (2026-04-27) |
| `pure-data` | 0.53.1 (Debian `0.53.1+ds-2+deb12u1`) |
| glibc `localedata` | 2.36 |

Re-verify these findings against any newer revision before trusting them.

**ORHACK's compiled binaries are byte-identical to upstream ORAC's.**
`KontrolRack.pd_linux`, `libmec-kontrol-api.so`, `libmec-api.so` and
`libcjson.so` all match — 30 of 40 shared files identical, zero mismatches. The
`mec` C++ source is therefore an accurate model of the shipped code, and every
`mec` finding here applies to the device.

Values called "stock defaults" throughout are `module.json` declared defaults,
not what a shipped preset happens to have saved.
