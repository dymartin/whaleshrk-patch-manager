# whaleshrk patch manager

Infrastructure-as-code for my band whaleshrk.

This platform lets me compile, maintain, and version control my live synth setup as code. The rig is deterministic and full reproducable offline.

I use the ORHACK plugin for the organelle S2 synth. This lets me chain together community instrument & effect modules with a simple user-facing config, with up to 4 parallel chains, 2 sends, and 2 master effects per song.

### Input Types
Each chain can process line input, audio samples, midi note data, or use the device's keyboard. I can also map midi CC control for all parameters. Midi PC messages select a specific song's suite of chains.   

### Synchronisation
The system has bidirectional sync over SSH or USB. The module's source of truth is compiled and pushed to the device remotely, recovering safely from interruptions. Pulls turn manual on-device changes into auto-generated PRs.

### Validation
The automated validation suite covers configuration regressions, module integrity and on-device performance benchmarking.

### Workflow
The only user facing workflow is editing the song files in `songs/`. The underlying code handles compilation, remote connection, bidirectional sync, module maintainance, validation, diff and drift detection.

### Song Schema
Each song is declarative YAML: a MIDI program selects the song, named chains define their input and ordered modules, and module parameters use readable catalog names rather than device IDs.

```yaml
song: Sample
program: 1 # Midi PC Number
sends:
  reverb:
    module: plateverb@orhack
    amount: 20
chains:
  - name: guitar
    input: {guitar: true}
    mix: {input-gain: 100, output-gain: 90}
    modules:
      - warp@orhack:
          drive-a: 45
          drive-b: 45
          midi: {drive-a: 71}
          send: {reverb: 20}
      - spiraldelay@orhack: {dry-wet: 25, tempo-sync: 1}
  - name: synth
    input: {guitar: false}
    midi: {channel: 2}
    modules:
      - rings@orhack:
          structure: 45
          midi: {structure: 74}
          note-thru: true
      - warp@orhack: {drive: 30}
```

## Running the rig

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```sh
uv sync
uv run rig --help
```

Common commands:

```sh
uv run rig lint # Validate songs and module archives

uv run rig push --dry-run # Preview rendered changes
uv run rig push # Deploy the rig to the device

uv run rig pull --dry-run # Preview on-device drift
uv run rig pull # Import on-device diff as config
```

Technical notes are in [`system/docs/`](system/docs/README.md).
