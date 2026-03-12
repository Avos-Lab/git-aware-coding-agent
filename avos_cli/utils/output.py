"""Terminal output formatting for AVOS CLI.

Uses Rich for interactive terminals (tables, panels, trees, progress bars,
colored status), with plain text fallback for piped/non-TTY output.
"""

from __future__ import annotations

import json
import sys

from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table
from rich.theme import Theme
from rich.tree import Tree

_theme = Theme(
    {
        "success": "bold green",
        "error": "bold red",
        "warning": "bold yellow",
        "info": "bold blue",
        "dim": "dim",
        "high": "bold red",
        "medium": "bold yellow",
        "low": "bold cyan",
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
        console.print("[success]\u2713[/success] ", end="")
        console.print(message, markup=False)
    else:
        print(f"OK: {message}")


def print_error(message: str) -> None:
    """Print an error message in red."""
    if is_interactive():
        console.print("[error]\u2717[/error] ", end="")
        console.print(message, markup=False)
    else:
        print(f"ERROR: {message}", file=sys.stderr)


def print_warning(message: str) -> None:
    """Print a warning message in yellow."""
    if is_interactive():
        console.print("[warning]\u26a0[/warning] ", end="")
        console.print(message, markup=False)
    else:
        print(f"WARN: {message}", file=sys.stderr)


def print_info(message: str) -> None:
    """Print an informational message."""
    if is_interactive():
        console.print("[info]\u2139[/info] ", end="")
        console.print(message, markup=False)
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


def render_table(
    title: str,
    columns: list[tuple[str, str]],
    rows: list[list[str]],
) -> None:
    """Render a Rich table or plain-text equivalent.

    Args:
        title: Table title displayed above the table.
        columns: List of (header_text, style) tuples.
        rows: List of row data (each row is a list of strings matching columns).
    """
    if is_interactive():
        table = Table(title=title, show_lines=False, pad_edge=True)
        for header, style in columns:
            table.add_column(header, style=style)
        for row in rows:
            table.add_row(*row)
        console.print(table)
    else:
        print(f"\n{title}")
        headers = [h for h, _ in columns]
        print("  " + " | ".join(headers))
        print("  " + "-+-".join("-" * len(h) for h in headers))
        for row in rows:
            print("  " + " | ".join(row))


def render_panel(title: str, content: str, style: str = "info") -> None:
    """Render a Rich panel or plain-text equivalent.

    Args:
        title: Panel title.
        content: Panel body text.
        style: Border color style name.
    """
    if is_interactive():
        console.print(Panel(content, title=title, border_style=style, expand=False))
    else:
        print(f"\n--- {title} ---")
        print(content)
        print("---")


def render_tree(label: str, children: list[tuple[str, list[str]]]) -> None:
    """Render a Rich tree or plain-text indented equivalent.

    Args:
        label: Root label for the tree.
        children: List of (branch_label, [leaf_labels]) tuples.
    """
    if is_interactive():
        tree = Tree(f"[bold]{label}[/bold]")
        for branch_label, leaves in children:
            branch = tree.add(f"[info]{branch_label}[/info]")
            for leaf in leaves:
                branch.add(leaf)
        console.print(tree)
    else:
        print(f"\n{label}")
        for branch_label, leaves in children:
            print(f"  {branch_label}")
            for leaf in leaves:
                print(f"    {leaf}")


def render_kv_panel(title: str, pairs: list[tuple[str, str]], style: str = "info") -> None:
    """Render a key-value panel (Rich table inside a panel, or plain text).

    Args:
        title: Panel title.
        pairs: List of (key, value) tuples.
        style: Border color style name.
    """
    if is_interactive():
        table = Table(show_header=False, show_edge=False, pad_edge=False, box=None)
        table.add_column("Key", style="bold")
        table.add_column("Value")
        for k, v in pairs:
            table.add_row(k, v)
        console.print(Panel(table, title=title, border_style=style, expand=False))
    else:
        print(f"\n--- {title} ---")
        for k, v in pairs:
            print(f"  {k}: {v}")


