"""The (code, message) shape every refusal in the rig shares.

A refusal carries a stable `code` a caller -- the CLI, a test -- can branch on
without parsing the message, and a human-readable `message`. Subclasses stay
distinct types so a caller still catches exactly the layer it handles;
`CodedError` only supplies the constructor they all agree on.

`ValueError` is the base because every refusal type here is a rejected input
rather than a broken environment, and callers already catch `ValueError` at
boundaries that predate this class.
"""

from __future__ import annotations


class CodedError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)
