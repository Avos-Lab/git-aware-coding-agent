"""Terminal output formatting for AVOS CLI.

Uses Rich for interactive terminals (progress bars, colored status),
with plain text fallback for piped/non-TTY output.
"""

from __future__ import annotations

import sys

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.theme import Theme

_theme = Theme(
    {
        "success": "bold green",
        "error": "bold red",
        "warning": "bold yellow",
        "info": "bold blue",
        "dim": "dim",
    }
)

console = Console(theme=_theme, stderr=True)


def is_interactive() -> bool:
    """Check if stdout is connected to an interactive terminal."""
    return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()


def print_success(message: str) -> None:
    """Print a success message in green."""
    if is_interactive():
        console.print(f"[success]\u2713[/success] {message}")
    else:
        print(f"OK: {message}")


def print_error(message: str) -> None:
    """Print an error message in red."""
    if is_interactive():
        console.print(f"[error]\u2717[/error] {message}")
    else:
        print(f"ERROR: {message}", file=sys.stderr)


def print_warning(message: str) -> None:
    """Print a warning message in yellow."""
    if is_interactive():
        console.print(f"[warning]\u26a0[/warning] {message}")
    else:
        print(f"WARN: {message}", file=sys.stderr)


def print_info(message: str) -> None:
    """Print an informational message."""
    if is_interactive():
        console.print(f"[info]\u2139[/info] {message}")
    else:
        print(message)


def create_progress(description: str = "Processing...") -> Progress:
    """Create a Rich progress bar for long-running operations.

    Args:
        description: Text label for the progress bar.

    Returns:
        A Rich Progress context manager.
    """
    return Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    )
