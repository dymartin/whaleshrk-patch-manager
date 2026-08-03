# The Pd runtime

Source: `Organelle_OS/platforms/organelle_cm/README.md` (the OS 5.1 build
recipe), `MainMenu.cpp`, and the image's `.pdsettings`.

The image is built from `2025-05-13-raspios-bookworm-armhf-lite` with
`apt-get install puredata`, so Pd is **Debian bookworm's `puredata`, upstream
0.53.1** (`0.53.1+ds-2+deb12u1`), at `/usr/bin/pd`. Derived from the recipe, not
observed: confirm with one `pd -version` at first device contact. Nothing in the
recipe pulls `bookworm-backports`, which carries 0.55.2.

Patch launch, from `MainMenu.cpp`:

```
cd /tmp/patch ; /usr/bin/pd -rt {-nogui -audiobuf 6 | -audiobuf 10} \
    -path $USER_DIR/PdExtraLibs <mother.pd> main.pd
```

`-audiobuf 10` applies only when X is running; headless is 6. Shipped
`.pdsettings` adds 44100 Hz, 64-sample blocks, ALSA MIDI, and one search path,
`/home/music/Pd/externals`.

`MainMenu.cpp` also appends the contents of a `pd-opts.txt` in the patch
directory to that command line. Anything using it changes the measured runtime,
so it belongs to experiments, not to a validated subject.

**Every patch launch rewrites the card.** Organelle_OS is built with
`FIX_ABL_LINK` on both CM3 and CM4, which runs
`find <patch dir> -name 'abl_link~.pd_linux' -exec mv {} {}.orig` before
starting Pd. A module bundling `abl_link~` is disabled in place, and the rename
is a card write on every launch. ORHACK ships its copy already renamed.

## External resolution order

Verified in Pd 0.53.1 `s_loader.c` and `g_canvas.c`. `sys_load_lib` walks the
search path one directory at a time through `canvas_path_iterate`, which stops
only when a loader reports success. A found-but-unloadable binary returns
failure and iteration continues. Order is: paths declared by the canvas and its
owners (for ORHACK, `/tmp/patch/externals` then `/tmp/patch/subpatches`), then
the canvas's own directory, then the global search path.

That resolves the `tb_peakcomp~` case. ORHACK's copy lives beside the module
that uses it, `modules/effects/comp/bus-comp/tb_peakcomp~.pd_linux`, and is
`EM_386`. The rootfs copy at `/home/music/Pd/externals/tb_peakcomp~.pd_linux` is
ARM hard-float. The x86 copy is reached first, fails `dlopen`, and the ARM copy
loads from the global path.

## Target profile

The Organelle S2 CPU is 64-bit capable, but current OS 5.1 build instructions
use Raspberry Pi OS Bookworm `armhf` and one CM3/CM4 image. The catalog remains
ARM32. Every new OS image must re-run target-profile discovery before its
hardware profile is accepted.

Pd API compatibility, CPU cost and DSP behaviour are not established by static
acceptance. [../validation.md](../validation.md) states what is and is not
checked.
