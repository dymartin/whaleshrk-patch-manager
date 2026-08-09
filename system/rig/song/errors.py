"""Error and finding types shared across song parsing and validation.

Every hard error carries a distinct message rather than a generic "invalid
song" failure. `Finding`
is that unit: a stable `code` a caller can match on, plus the human-readable
`message` `rig lint` prints. Warnings use the same shape so they can be
reported through the same list, then filtered by severity.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Finding:
    code: str
    message: str


class SongParseError(ValueError):
    """The YAML does not match the documented song shape.

    Structural (missing/mis-typed field), not semantic -- catalog lookups,
    capacity limits and range checks are validation's job, not the parser's.
    """
