"""The canonical, versioned validation report -- shared by static (Task 9)
and hardware (Task 10) tiers.

docs/validation.md fixes the field list: verdict, tier, subject, run id,
per-song checks, metrics, failures, start/end times. `Report` holds exactly
those, plus `confidence` (docs/validation.md "Confidence levels") and
`scope_note` -- a disclaimer carried inside the report data itself, not just
CLI stdout, so a report saved, forwarded or read later still cannot be
misread as proof of anything the tier producing it did not check (Task 9
Ruling #2; decisions #61/#63).

Nothing here is tier-specific. `metrics` is namespaced -- `{"catalog": {...},
"songs": {...}}` -- so a song id can never collide with a catalog-wide key.
Task 10 adds its hardware measurements under `metrics["songs"][<song id>]` and
fills the device-only `Subject` members this tier leaves `None`; it needs no
new field and no new shape.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal, Optional

from rig.atomicio import write_text_atomic

REPORT_SCHEMA_VERSION = 1

# docs/validation.md "Confidence levels".
CONFIDENCE_STATIC_ONLY = "static-only"
CONFIDENCE_HARDWARE_OBSERVED = "hardware-observed"

VERDICT_PASS = "pass"
VERDICT_FAIL = "fail"
VERDICT_UNAVAILABLE = "unavailable"

STATUS_PASS = "pass"
STATUS_FAIL = "fail"
STATUS_UNAVAILABLE = "unavailable"

TIER_STATIC = "static"
TIER_HARDWARE = "hardware"

# The closed value sets above, stated as types so a wrong string is a type
# error rather than a comment nobody checks.
Verdict = Literal["pass", "fail", "unavailable"]
Tier = Literal["static", "hardware"]
Confidence = Literal["static-only", "hardware-observed"]


@dataclass(frozen=True)
class CheckResult:
    """One named check and its outcome. `id` is a stable identifier -- a
    catalog `RejectReason` value or a `rig.song.Finding` code -- never
    free-text, so a caller (or a later run) can match checks across reports."""

    id: str
    status: Verdict
    message: str = ""


@dataclass(frozen=True)
class SongChecks:
    """Every check run against one song. `status` is the aggregate: `fail`
    if any check failed, `unavailable` if every check was unavailable
    (device-only, never true for the static tier), else `pass`."""

    song: str
    status: Verdict
    checks: list[CheckResult] = field(default_factory=list)


@dataclass(frozen=True)
class Subject:
    """The exact identity a result belongs to (docs/validation.md
    "Subject"). A static run fills what it can from the repo and the pinned
    OS/Pd/ORHACK build; device-only members (`s2_device_id`,
    `midi_port_name`) and the hardware-only `stimulus_profile_version` stay
    `None` until the hardware tier runs."""

    commit: Optional[str]
    report_schema_version: int
    module_lock_digest: Optional[str]
    s2_device_id: Optional[str]
    os_version: Optional[str]
    pd_version: Optional[str]
    orhack_version: Optional[str]
    midi_port_name: Optional[str]
    stimulus_profile_version: Optional[str]


@dataclass(frozen=True)
class Report:
    schema_version: int
    verdict: Verdict
    tier: Tier
    subject: Subject
    run_id: str
    checks: list[SongChecks]
    metrics: dict[str, Any]
    failures: list[CheckResult]
    started_at: str  # ISO 8601, UTC
    ended_at: str  # ISO 8601, UTC
    confidence: Confidence
    scope_note: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ReportIntegrityError(RuntimeError):
    """A report's stored digest does not match its content -- it has been
    edited, truncated or corrupted since `write_report` wrote it."""


def _canonical_bytes(body: dict) -> bytes:
    """A stable byte encoding for hashing: sorted keys, no incidental
    whitespace, so on-disk pretty-printing never changes the digest."""
    return json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")


def compute_digest(body: dict) -> str:
    """sha256 over every field except `integrity` itself."""
    stripped = {k: v for k, v in body.items() if k != "integrity"}
    return hashlib.sha256(_canonical_bytes(stripped)).hexdigest()


def write_report(report: Report, path: Path) -> None:
    """Write `report` as canonical JSON plus a self-contained integrity
    digest. Not a cryptographic signature -- there is no third party to
    convince (decision #62's reasoning applies here too) -- just enough to
    catch a hand edit, which is all `verify-report` promises."""
    body = report.to_dict()
    digest = compute_digest(body)
    body["integrity"] = {"algorithm": "sha256", "digest": digest}
    write_text_atomic(path, json.dumps(body, indent=2, sort_keys=True) + "\n")


def verify_report(path: Path) -> None:
    """Raise `ReportIntegrityError` if `path` was edited since `write_report`
    wrote it. Raises `FileNotFoundError` if `path` does not exist -- the
    caller's problem to report, not this function's to hide."""
    data = json.loads(path.read_text(encoding="utf-8"))
    integrity = data.get("integrity")
    if not isinstance(integrity, dict) or "digest" not in integrity:
        raise ReportIntegrityError(f"{path}: no integrity digest recorded -- not a report this tool wrote")
    expected = integrity["digest"]
    actual = compute_digest(data)
    if actual != expected:
        raise ReportIntegrityError(f"{path}: digest mismatch -- report has been modified since it was written")
