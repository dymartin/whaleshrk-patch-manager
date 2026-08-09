"""Push's one exception type.

Every refusal push can make -- card detection, module reconciliation, an
unrecorded preset, an un-commanded chain rename, a failed transaction -- uses
this, never a bare `ValueError` or a silent downgrade to a warning. `code`
lets a caller (the CLI, a test) branch on which rule
fired without parsing the message.
"""

from __future__ import annotations

from rig.errors import CodedError


class PushError(CodedError):
    pass
