# Open questions

## Missing sequencer defaults

The default contents of these files remain unknown:

- `<slot>-slot-tracker.txt` and `<slot>-seq<n>x.txt` for
  `sequencers/{overdrum,overflow,clips}`
- `<slot>-{len,notes,vel}.txt` for `sequencers/polystep`

Source inspection shows that `overdrum` and `overflow` read the first two
families on load, but the shipped `Init` preset provides no matching complete
template. Capture a freshly placed instance of each module on hardware, save the
preset, and inspect the emitted files. Until then, inventing defaults would make
compiled presets nondeterministic.

## Hardware thresholds

There is not enough measurement history to justify absolute CPU or load-time
limits. Existing per-device baselines can reveal regressions; add absolute
limits only after real measurements establish useful bounds.
