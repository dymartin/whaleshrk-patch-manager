"""Validation report schema and the static (Tier 1) checks that emit it.

See docs/validation.md. The hardware (Tier 2) checks land in Task 10, into
this same `Report` shape (Prompt/09-static-validation.md Ruling #1).
"""

from .report import (
    CONFIDENCE_HARDWARE_OBSERVED,
    CONFIDENCE_STATIC_ONLY,
    REPORT_SCHEMA_VERSION,
    STATUS_FAIL,
    STATUS_PASS,
    STATUS_UNAVAILABLE,
    TIER_HARDWARE,
    TIER_STATIC,
    VERDICT_FAIL,
    VERDICT_PASS,
    VERDICT_UNAVAILABLE,
    CheckResult,
    Report,
    ReportIntegrityError,
    SongChecks,
    Subject,
    compute_digest,
    verify_report,
    write_report,
)
from .static import (
    CATALOG_GATE_CHECK_ID,
    ORHACK_VERSION,
    OS_VERSION,
    PD_VERSION,
    SCHEMA_LINT_CHECK_ID,
    catalog_gate_checks,
    locked_module_gate_checks,
    run_static,
)

__all__ = [
    "CONFIDENCE_HARDWARE_OBSERVED",
    "CONFIDENCE_STATIC_ONLY",
    "REPORT_SCHEMA_VERSION",
    "STATUS_FAIL",
    "STATUS_PASS",
    "STATUS_UNAVAILABLE",
    "TIER_HARDWARE",
    "TIER_STATIC",
    "VERDICT_FAIL",
    "VERDICT_PASS",
    "VERDICT_UNAVAILABLE",
    "CheckResult",
    "Report",
    "ReportIntegrityError",
    "SongChecks",
    "Subject",
    "compute_digest",
    "verify_report",
    "write_report",
    "CATALOG_GATE_CHECK_ID",
    "ORHACK_VERSION",
    "OS_VERSION",
    "PD_VERSION",
    "SCHEMA_LINT_CHECK_ID",
    "catalog_gate_checks",
    "locked_module_gate_checks",
    "run_static",
]
