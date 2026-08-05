"""Error and finding types shared across song parsing and validation.

`docs/schema.md` and `Prompt/02-schema.md` require every hard error to carry
its own distinct message -- never a generic "invalid song" failure. `Finding`
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


class SongValidationError(ValueError):
    """Raised by callers that want validation failures to abort immediately.

    Carries every `Finding` collected, not just the first, so a caller that
    catches this can still report everything wrong with the song.
    """

    def __init__(self, findings: list[Finding]):
        self.findings = findings
        super().__init__("; ".join(f"{f.code}: {f.message}" for f in findings))
