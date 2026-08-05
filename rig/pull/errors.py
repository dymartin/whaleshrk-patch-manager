"""Pull's own exception type.

Mirrors `rig.push.errors.PushError`'s (code, message) shape -- a card-level
refusal that is not a per-song reverse-map abort (those stay
`rig.pull.reverse.ReverseMapError`/`ReverseMapError`-shaped so `rig.pull.adopt`
can reuse the same codes), used for whole-run refusals like "every recorded
preset is missing" (docs/workflows/pull.md, decision #55).
"""

from __future__ import annotations


class PullError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)
