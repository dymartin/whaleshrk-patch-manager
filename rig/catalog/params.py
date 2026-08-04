"""Parameter derivation from a module.json "parameters" array.

Tuple shape verified against all 67 built-in module.json files and every
community module.json in the 122-candidate passing set (see
docs/catalog.md "Parameter derivation"):

- Every type except `bool` uses a 6-element tuple:
  `[type, id, label, min, max, default]`.
- `bool` uses a 4-element tuple, `[type, id, label, default]` -- min/max are
  never carried; they are implicitly 0/1. Measured across all 67 built-ins
  with no exception.
- One real community module (candidate 163108, "vj-fm") ships a `bool`
  parameter with a spurious extra numeric element before the default
  (`["bool", "l1m2_is_velocity_sensitive", "Velocity?", 0, 0]`). The default
  is always the tuple's last element regardless of length, which reads
  correctly for both the 4- and 5-element cases.
"""

from __future__ import annotations

from dataclasses import dataclass

from .slugs import param_names

KNOWN_TYPES = {"float", "int", "bool", "pct", "freq", "time", "pitch", "pan"}


class ParamParseError(ValueError):
    """A parameter tuple could not be interpreted -- never silently guessed."""


@dataclass(frozen=True)
class ParamSpec:
    name: str  # friendly slug, e.g. "amount-3"
    id: str  # real parameter id, e.g. "m_amt_p3" -- what rig upgrade pins against
    label: str
    type: str
    min: float
    max: float
    default: float


def parse_parameters(module_label: str, raw_parameters: list | None) -> list[ParamSpec]:
    """Parse a module.json "parameters" array in declaration order.

    `raw_parameters` may be absent (module.json with no "parameters" key at
    all -- measured on candidate 103456, "seq3": a module with zero
    user-adjustable parameters is real, not an error).
    """
    if not raw_parameters:
        return []

    ids: list[str] = []
    labels: list[str] = []
    types: list[str] = []
    mins: list[float] = []
    maxs: list[float] = []
    defaults: list[float] = []

    for tup in raw_parameters:
        if not isinstance(tup, list) or len(tup) < 4:
            raise ParamParseError(f"{module_label}: malformed parameter tuple {tup!r}")
        ptype, pid, label = tup[0], tup[1], tup[2]
        if ptype not in KNOWN_TYPES:
            raise ParamParseError(
                f"{module_label}: unknown parameter type {ptype!r} for id {pid!r}"
            )
        if ptype == "bool":
            pmin, pmax = 0, 1
            pdefault = tup[-1]
        else:
            if len(tup) != 6:
                raise ParamParseError(
                    f"{module_label}: {ptype} parameter {pid!r} has {len(tup)} "
                    "elements, expected [type, id, label, min, max, default]"
                )
            pmin, pmax, pdefault = tup[3], tup[4], tup[5]
        ids.append(pid)
        labels.append(label)
        types.append(ptype)
        mins.append(pmin)
        maxs.append(pmax)
        defaults.append(pdefault)

    names = param_names(labels)
    return [
        ParamSpec(name=n, id=i, label=lbl, type=t, min=mn, max=mx, default=d)
        for n, i, lbl, t, mn, mx, d in zip(names, ids, labels, types, mins, maxs, defaults)
    ]
