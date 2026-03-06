"""CLI entry point for the avos command."""

from __future__ import annotations

import typer

from avos_cli import __version__

app = typer.Typer(
    name="avos",
    help="Developer memory CLI for repositories.",
    no_args_is_help=True,
    add_completion=False,
)


def _version_callback(value: bool) -> None:
    """Print version and exit."""
    if value:
        typer.echo(f"avos {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool | None = typer.Option(
        None,
        "--version",
        "-v",
        help="Show version and exit.",
        callback=_version_callback,
        is_eager=True,
    ),
) -> None:
    """AVOS CLI - Developer memory for repositories."""


if __name__ == "__main__":
    app()
