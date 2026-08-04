"""CLI command surface: every command is a stub, and the surface is complete.

Bodies are filled in later phases; this only pins the argument/option shape
the brief specifies, and that every stub fails loudly rather than silently
doing nothing.
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


def test_catalog_update_not_implemented():
    result = runner.invoke(app, ["catalog", "update", "--dry-run"])
    assert result.exit_code != 0
    assert "not implemented" in result.output


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
