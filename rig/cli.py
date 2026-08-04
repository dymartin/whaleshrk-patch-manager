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


@app.command(
    context_settings={"ignore_unknown_options": True},
)
def validate(
    args: Optional[list[str]] = typer.Argument(
        None, help="SONG... , or 'verify-report REPORT'"
    ),
    tier: Optional[str] = typer.Option(None, "--tier", help="static|hardware"),
) -> None:
    """rig validate --tier static|hardware [SONG...]

    rig validate verify-report REPORT

    A single flat command, not a subcommand group: typer/click resolve a
    group's leftover positional tokens as a subcommand name before the
    group's own callback runs, which would swallow SONG names meant for the
    --tier form. Dispatch on args[0] instead.
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
