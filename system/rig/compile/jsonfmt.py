"""Serialises `params.json` in ORAC's own on-device format.

Verified byte-for-byte against the pinned ORHACK 0.52b card's shipped
preset (`fixtures/card/Patches/0RHACK/data/presets/Init/params.json`
-- see docs/platform/README.md): a tab per nesting level, a single tab (not
`": "`) between key and value, `",\\n"` between siblings with no trailing
comma, and even an empty dict expands onto its own line rather than
collapsing to `{}`. Matching this is what `Prompt/03-compiler.md` means by
"tab-indented... matches what the device itself writes" -- a real diff
against device output is then formatting-free, and content-hash
verification (push) compares like for like.

Key *order* inside "params" and "midi-mapping.cc" is a compiler decision,
not a reproduction of the device's: the on-device dict order visible in the
fixtures matches no documented rule (not alphabetical, not module.json
declaration order) and there is no source to verify it against (Prompt.md
Global Constraint #1 -- never assume undocumented behaviour). Callers of
`dumps` choose key order themselves; this module only renders it, in
insertion order, at every level.
"""

from __future__ import annotations

import json

Value = None | bool | int | float | str | list | dict


def _format_number(value) -> str:
    if isinstance(value, bool):  # params.json never carries JSON booleans -- see module docstring
        raise TypeError("bool is not a valid params.json value; use 0/1")
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return repr(value)
    raise TypeError(f"unsupported params.json value {value!r}")


def _dump(value: Value, level: int) -> str:
    indent = "\t" * level
    child_indent = "\t" * (level + 1)
    if isinstance(value, dict):
        if not value:
            return "{\n" + indent + "}"
        items = ",\n".join(f'{child_indent}"{k}":\t{_dump(v, level + 1)}' for k, v in value.items())
        return "{\n" + items + "\n" + indent + "}"
    if isinstance(value, list):
        if not value:
            return "[\n" + indent + "]"
        items = ",\n".join(f"{child_indent}{_dump(v, level + 1)}" for v in value)
        return "[\n" + items + "\n" + indent + "]"
    if isinstance(value, str):
        return json.dumps(value)
    return _format_number(value)


def dumps(obj: Value) -> str:
    """Serialise a nested dict/list/str/number structure to on-device JSON text."""
    return _dump(obj, 0) + "\n"
