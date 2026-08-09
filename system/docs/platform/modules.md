# Module definitions

Each module directory holds `module.pd` and `module.json`:

```json
{
  "display": "Analog Mono",
  "parameters": [ ["<type>", "<id>", "<label>", <min>, <max>, <default>], ... ],
  "pages":      [ ["<pageId>", "<pageLabel>", ["<paramId>", ...]], ... ]
}
```

Parameter types: `float` `int` `bool` `pct` `freq` `time` `pitch` `pan`.

Two traps:

- **Display labels are not unique within a module.** 16 of 66 built-ins have
  duplicates — `fission` has 83 of 97 parameters sharing labels, `morpher` has
  "Amount" sixteen times. The duplicates are structured per-voice repeats, and
  parameter ids carry the index (`m_amt_p1`…`m_amt_p16`).
- **Page grouping does not disambiguate.** Many parameters are unpaged entirely
  (`morpher` 48 of 64, `overflow` all 28), and `progarp` collides even when
  paged.

Real-world `module.json` is not guaranteed valid JSON — at least one published
module has an unquoted property name.

**A module's role cannot be derived from its signal I/O.** Measured across the
built-in tree, `(2 signal in, 2 signal out)` occurs in effects (25), utility
(11), instruments (7), sequencers (7) and mod-sources (3) alike, because slots
are wrapped and most modules pass audio through regardless of function. Only
three modules deviate. Any instrument-vs-effect classification must come from
metadata, not from inspecting the patch.

**The category folder is functionally inert.** `loadModuleDir` recurses
arbitrarily deep and registers any directory containing `module.pd`, named by
its relative path. Nothing interprets the category — it is an identifier and a
device-browser grouping. A wrong category costs browsing convenience, not
correctness. But since the path *is* the `moduleType`, changing a module's
category changes its identity and should be treated like a version bump.

**Recursion stops at the first `module.pd`.** A nested module directory is
invisible to the runtime. ORHACK's tree holds 67 `module.json` files; one,
`effects/delay/spiraldelay/module`, sits inside a registered module and is never
loaded. So the device registers **66 built-ins including `-empty-`, 65
selectable**. The catalog's nested-directory skip rule reproduces runtime
behaviour rather than merely avoiding a key collision.
