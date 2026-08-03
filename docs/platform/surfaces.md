# Control and observation surfaces

What the device already exposes. Nothing here requires installing anything.
[../validation.md](../validation.md) is what uses it.

## Everything Pd prints reaches journald

`start-mother.sh` runs `mother 2>&1 | systemd-cat --identifier=Organelle`, and
Pd is launched by mother, inheriting its stdout. So every Pd `post()` and error
is in the journal under tag `Organelle`. Journald storage is volatile and
`/var/log` is tmpfs — the log survives until reboot, not past it.

## A preset finishing loading is an observable event

`Rack::loadFilePreset` swaps every changed module, applies every parameter, and
*then* calls the model's `loadPreset`, which reaches `PdCallback::loadPreset`.
That posts

```
preset loaded  : <name>
```

and sends the name to the Pd receive symbols `rackLoadPreset` and
`rackCurrentPreset`. It fires for every load path — Program Change, next/prev
preset, remote OSC — and always after the work is done. It is the control
plane's completion signal; it says nothing about a module's internal warm-up.

**DSP stops during each module load.** `KontrolRack_loadmodule` sends `pd dsp 0`
before clearing a slot and `pd dsp 1` after building it. A preset switch is
therefore silent for roughly the number of changed slots times the per-module
load cost.

## Web app, port 8080

OS 5.1 runs a Flask app on `0.0.0.0:8080` with **no authentication**:

| Endpoint | Use |
|---|---|
| `/log_stream` | websocket streaming `journalctl -f -o cat -t Organelle` |
| `/terminal` | websocket to a live bash PTY |
| `/upload` `/download` `/get_file` `/save` | file access |

The UI filters `(snd_pcm_recover) underrun occurred` lines out of the log view;
the raw stream still carries them, which makes xruns observable for free.

**SSH is disabled** in shipped S2 images — the build recipe ends with
`systemctl disable ssh.service`. The web terminal is the access path, and it is
unauthenticated to anyone on the network. Treat the Organelle as a device that
trusts its LAN completely.

Root filesystem is mounted read-only; `fw_dir/scripts/remount-rw.sh` is what
changes that. `/tmp`, `/var/log` and `/var/tmp` are tmpfs. `vcgencmd` and
`python3-psutil` are present.

## mec OSC control plane

`main.pd` instantiates `KontrolRack organelle 6000 6001`: the rack listens on
UDP **6001** and broadcasts to **6000**.

Inbound works from any host — `/Kontrol/loadPreset`, `/Kontrol/changed` and
friends are accepted from anywhere, so a preset can be loaded *by name*, which
MIDI cannot do. Outbound does not: `KontrolRack_connect` hardcodes host
`127.0.0.1`, and a broadcaster only sends to a client that has pinged it. So
commands can come from the network, but events cannot leave it. Off-device
observation goes through the journal instead.

## Per-slot injection points

`KontrolRack_loadmodule` wires each slot with `r~ inL-<slot>` / `r~ inR-<slot>`
and `s~ outL-<slot>` / `s~ outR-<slot>`, and `fullmodule.pd` routes notes and
controls through `notesIn-<slot>` / `ctrlIn-<slot>`. A slot's audio, notes and
controls are all addressable by name, without any MIDI or audio device.
