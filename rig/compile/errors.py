"""Shared compile-time error type.

Mirrors `rig.song.letters.LetterAssignmentError` and
`rig.song.errors.Finding`'s (code, message) shape, so a caller -- `rig
lint`, push -- can report a compile failure the same way as any other
validation finding.
"""

from __future__ import annotations

from rig.errors import CodedError


class CompileError(CodedError):
    pass
