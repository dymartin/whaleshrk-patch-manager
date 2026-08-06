"""The canonical report schema and its tamper-evidence -- Prompt/09-static-
validation.md "Land the report schema first" and its Verification table's
"Hand-edited report" row."""

from __future__ import annotations

import json

import pytest

from rig.validate.report import (
    CheckResult,
    Report,
    ReportIntegrityError,
    SongChecks,
    Subject,
    verify_report,
    write_report,
)


def _subject(**overrides) -> Subject:
    base = dict(
        commit="deadbeef",
        report_schema_version=1,
        module_lock_digest="abc123",
        s2_device_id=None,
        os_version="5.1",
        pd_version="0.53.1+ds-2+deb12u1",
        orhack_version="0.52b",
        midi_port_name=None,
        stimulus_profile_version=None,
    )
    base.update(overrides)
    return Subject(**base)


def _report(**overrides) -> Report:
    base = dict(
        schema_version=1,
        verdict="pass",
        tier="static",
        subject=_subject(),
        run_id="run-1",
        checks=[SongChecks(song="vellichor", status="pass", checks=[CheckResult(id="schema-lint", status="pass")])],
        metrics={"catalog": {"modules_gated": 1, "modules_failed": 0, "modules_unavailable": 0}},
        failures=[],
        started_at="2026-01-01T00:00:00+00:00",
        ended_at="2026-01-01T00:00:01+00:00",
        confidence="static-only",
        scope_note="static-only: ... not evidence the rig is stage-ready.",
    )
    base.update(overrides)
    return Report(**base)


def test_report_round_trips_through_to_dict_as_plain_json_types():
    report = _report()
    data = report.to_dict()
    # Every value must survive json.dumps/loads unchanged -- this is the
    # exact shape written to disk and read back by verify_report.
    reparsed = json.loads(json.dumps(data))
    assert reparsed["verdict"] == "pass"
    assert reparsed["subject"]["commit"] == "deadbeef"
    assert reparsed["checks"][0]["song"] == "vellichor"


def test_write_report_then_verify_report_succeeds(tmp_path):
    path = tmp_path / "report.json"
    write_report(_report(), path)

    verify_report(path)  # raises on failure -- no exception is the assertion


def test_write_report_embeds_the_scope_note_in_the_file_itself(tmp_path):
    # Ruling #2: the disclaimer must travel with the data, not just print to
    # stdout at run time.
    path = tmp_path / "report.json"
    write_report(_report(), path)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert "not evidence the rig is stage-ready" in data["scope_note"]


def test_verify_report_rejects_a_hand_edited_field(tmp_path):
    path = tmp_path / "report.json"
    write_report(_report(verdict="fail"), path)

    data = json.loads(path.read_text(encoding="utf-8"))
    data["verdict"] = "pass"  # flip a failing report to look clean
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(ReportIntegrityError):
        verify_report(path)


def test_verify_report_rejects_a_missing_integrity_block(tmp_path):
    path = tmp_path / "report.json"
    path.write_text(json.dumps(_report().to_dict()), encoding="utf-8")

    with pytest.raises(ReportIntegrityError):
        verify_report(path)


def test_verify_report_raises_file_not_found_for_a_missing_path(tmp_path):
    with pytest.raises(FileNotFoundError):
        verify_report(tmp_path / "nope.json")


def test_write_report_ignores_incidental_formatting_changes():
    # Pretty-printing (whitespace only) must not itself break verification --
    # only content changes should. Confirmed by writing then re-serialising
    # the same dict compactly before verifying.
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "report.json"
        write_report(_report(), path)
        data = json.loads(path.read_text(encoding="utf-8"))
        path.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
        verify_report(path)
