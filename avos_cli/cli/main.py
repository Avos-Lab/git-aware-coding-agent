"""CLI entry point for the avos command.

Thin layer: parses arguments, resolves credentials from environment,
instantiates services, and delegates to orchestrators.
"""

from __future__ import annotations

import os
from pathlib import Path

import typer

from avos_cli import __version__
from avos_cli.utils.output import print_error

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


@app.command()
def connect(
    repo: str = typer.Argument(..., help="Repository slug in 'org/repo' format."),
) -> None:
    """Connect a repository to Avos Memory."""
    from avos_cli.commands.connect import ConnectOrchestrator
    from avos_cli.config.manager import find_repo_root
    from avos_cli.exceptions import RepositoryContextError
    from avos_cli.services.git_client import GitClient
    from avos_cli.services.github_client import GitHubClient
    from avos_cli.services.memory_client import AvosMemoryClient

    api_key = os.environ.get("AVOS_API_KEY", "")
    api_url = os.environ.get("AVOS_API_URL", "https://api.avos.ai")
    github_token = os.environ.get("GITHUB_TOKEN", "")

    if not api_key:
        print_error("[AUTH_ERROR] AVOS_API_KEY environment variable is required.")
        raise typer.Exit(1)
    if not github_token:
        print_error("[AUTH_ERROR] GITHUB_TOKEN environment variable is required.")
        raise typer.Exit(1)

    try:
        repo_root = find_repo_root(Path.cwd())
    except RepositoryContextError as e:
        print_error(f"[REPOSITORY_CONTEXT_ERROR] {e}")
        raise typer.Exit(1) from e

    orchestrator = ConnectOrchestrator(
        git_client=GitClient(),
        github_client=GitHubClient(token=github_token),
        memory_client=AvosMemoryClient(api_key=api_key, api_url=api_url),
        repo_root=repo_root,
    )
    code = orchestrator.run(repo)
    raise typer.Exit(code)


def _parse_since_days(value: str) -> int:
    """Parse a '--since Nd' value like '90d' into integer days."""
    cleaned = value.strip().lower()
    if cleaned.endswith("d"):
        cleaned = cleaned[:-1]
    try:
        days = int(cleaned)
        if days <= 0:
            raise typer.BadParameter("--since must be a positive number of days.")
        return days
    except ValueError as e:
        raise typer.BadParameter(f"Invalid --since value: '{value}'. Expected format: '90d' or '90'.") from e


@app.command()
def ingest(
    repo: str = typer.Argument(..., help="Repository slug in 'org/repo' format."),
    since: str = typer.Option("90d", "--since", help="Time window, e.g. '90d' for 90 days."),
) -> None:
    """Ingest repository history into Avos Memory."""
    from avos_cli.commands.ingest import IngestOrchestrator
    from avos_cli.config.hash_store import IngestHashStore
    from avos_cli.config.lock import IngestLockManager
    from avos_cli.config.manager import find_repo_root
    from avos_cli.exceptions import RepositoryContextError
    from avos_cli.services.git_client import GitClient
    from avos_cli.services.github_client import GitHubClient
    from avos_cli.services.memory_client import AvosMemoryClient

    since_days = _parse_since_days(since)

    api_key = os.environ.get("AVOS_API_KEY", "")
    api_url = os.environ.get("AVOS_API_URL", "https://api.avos.ai")
    github_token = os.environ.get("GITHUB_TOKEN", "")

    if not api_key:
        print_error("[AUTH_ERROR] AVOS_API_KEY environment variable is required.")
        raise typer.Exit(1)
    if not github_token:
        print_error("[AUTH_ERROR] GITHUB_TOKEN environment variable is required.")
        raise typer.Exit(1)

    try:
        repo_root = find_repo_root(Path.cwd())
    except RepositoryContextError as e:
        print_error(f"[REPOSITORY_CONTEXT_ERROR] {e}")
        raise typer.Exit(1) from e

    avos_dir = repo_root / ".avos"
    hash_store = IngestHashStore(avos_dir)
    hash_store.load()

    orchestrator = IngestOrchestrator(
        memory_client=AvosMemoryClient(api_key=api_key, api_url=api_url),
        github_client=GitHubClient(token=github_token),
        git_client=GitClient(),
        hash_store=hash_store,
        lock_manager=IngestLockManager(avos_dir),
        repo_root=repo_root,
    )
    code = orchestrator.run(repo, since_days=since_days)
    raise typer.Exit(code)


@app.command()
def ask(
    question: str = typer.Argument(..., help="Natural language question about the repository."),
) -> None:
    """Ask a question about the repository and get an evidence-backed answer."""
    from avos_cli.commands.ask import AskOrchestrator
    from avos_cli.config.manager import find_repo_root
    from avos_cli.exceptions import RepositoryContextError
    from avos_cli.services.llm_client import LLMClient
    from avos_cli.services.memory_client import AvosMemoryClient

    api_key = os.environ.get("AVOS_API_KEY", "")
    api_url = os.environ.get("AVOS_API_URL", "https://api.avos.ai")
    llm_provider = os.environ.get("AVOS_LLM_PROVIDER", "")
    llm_model = os.environ.get("AVOS_LLM_MODEL", "")

    if not api_key:
        print_error("[AUTH_ERROR] AVOS_API_KEY environment variable is required.")
        raise typer.Exit(1)

    try:
        repo_root = find_repo_root(Path.cwd())
    except RepositoryContextError as e:
        print_error(f"[REPOSITORY_CONTEXT_ERROR] {e}")
        raise typer.Exit(1) from e

    orchestrator = AskOrchestrator(
        memory_client=AvosMemoryClient(api_key=api_key, api_url=api_url),
        llm_client=LLMClient(api_key=api_key),
        repo_root=repo_root,
    )
    code = orchestrator.run("_/_", question)
    raise typer.Exit(code)


@app.command()
def history(
    subject: str = typer.Argument(..., help="Subject or topic for chronological history."),
) -> None:
    """Get a chronological history of a subject in the repository."""
    from avos_cli.commands.history import HistoryOrchestrator
    from avos_cli.config.manager import find_repo_root
    from avos_cli.exceptions import RepositoryContextError
    from avos_cli.services.llm_client import LLMClient
    from avos_cli.services.memory_client import AvosMemoryClient

    api_key = os.environ.get("AVOS_API_KEY", "")
    api_url = os.environ.get("AVOS_API_URL", "https://api.avos.ai")

    if not api_key:
        print_error("[AUTH_ERROR] AVOS_API_KEY environment variable is required.")
        raise typer.Exit(1)

    try:
        repo_root = find_repo_root(Path.cwd())
    except RepositoryContextError as e:
        print_error(f"[REPOSITORY_CONTEXT_ERROR] {e}")
        raise typer.Exit(1) from e

    orchestrator = HistoryOrchestrator(
        memory_client=AvosMemoryClient(api_key=api_key, api_url=api_url),
        llm_client=LLMClient(api_key=api_key),
        repo_root=repo_root,
    )
    code = orchestrator.run("_/_", subject)
    raise typer.Exit(code)


@app.command(name="session-start")
def session_start(
    goal: str = typer.Argument(..., help="Session goal description."),
) -> None:
    """Start a coding session with a goal and background activity capture."""
    from avos_cli.commands.session_start import SessionStartOrchestrator
    from avos_cli.config.manager import find_repo_root
    from avos_cli.exceptions import RepositoryContextError
    from avos_cli.services.git_client import GitClient
    from avos_cli.services.memory_client import AvosMemoryClient

    api_key = os.environ.get("AVOS_API_KEY", "")
    api_url = os.environ.get("AVOS_API_URL", "https://api.avos.ai")

    if not api_key:
        print_error("[AUTH_ERROR] AVOS_API_KEY environment variable is required.")
        raise typer.Exit(1)

    try:
        repo_root = find_repo_root(Path.cwd())
    except RepositoryContextError as e:
        print_error(f"[REPOSITORY_CONTEXT_ERROR] {e}")
        raise typer.Exit(1) from e

    orchestrator = SessionStartOrchestrator(
        git_client=GitClient(),
        memory_client=AvosMemoryClient(api_key=api_key, api_url=api_url),
        repo_root=repo_root,
    )
    code = orchestrator.run(goal)
    raise typer.Exit(code)


@app.command(name="session-end")
def session_end() -> None:
    """End the current coding session and store a session memory artifact."""
    from avos_cli.commands.session_end import SessionEndOrchestrator
    from avos_cli.config.manager import find_repo_root
    from avos_cli.exceptions import RepositoryContextError
    from avos_cli.services.llm_client import LLMClient
    from avos_cli.services.memory_client import AvosMemoryClient

    api_key = os.environ.get("AVOS_API_KEY", "")
    api_url = os.environ.get("AVOS_API_URL", "https://api.avos.ai")

    if not api_key:
        print_error("[AUTH_ERROR] AVOS_API_KEY environment variable is required.")
        raise typer.Exit(1)

    try:
        repo_root = find_repo_root(Path.cwd())
    except RepositoryContextError as e:
        print_error(f"[REPOSITORY_CONTEXT_ERROR] {e}")
        raise typer.Exit(1) from e

    orchestrator = SessionEndOrchestrator(
        memory_client=AvosMemoryClient(api_key=api_key, api_url=api_url),
        llm_client=LLMClient(api_key=api_key),
        repo_root=repo_root,
    )
    code = orchestrator.run()
    raise typer.Exit(code)


if __name__ == "__main__":
    app()
