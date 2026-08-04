"""`rig` command-line entry point.

Command surface only -- every body is a stub that exits non-zero. Fixed now so
later phases fill bodies without changing the arguments or options a musician
or CI job depends on.
"""

from __future__ import annotations

from typing import Optional

import typer

app = typer.Typer(no_args_is_help=True, add_completion=False)
catalog_app = typer.Typer(no_args_is_help=True)
app.add_typer(catalog_app, name="catalog")


def _not_implemented(command: str) -> None:
    typer.echo(f"rig {command}: not implemented", err=True)
    raise typer.Exit(code=1)


@app.command()
def push(
    song: Optional[list[str]] = typer.Argument(None),
    dry_run: bool = typer.Option(False, "--dry-run"),
    force: bool = typer.Option(False, "--force"),
) -> None:
    """Compile song YAML and write it to the card."""
    _not_implemented("push")


@app.command()
def pull(
    song: Optional[list[str]] = typer.Argument(None),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Detect card drift and open one PR per drifted song."""
    _not_implemented("pull")


@app.command()
def lint(
    song: Optional[list[str]] = typer.Argument(None),
) -> None:
    """Check song YAML without touching the card."""
    _not_implemented("lint")


@catalog_app.command("update")
def catalog_update(
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Rebuild .rig/catalog/ and .rig/modules.lock."""
    _not_implemented("catalog update")


@app.command()
def upgrade(
    module: list[str] = typer.Argument(...),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Bump pinned module versions in .rig/modules.lock."""
    _not_implemented("upgrade")


@app.command("rename-chain")
def rename_chain(
    song: str = typer.Argument(...),
    old: str = typer.Argument(...),
    new: str = typer.Argument(...),
) -> None:
    """Rename a chain within a song, preserving its letter binding."""
    _not_implemented("rename-chain")


# `validate` is a single flat command, deliberately not a typer sub-app/group,
# even though `verify-report` reads like a subcommand. typer's TyperGroup
# (vendored click) resolves a group's leftover positional tokens as a
# subcommand-name candidate before the group's own callback runs at all --
# confirmed against typer 0.27.1's TyperGroup.parse_args/invoke in
# typer/core.py -- regardless of allow_extra_args/ignore_unknown_options. A
# `song: list[str]` argument on a `validate` group callback therefore either
# swallows a literal `verify-report` (breaking subcommand dispatch) or, as a
# group argument, makes any non-empty SONG list fail with "No such command".
# Do not turn this back into a group; dispatch on args[0] instead.
@app.command(
    context_settings={"ignore_unknown_options": True},
    epilog=(
        "rig validate --tier static|hardware [SONG...]\n\n"
        "rig validate verify-report REPORT"
    ),
)
def validate(
    args: Optional[list[str]] = typer.Argument(
        None,
        metavar="[SONG]... | verify-report REPORT",
        help="Song names for --tier validation, or the literal "
        "'verify-report REPORT'.",
    ),
    tier: Optional[str] = typer.Option(None, "--tier", help="static|hardware"),
) -> None:
    """Run static or hardware validation, or verify a recorded report.

    Two invocation forms:

        rig validate --tier static|hardware [SONG...]

        rig validate verify-report REPORT
    """
    args = args or []
    if args and args[0] == "verify-report":
        if len(args) != 2:
            typer.echo("usage: rig validate verify-report REPORT", err=True)
            raise typer.Exit(code=2)
        _not_implemented("validate verify-report")
    _not_implemented("validate")


if __name__ == "__main__":
    app()
