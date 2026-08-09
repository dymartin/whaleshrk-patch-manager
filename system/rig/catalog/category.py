"""Community module category mapping -- docs/catalog.md "Category mapping".

Archives carry no category; ingest assigns one from the upload's Patchstorage
category. Multi-category uploads resolve by fixed precedence (decision #32),
most specific first, so the mapping stays deterministic and re-runnable
across ingests.
"""

from __future__ import annotations

CATEGORY_FOLDER = {
    "synthesizer": "instruments/synth",
    "sampler": "instruments/sampler",
    "sequencer": "sequencers",
    "effect": "effects/mod",
    "utility": "utility/audio",
    "sound": "utility/audio",
    "other": "utility/audio",
    "composition": "utility/audio",
}

# Most specific first. A category not in this list is unknown and never
# silently ignored -- see resolve_category.
PRECEDENCE = [
    "sampler",
    "sequencer",
    "synthesizer",
    "effect",
    "utility",
    "sound",
    "other",
    "composition",
]


class UnrecognizedCategoryError(ValueError):
    """None of an upload's Patchstorage categories map to an ORHACK folder."""


def resolve_category(category_slugs: list[str]) -> str:
    """Return the ORHACK install folder for an upload's Patchstorage categories.

    First category present in PRECEDENCE order wins, regardless of the
    upload's own category ordering.
    """
    present = {c.lower() for c in category_slugs}
    for candidate in PRECEDENCE:
        if candidate in present:
            return CATEGORY_FOLDER[candidate]
    raise UnrecognizedCategoryError(
        f"no recognized Patchstorage category in {category_slugs!r}"
    )
