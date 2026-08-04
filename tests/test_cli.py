"""CLI command surface: every command is reachable, and the surface is complete.

`catalog update` is implemented (Phase 1); every other command is still a
stub, filled in by a later phase. This pins the argument/option shape the
brief specifies, and that every stub fails loudly rather than silently doing
nothing.
"""

from typer.testing import CliRunner

from rig.cli import app

runner = CliRunner()


def test_help_lists_all_seven_commands():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for name in ["push", "pull", "lint", "catalog", "upgrade", "rename-chain", "validate"]:
        assert name in result.output


def test_push_not_implemented():
    result = runner.invoke(app, ["push", "song1", "--dry-run", "--force"])
    assert result.exit_code != 0
    assert "not implemented" in result.output


def test_pull_not_implemented():
    result = runner.invoke(app, ["pull", "song1", "--dry-run"])
    assert result.exit_code != 0
    assert "not implemented" in result.output


def test_lint_not_implemented():
    result = runner.invoke(app, ["lint", "song1"])
    assert result.exit_code != 0
    assert "not implemented" in result.output


def test_catalog_update_help_documents_the_command():
    # `catalog update` is implemented (Phase 1) and reaches the network for
    # its live discovery path, so it is not exercised end-to-end here --
    # tests/conftest.py blocks every socket for the whole session. Just
    # confirm the command is wired up and documented.
    result = runner.invoke(app, ["catalog", "update", "--help"])
    assert result.exit_code == 0
    assert "--dry-run" in result.output


def test_upgrade_not_implemented():
    result = runner.invoke(app, ["upgrade", "module-a", "module-b", "--dry-run"])
    assert result.exit_code != 0
    assert "not implemented" in result.output


def test_rename_chain_not_implemented():
    result = runner.invoke(app, ["rename-chain", "song1", "old", "new"])
    assert result.exit_code != 0
    assert "not implemented" in result.output


def test_validate_tier_form_not_implemented():
    result = runner.invoke(app, ["validate", "--tier", "static", "song1", "song2"])
    assert result.exit_code != 0
    assert "not implemented" in result.output


def test_validate_hardware_tier_with_no_songs():
    result = runner.invoke(app, ["validate", "--tier", "hardware"])
    assert result.exit_code != 0
    assert "not implemented" in result.output


def test_validate_verify_report_not_implemented():
    result = runner.invoke(app, ["validate", "verify-report", "report.json"])
    assert result.exit_code != 0
    assert "not implemented" in result.output


def test_validate_help_documents_both_invocation_forms():
    # `validate` is a flat command, not a subcommand group (see the comment
    # above it in rig/cli.py), so `verify-report` isn't a discoverable
    # subcommand on its own -- the help text is the only place a caller
    # learns it exists.
    result = runner.invoke(app, ["validate", "--help"])
    assert result.exit_code == 0
    assert "rig validate --tier static|hardware [SONG...]" in result.output
    assert "rig validate verify-report REPORT" in result.output
    assert "verify-report" in result.output
