"""Shared compile-time error type.

Mirrors `rig.compile.letters.LetterAssignmentError` and
`rig.song.errors.Finding`'s (code, message) shape, so a caller -- `rig
lint`, push -- can report a compile failure the same way as any other
validation finding.
"""

from __future__ import annotations


class CompileError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)
