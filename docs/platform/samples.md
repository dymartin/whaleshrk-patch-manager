# Samples are referenced by position, not name

`samplement` stores `samp_source` (folder selector) and `samp_select` (float
0-100). No filename is ever stored.

`samp_source` is decoded by a `sel -1 0 25 26 27` whose **sixth outlet is the
no-match passthrough** — that is the one driving the kits path. The encoding is
therefore not the ordering the `[-1, 27]` range suggests:

| `samp_source` | Folder |
|---|---|
| `-1`, `0` | none — all four gates closed, nothing selected |
| `1`-`24` | `kits/kit-N`, the value used literally as N |
| `25` | `samples/loops` |
| `26` | `samples/synths` |
| `27` | `samples/` root |

Then position within that folder:

```
index = int( (samp_select / 100) × (N − 0.05) )      N = count of *.wav in folder
```

Listing order comes from POSIX `glob()`, which sorts — so ordering is stable
given identical folder contents. But **any change to the file count remaps every
sample in that folder**, including appending a file that sorts last.

To select file `k` of `N`, emit the midpoint of the valid interval for maximum
float tolerance: `samp_select = 100 × (k + 0.5) / (N − 0.05)`.
