# Overview

`rig` treats whaleshrk's Organelle S2 / ORHACK live setup as version-controlled
configuration. Musicians describe songs in YAML; the application validates and
compiles them, synchronises presets, modules, and media to the device, and turns
supported device-side parameter changes back into reviewable repository changes.

The repository is intended to reproduce a show rig offline. It owns declared
song state and playback media while leaving device recordings alone. Hardware
and upstream behavior that makes those rules necessary is recorded under
[platform/](platform/README.md); current commands and data shapes live in the
code and `rig --help`.
