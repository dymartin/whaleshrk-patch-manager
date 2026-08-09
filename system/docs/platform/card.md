# Installation and card layout

Source: `0RHACK/deploy.sh`, plus `Organelle_OS/fw_dir/scripts/`.

ORHACK is installed by unzipping the `.zop` into `Patches/` and running its
`deploy.sh`. That script is the authoritative description of a correctly
installed card:

```
media/orhack/kits/kit-1 … kit-24        # exactly 24, confirms samp_source encoding
media/orhack/recordings
media/orhack/samples
media/orhack/user-modules/
    clocks
    effects/{comp,delay,drive,filter,mod,reverb}
    instruments/{drum,sampler,synth}
    mod-sources
    routers
    sequencers
    utility/{audio,cv,midi,visual}
data/orhack/presets/                     # data/presets/* copied in
data/orhack/rack.json
```

`media/orhack/user-modules/<category-path>` is where community modules install.
That tree is fixed by `deploy.sh`, which is why a module's Patchstorage category
has to resolve to exactly one of these folders — see
[../catalog.md](../catalog.md).

`deploy.sh` ends with `chmod 555 data/orhack/presets/Init`. **That only takes
effect on a POSIX filesystem.** `mount.sh` mounts the user drive as `vfat`,
`exfat`, `ntfs` or `ext*`, and on the first three the mode bits are meaningless.
So `Init` is read-only *only on an ext-formatted card*.

`install_package.sh` verifies an unzipped package by regenerating sha1sums and
diffing against the package's own `manifest.txt`. ORHACK ships one covering
2,353 files, so a card's ORHACK installation can be integrity-checked offline,
with no network and no device.

**Writes are buffered.** `mount.sh` mounts with `-o async,noatime`. Pulling the
card without ejecting loses whatever is still in the page cache — on either the
device or the host. Eject; do not yank the card.

The shipped `orac.json` reads

```json
{"dataDir": "/tmp/data/orhack", "mediaDir": "/tmp/media",
 "userModuleDir": "/tmp/media/orhack/user-modules"}
```

`MainMenu.cpp` creates the `/tmp/data` and `/tmp/media` symlinks to the active
`/usbdrive` or `/sdcard` user directory when launching a patch, so ORHACK saves
reach card storage directly.
