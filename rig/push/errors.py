"""Push's one exception type.

Every refusal push can make -- card detection, module reconciliation, an
unrecorded preset, an un-commanded chain rename, a failed transaction -- uses
this, never a bare `ValueError` or a silent downgrade to a warning (Prompt.md
Global Constraint #3, and Task 5's Ruling #3: "no refusal may be downgraded
to a warning"). `code` lets a caller (the CLI, a test) branch on which rule
fired without parsing the message.
"""

from __future__ import annotations


class PushError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)
