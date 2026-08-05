"""Preset-sidecar detection for a single module.

Sidecar files are written by Pure Data code inside a module; the preset
system knows nothing about them (docs/platform/state.md). A module that
writes one outside the compiler's template mechanism produces a preset the
compiler cannot regenerate deterministically, so ingest must detect and
reject it -- see docs/catalog.md "Detecting preset sidecars".

Detection method, verified against the five known built-in stateful modules
(mod-sources/morpher, sequencers/{overflow,overdrum,polystep,clips}) and
against every real "read"/"write presets" message in the 122 candidates that
pass the rest of the gate (zero of them are unresolved -- see
docs/catalog.md "Reject ordering" for the measurement):

Every built-in stateful pattern is a Pd message box whose text is
`read <path>` or `write <path>`, where `<path>` starts with the literal
`$1/presets/$2/` (`$1` = dataDir, `$2` = preset name -- both framework-
injected at runtime by the same convention across every stateful module,
never module-specific) followed only by further `$N` substitutions (slot id,
loop index, etc., also framework-injected) and fixed literal characters
(hyphens, digits, a filename and extension baked into that module's own .pd
file). That whole shape is "resolved": the compiler can synthesize a matching
filename once it knows $1/$2/$3.../slot, regardless of which specific
literal suffix the module chose.

A message that does not start with `$1/presets/$2/`, or whose remainder
contains anything other than `$N` tokens and literal filename characters, is
"unresolved" and rejects the module.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_MSG_RE = re.compile(r"#X msg -?\d+ -?\d+ (.*);\s*$")
_RESOLVED_RE = re.compile(
    r"^\\\$1/presets/\\\$2/(?:\\\$\d+|[A-Za-z0-9_\-.])+$"
)


@dataclass(frozen=True)
class SidecarScanResult:
    resolved: list[str]
    unresolved: list[str]

    @property
    def is_modelled(self) -> bool:
        return not self.unresolved


def _is_statement_end(line: str) -> bool:
    """True if `line` ends a Pd declaration with an unescaped ';'.

    Pd escapes a semicolon inside box text as '\\;'; that must not be read
    as the statement terminator (see `test_wrapped_message_with_escaped_
    semicolon_is_not_mistaken_for_the_terminator`).
    """
    stripped = line.rstrip()
    if not stripped.endswith(";"):
        return False
    backslashes = 0
    i = len(stripped) - 2
    while i >= 0 and stripped[i] == "\\":
        backslashes += 1
        i -= 1
    return backslashes % 2 == 0


def _logical_lines(text: str) -> list[str]:
    """Rejoin declarations Pd wrapped across multiple physical lines.

    Every Pd declaration (`#X msg ...;`, `#X obj ...;`, ...) normally
    occupies one physical line, but Pd's own file writer wraps long box text
    at a column width with no inserted separator, so the wrapped remainder
    is the *same* declaration continuing on the next line. Verified against
    sequencers/overflow/overflow.pd's step-seq-length read/write messages,
    whose long filename wraps across two physical lines -- a real case a
    naive per-line scan silently drops instead of resolving, which is worse
    than flagging it unresolved (Prompt.md Global Constraint #3).
    """
    logical: list[str] = []
    buffer = ""
    for raw in text.splitlines():
        buffer += raw
        if not buffer or _is_statement_end(buffer):
            logical.append(buffer)
            buffer = ""
    if buffer:
        logical.append(buffer)
    return logical


def scan_pd_text(text: str) -> SidecarScanResult:
    """Scan one .pd file's text for read/write-to-presets messages."""
    resolved: list[str] = []
    unresolved: list[str] = []
    for line in _logical_lines(text):
        m = _MSG_RE.search(line)
        if not m:
            continue
        content = m.group(1).strip()
        parts = content.split(" ", 1)
        if len(parts) < 2:
            continue
        verb, rest = parts
        if verb not in ("read", "write"):
            continue
        path_arg = re.split(r"[ ,]", rest, maxsplit=1)[0]
        if "presets" not in path_arg.lower():
            continue
        if _RESOLVED_RE.match(path_arg):
            resolved.append(path_arg)
        else:
            unresolved.append(path_arg)
    return SidecarScanResult(resolved=resolved, unresolved=unresolved)


def scan_module_sidecars(pd_files: dict[str, str]) -> SidecarScanResult:
    """Scan every .pd file belonging to one module (its directory subtree).

    `pd_files` maps a relative path (informational, for error messages) to
    file text. A read and a write of the same path (the common case) produce
    the same pattern twice; deduplicated here, order preserved, since it is
    one sidecar template either way.
    """
    resolved: list[str] = []
    unresolved: list[str] = []
    for text in pd_files.values():
        result = scan_pd_text(text)
        resolved.extend(result.resolved)
        unresolved.extend(result.unresolved)
    return SidecarScanResult(
        resolved=list(dict.fromkeys(resolved)), unresolved=list(dict.fromkeys(unresolved))
    )
