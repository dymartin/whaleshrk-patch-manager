# Control and observation surfaces

What the device already exposes, plus the one procedure that changes it.
[../validation.md](../validation.md) is what uses the observation surfaces.
Everything up to "Device bootstrap" is stock and installs nothing; that last
section is a deliberate deviation from the shipped image.

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
`systemctl disable ssh.service`. The web terminal is the stock access path, and
it is unauthenticated to anyone on the network. "Device bootstrap" below enables
sshd; until that is run on a given device, the web terminal is all there is.

**The web terminal is a root shell in practice.** Observed 2026-08-08: it runs
as `music` (uid 1000), and `music` has passwordless `sudo` (`sudo -n true`
returns 0). So an unauthenticated port-8080 connection is full root over the
LAN. Treat the Organelle as a device that trusts its LAN completely — this is
the stock posture, not something the tooling introduces.

Root filesystem is `/dev/mmcblk0p2`, ext4, mounted `ro,noatime`;
`/home/music/fw_dir/scripts/remount-rw.sh` is what changes that, and
`mount -o remount,ro /` puts it back. `/tmp`, `/var/log` and `/var/tmp` are
tmpfs. `vcgencmd` and `python3-psutil` are present.

## Storage layout, observed

Observed 2026-08-08 on the band's S2:

| Path | Device | Filesystem | Notes |
|---|---|---|---|
| `/` | `/dev/mmcblk0p2` | ext4 `ro,noatime` | needs remount to write |
| `/sdcard` | `/dev/mmcblk0p3` | ext4 `rw,noatime` | `music:music`, `drwxr-xr-x` |
| `/usbdrive` | — | — | mountpoint exists, nothing mounted |

**The user drive is a separate, already-writable partition.** Card writes
therefore need no remount and no root — `music` owns `/sdcard` and can write it
directly. Only the bootstrap touches the read-only root.

The card is **ext4**, which makes `deploy.sh`'s `chmod 555` on
`data/orhack/presets/Init` effective here — see [card.md](card.md), where that
protection is described as conditional on a POSIX filesystem. The tool still
protects `Init` by rule and never relies on the mode bits.

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

## Device bootstrap

One-time, per device, and **not automated** — `rig` never performs it. It is a
root-level change to a device the operator owns, and burying it in a push
command means it fires on the wrong box. `rig` assumes it was done and refuses
with a clear message when sshd is unreachable.

All of it is root-filesystem state, so **a firmware update can revert it**. That
is why the procedure lives here rather than in someone's memory.

Run it through the stock web terminal (port 8080). That terminal mangles pasted
multi-line input — heredocs in particular arrive truncated — so every command
must be a single line.

### 1. sshd

```sh
sudo /home/music/fw_dir/scripts/remount-rw.sh
mkdir -p /home/music/.ssh && chmod 700 /home/music/.ssh
echo '<laptop public key>' >> /home/music/.ssh/authorized_keys
chmod 600 /home/music/.ssh/authorized_keys
printf 'PasswordAuthentication no\nKbdInteractiveAuthentication no\nPermitRootLogin no\n' | sudo tee /etc/ssh/sshd_config.d/10-whaleshrk.conf
sudo mkdir -p /run/sshd && sudo sshd -t && echo CONFIG_OK
sudo systemctl enable --now ssh
sudo mount -o remount,ro /
```

Load-bearing details, each of which cost a debugging round:

- **`700` on `.ssh` and `600` on `authorized_keys`.** sshd's `StrictModes`
  silently refuses looser permissions, and the failure presents as a rejected
  key.
- **Harden before enabling.** Writing the config first means sshd is never up
  with password authentication live. Organelle images ship well-known default
  credentials, so that window is the whole risk.
- **A drop-in under `sshd_config.d/`, not an edit to `sshd_config`.** Debian 12
  includes that directory; an OS update rewriting the main config leaves the
  drop-in intact.
- **`sudo sshd -t` fails with `Missing privilege separation directory:
  /run/sshd` before sshd has ever run.** That is not a config error —
  `/run/sshd` is created by the unit's `RuntimeDirectory=` at start. `mkdir` it
  first; `/run` is tmpfs so it costs nothing and needs no remount. Do not enable
  without a passing `sshd -t`: the only other way in is the web page.
- **Verify from the laptop before closing the web terminal.** It is the recovery
  path if the key did not take.

Host keys already exist in `/etc/ssh/`; nothing is generated.

### 2. mDNS — optional, and a deliberate deviation

`avahi-daemon` ships **installed but masked** — symlinked to `/dev/null`, which
blocks socket and D-Bus activation too, not merely boot. That is a deliberate
vendor choice. **No documented reason was found.**

The likeliest explanation, and it is a hypothesis rather than a finding, is
realtime audio: avahi wakes on every mDNS multicast packet on the segment, and
on this hardware that jitter can surface as ALSA xruns — the exact condition
[../validation.md](../validation.md) makes a hard fail. Unmasking it therefore
adds a candidate cause of the thing the hardware check measures.

```sh
sudo /home/music/fw_dir/scripts/remount-rw.sh
sudo systemctl unmask avahi-daemon avahi-daemon.socket
sudo systemctl enable --now avahi-daemon
sudo mount -o remount,ro /
```

`unmask` persists on its own (it deletes a file). `enable` is what survives
reboot; `start` alone does not. Revert with `systemctl disable --now
avahi-daemon` followed by `mask`.

**If the hardware check ever reports underruns, disabling avahi is the first
experiment** — one command, decisive.

A DHCP reservation avoids the question entirely: the address stops moving,
nothing extra runs, and the audio thread is untouched. Preferred unless
name-based addressing is actually needed.

### 3. Addressing and exposure

`~/.ssh/config` on each operator's laptop holds the host, user and key. **The
repo stores only the alias** — no address, no credentials in git.

```
Host organelle
    HostName <address or organelle-s2.local>
    User music
    IdentityFile ~/.ssh/organelle
```

mDNS is link-local multicast and **does not cross a router**. A laptop on a
different subnet than the device — easy to end up with under double NAT — will
never resolve `.local` however healthy avahi is.

The operating rule from [../validation.md](../validation.md), "only on a network
you control", is satisfiable at home and is not on a venue's shared wifi, where
the unauthenticated port-8080 root shell is exposed to everyone present. A
band-owned travel router with a DHCP reservation solves addressing and exposure
together. Switching the device's wifi off for a set is the blunt version and
costs nothing — the rig needs no network on stage.
