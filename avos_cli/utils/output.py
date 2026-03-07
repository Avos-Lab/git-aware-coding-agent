"""Terminal output formatting for AVOS CLI.

Uses Rich for interactive terminals (progress bars, colored status),
with plain text fallback for piped/non-TTY output.
"""

from __future__ import annotations

import json
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


class _NullProgress:
    """No-op progress context manager for JSON mode (suppress progress bars)."""

    def __enter__(self) -> _NullProgress:
        return self

    def __exit__(self, *args: object) -> None:
        pass


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


def print_json(success: bool, data: dict | None = None, error: dict | None = None) -> None:
    """Emit strict JSON envelope for machine-readable output.

    Per Q13: envelope is {"success": bool, "data": {...}, "error": {...}}.
    When success=True, error is None; when success=False, data is None.

    Args:
        success: Whether the operation succeeded.
        data: Command-specific payload (when success).
        error: Error payload with code, message, hint, retryable (when not success).
    """
    envelope: dict[str, object] = {
        "success": success,
        "data": data,
        "error": error,
    }
    print(json.dumps(envelope))


def print_verbose(label: str, message: str, verbose: bool = False) -> None:
    """Emit debug-level verbose line. Suppressed unless verbose is True.

    Args:
        label: Short label (e.g. "HTTP", "Config").
        message: Debug message.
        verbose: If False, does nothing.
    """
    if not verbose:
        return
    if is_interactive():
        console.print(f"[dim][{label}] {message}[/dim]")
    else:
        print(f"[{label}] {message}", file=sys.stderr)


def create_progress(description: str = "Processing...", suppress: bool = False) -> Progress | _NullProgress:
    """Create a Rich progress bar for long-running operations.

    When suppress=True (e.g. --json mode), returns a no-op progress that does nothing.

    Args:
        description: Text label for the progress bar.
        suppress: If True, return no-op progress (for JSON output mode).

    Returns:
        A Rich Progress context manager (or no-op when suppress).
    """
    if suppress:
        return _NullProgress()
    return Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    )
