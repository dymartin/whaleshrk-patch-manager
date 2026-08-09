"""Slug and key derivation for catalog entries.

Rules verified by measuring the real 145-candidate fixture plus the 67
built-in module.json files -- see docs/catalog.md "Keys" and "Parameter
names".
"""

from __future__ import annotations

import re

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def slug(text: str) -> str:
    """Lowercase, hyphenate. "+" becomes "-plus" before generic slugification.

    Without the "+" rule, "Braids"/"Braids +" and "Plaits"/"Plaits +" collide
    once generic punctuation stripping drops the "+" -- measured against the
    real catalog, see docs/catalog.md "Keys".
    """
    text = text.replace("+", "-plus")
    text = text.lower()
    text = _NON_ALNUM.sub("-", text)
    return text.strip("-")


def module_key(display: str, source: str) -> str:
    """`slug(display)@source` -- unconditional qualification, no "who wins" rule.

    See docs/catalog.md "Keys": unqualified, 34 keys covering 69 of 200
    entries collide; qualified, zero.
    """
    return f"{slug(display)}@{source}"


def param_names(labels: list[str]) -> list[str]:
    """Friendly parameter names in declaration order.

    `slug(label)`, with a 1-based declaration-order index suffix on every
    occurrence of a label that repeats within the module (`amount-1` ...
    `amount-16`). Labels that occur exactly once get no suffix. Page grouping
    is not used -- it does not disambiguate real modules (see
    docs/platform/modules.md).
    """
    slugged = [slug(label) for label in labels]
    counts: dict[str, int] = {}
    for s in slugged:
        counts[s] = counts.get(s, 0) + 1

    seen: dict[str, int] = {}
    names = []
    for s in slugged:
        if counts[s] == 1:
            names.append(s)
            continue
        seen[s] = seen.get(s, 0) + 1
        names.append(f"{s}-{seen[s]}")
    return names
