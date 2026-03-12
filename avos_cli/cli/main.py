"""CLI entry point for the avos command.

Thin layer: parses arguments, resolves credentials from environment,
instantiates services, and delegates to orchestrators.
"""

from __future__ import annotations

import os
from pathlib import Path

import typer
from dotenv import load_dotenv

from avos_cli import __version__
from avos_cli.utils.output import print_error

# Load environment variables: cwd first, then package root (editable install),
# then ~/.avos/.env. Later loads do not override existing vars.
load_dotenv()
try:
    _pkg_root = Path(__file__).resolve().parent.parent.parent
    _pkg_env = _pkg_root / ".env"
    if _pkg_env.exists():
        load_dotenv(_pkg_env)
except Exception:
    pass
_avos_home = Path.home() / ".avos"
if (_avos_home / ".env").exists():
    load_dotenv(_avos_home / ".env")

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


def _first_env(*keys: str) -> str:
    """Return the first non-empty env value for any of the given keys."""
    for k in keys:
        v = os.environ.get(k, "")
        if v and isinstance(v, str):
            return v.strip()
    return ""


def _make_reply_service() -> object | None:
    """Build ReplyOutputService from env if REPLY_MODEL, REPLY_MODEL_URL, REPLY_MODEL_API_KEY are set."""
    model = _first_env("REPLY_MODEL", "reply_model")
    url = _first_env("REPLY_MODEL_URL", "reply_model_URL", "reply_model_url")
    api_key = _first_env("REPLY_MODEL_API_KEY", "reply_model_API_KEY", "reply_model_api_key")
    if model and url and api_key:
        from avos_cli.services.reply_output_service import ReplyOutputService
        return ReplyOutputService(api_key=api_key, api_url=url, model=model)
    return None


@app.callback()
def main(
    ctx: typer.Context,
    version: bool | None = typer.Option(
        None,
        "--version",
        "-v",
        help="Show version and exit.",
        callback=_version_callback,
        is_eager=True,
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        help="Enable verbose debug output.",
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Emit machine-readable JSON output.",
    ),
) -> None:
    """AVOS CLI - Developer memory for repositories."""
    ctx.ensure_object(dict)
    ctx.obj["verbose"] = verbose
    ctx.obj["json"] = json_output


@app.command()
def connect(
    ctx: typer.Context,
    repo: str = typer.Argument(..., help="Repository slug in 'org/repo' format."),
) -> None:
    """Connect a repository to Avos Memory."""
    from avos_cli.commands.connect import ConnectOrchestrator
    from avos_cli.config.manager import find_repo_root
    from avos_cli.exceptions import RepositoryContextError
    from avos_cli.services.git_client import GitClient
    from avos_cli.services.github_client import GitHubClient
    from avos_cli.services.memory_client import AvosMemoryClient

    json_output = ctx.obj.get("json", False)

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
    code = orchestrator.run(repo, json_output=json_output)
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
    ctx: typer.Context,
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

    json_output = ctx.obj.get("json", False)
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
    code = orchestrator.run(repo, since_days=since_days, json_output=json_output)
    raise typer.Exit(code)


@app.command(name="ingest-pr")
def ingest_pr(
    ctx: typer.Context,
    repo: str = typer.Argument(..., help="Repository slug in 'org/repo' format."),
    pr_number: int = typer.Argument(..., help="PR number to ingest."),
) -> None:
    """Ingest a single PR into Avos Memory."""
    from avos_cli.commands.ingest_pr import IngestPROrchestrator
    from avos_cli.config.hash_store import IngestHashStore
    from avos_cli.config.manager import find_repo_root
    from avos_cli.exceptions import RepositoryContextError
    from avos_cli.services.github_client import GitHubClient
    from avos_cli.services.memory_client import AvosMemoryClient

    json_output = ctx.obj.get("json", False)

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

    orchestrator = IngestPROrchestrator(
        memory_client=AvosMemoryClient(api_key=api_key, api_url=api_url),
        github_client=GitHubClient(token=github_token),
        hash_store=hash_store,
        repo_root=repo_root,
    )
    code = orchestrator.run(repo, pr_number, json_output=json_output)
    raise typer.Exit(code)


@app.command()
def ask(
    ctx: typer.Context,
    question: str = typer.Argument(..., help="Natural language question about the repository."),
) -> None:
    """Ask a question about the repository and get an evidence-backed answer."""
    from avos_cli.commands.ask import AskOrchestrator
    from avos_cli.config.manager import find_repo_root, load_config
    from avos_cli.exceptions import (
        ConfigurationNotInitializedError,
        RepositoryContextError,
    )
    from avos_cli.services.llm_client import LLMClient
    from avos_cli.services.memory_client import AvosMemoryClient

    json_output = ctx.obj.get("json", False)

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

    try:
        config = load_config(repo_root)
    except ConfigurationNotInitializedError:
        print_error("[AUTH_ERROR] Repository not connected. Run 'avos connect org/repo' first.")
        raise typer.Exit(1)

    provider = config.llm.provider.lower()
    if provider == "openai":
        llm_api_key = os.environ.get("OPENAI_API_KEY", "")
        if not llm_api_key:
            print_error("[AUTH_ERROR] OPENAI_API_KEY environment variable is required for OpenAI.")
            raise typer.Exit(1)
    else:
        llm_api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not llm_api_key:
            print_error("[AUTH_ERROR] ANTHROPIC_API_KEY environment variable is required for LLM synthesis.")
            raise typer.Exit(1)

    reply_service = _make_reply_service()
    orchestrator = AskOrchestrator(
        memory_client=AvosMemoryClient(api_key=api_key, api_url=api_url),
        llm_client=LLMClient(api_key=llm_api_key, provider=provider),
        repo_root=repo_root,
        reply_service=reply_service,
    )
    code = orchestrator.run("_/_", question, json_output=json_output)
    raise typer.Exit(code)


@app.command(name="session-ask")
def session_ask(
    ctx: typer.Context,
    question: str = typer.Argument(
        ..., help="Natural language question about session/live context."
    ),
) -> None:
    """Ask a question about current session and team work (Memory B)."""
    from avos_cli.commands.session_ask import SessionAskOrchestrator
    from avos_cli.config.manager import find_repo_root, load_config
    from avos_cli.exceptions import (
        ConfigurationNotInitializedError,
        RepositoryContextError,
    )
    from avos_cli.services.llm_client import LLMClient
    from avos_cli.services.memory_client import AvosMemoryClient

    json_output = ctx.obj.get("json", False)

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

    try:
        config = load_config(repo_root)
    except ConfigurationNotInitializedError:
        print_error("[AUTH_ERROR] Repository not connected. Run 'avos connect org/repo' first.")
        raise typer.Exit(1)

    provider = config.llm.provider.lower()
    if provider == "openai":
        llm_api_key = os.environ.get("OPENAI_API_KEY", "")
        if not llm_api_key:
            print_error("[AUTH_ERROR] OPENAI_API_KEY environment variable is required for OpenAI.")
            raise typer.Exit(1)
    else:
        llm_api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not llm_api_key:
            print_error("[AUTH_ERROR] ANTHROPIC_API_KEY environment variable is required for LLM synthesis.")
            raise typer.Exit(1)

    reply_service = _make_reply_service()
    orchestrator = SessionAskOrchestrator(
        memory_client=AvosMemoryClient(api_key=api_key, api_url=api_url),
        llm_client=LLMClient(api_key=llm_api_key, provider=provider),
        repo_root=repo_root,
        reply_service=reply_service,
    )
    code = orchestrator.run(config.repo, question, json_output=json_output)
    raise typer.Exit(code)


@app.command()
def history(
    ctx: typer.Context,
    subject: str = typer.Argument(..., help="Subject or topic for chronological history."),
) -> None:
    """Get a chronological history of a subject in the repository."""
    from avos_cli.commands.history import HistoryOrchestrator
    from avos_cli.config.manager import find_repo_root, load_config
    from avos_cli.exceptions import (
        ConfigurationNotInitializedError,
        RepositoryContextError,
    )
    from avos_cli.services.llm_client import LLMClient
    from avos_cli.services.memory_client import AvosMemoryClient

    json_output = ctx.obj.get("json", False)

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

    try:
        config = load_config(repo_root)
    except ConfigurationNotInitializedError:
        print_error("[AUTH_ERROR] Repository not connected. Run 'avos connect org/repo' first.")
        raise typer.Exit(1)

    provider = config.llm.provider.lower()
    if provider == "openai":
        llm_api_key = os.environ.get("OPENAI_API_KEY", "")
        if not llm_api_key:
            print_error("[AUTH_ERROR] OPENAI_API_KEY environment variable is required for OpenAI.")
            raise typer.Exit(1)
    else:
        llm_api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not llm_api_key:
            print_error("[AUTH_ERROR] ANTHROPIC_API_KEY environment variable is required for LLM synthesis.")
            raise typer.Exit(1)

    reply_service = _make_reply_service()
    orchestrator = HistoryOrchestrator(
        memory_client=AvosMemoryClient(api_key=api_key, api_url=api_url),
        llm_client=LLMClient(api_key=llm_api_key, provider=provider),
        repo_root=repo_root,
        reply_service=reply_service,
    )
    code = orchestrator.run("_/_", subject, json_output=json_output)
    raise typer.Exit(code)


@app.command(name="session-start")
def session_start(
    ctx: typer.Context,
    goal: str = typer.Argument(..., help="Session goal description."),
    agent: str | None = typer.Option(
        None, "--agent", help="Custom agent/developer name (e.g. 'agentA')."
    ),
) -> None:
    """Start a coding session with a goal and background activity capture."""
    from avos_cli.commands.session_start import SessionStartOrchestrator
    from avos_cli.config.manager import find_repo_root
    from avos_cli.exceptions import RepositoryContextError
    from avos_cli.services.git_client import GitClient
    from avos_cli.services.memory_client import AvosMemoryClient

    json_output = ctx.obj.get("json", False)

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
    code = orchestrator.run(goal, agent=agent, json_output=json_output)
    raise typer.Exit(code)


@app.command(name="session-end")
def session_end(ctx: typer.Context) -> None:
    """End the current coding session and store a session memory artifact."""
    from avos_cli.commands.session_end import SessionEndOrchestrator
    from avos_cli.config.manager import find_repo_root
    from avos_cli.exceptions import RepositoryContextError
    from avos_cli.services.git_client import GitClient
    from avos_cli.services.memory_client import AvosMemoryClient

    json_output = ctx.obj.get("json", False)

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
        llm_client=None,
        git_client=GitClient(),
        repo_root=repo_root,
    )
    code = orchestrator.run(json_output=json_output)
    raise typer.Exit(code)


@app.command(name="session-status")
def session_status(ctx: typer.Context) -> None:
    """Check if a coding session is currently active."""
    from avos_cli.commands.session_status import SessionStatusOrchestrator
    from avos_cli.config.manager import find_repo_root
    from avos_cli.exceptions import RepositoryContextError

    json_output = ctx.obj.get("json", False)

    try:
        repo_root = find_repo_root(Path.cwd())
    except RepositoryContextError as e:
        print_error(f"[REPOSITORY_CONTEXT_ERROR] {e}")
        raise typer.Exit(1) from e

    orchestrator = SessionStatusOrchestrator(repo_root=repo_root)
    code = orchestrator.run(json_output=json_output)
    raise typer.Exit(code)


@app.command(name="worktree-init")
def worktree_init() -> None:
    """Initialize avos in an existing git worktree by copying config from a sibling."""
    from avos_cli.commands.worktree_init import WorktreeInitOrchestrator
    from avos_cli.config.manager import find_repo_root
    from avos_cli.exceptions import RepositoryContextError
    from avos_cli.services.git_client import GitClient

    try:
        repo_root = find_repo_root(Path.cwd())
    except RepositoryContextError as e:
        print_error(f"[REPOSITORY_CONTEXT_ERROR] {e}")
        raise typer.Exit(1) from e

    orchestrator = WorktreeInitOrchestrator(
        git_client=GitClient(),
        repo_root=repo_root,
    )
    code = orchestrator.run()
    raise typer.Exit(code)


@app.command(name="worktree-add")
def worktree_add(
    path: str = typer.Argument(..., help="Filesystem path for the new worktree."),
    branch: str = typer.Argument(..., help="Branch name to create in the new worktree."),
    goal: str = typer.Argument(..., help="Session goal description for the new worktree."),
    agent: str | None = typer.Option(
        None, "--agent", help="Custom agent/developer name (e.g. 'agentA')."
    ),
) -> None:
    """Create a git worktree with automatic config copy and session start."""
    from avos_cli.commands.worktree_add import WorktreeAddOrchestrator
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

    orchestrator = WorktreeAddOrchestrator(
        git_client=GitClient(),
        memory_client=AvosMemoryClient(api_key=api_key, api_url=api_url),
        repo_root=repo_root,
    )
    code = orchestrator.run(path=path, branch=branch, goal=goal, agent=agent)
    raise typer.Exit(code)


@app.command(name="hook-install")
def hook_install(
    force: bool = typer.Option(
        False, "--force", "-f", help="Overwrite existing pre-push hook."
    ),
) -> None:
    """Install git hook for automatic commit sync on push."""
    from avos_cli.commands.hook_install import HookInstallOrchestrator
    from avos_cli.config.manager import find_repo_root
    from avos_cli.exceptions import RepositoryContextError
    from avos_cli.services.git_client import GitClient

    try:
        repo_root = find_repo_root(Path.cwd())
    except RepositoryContextError as e:
        print_error(f"[REPOSITORY_CONTEXT_ERROR] {e}")
        raise typer.Exit(1) from e

    orchestrator = HookInstallOrchestrator(
        git_client=GitClient(),
        repo_root=repo_root,
    )
    code = orchestrator.run(force=force)
    raise typer.Exit(code)


@app.command(name="hook-uninstall")
def hook_uninstall() -> None:
    """Remove the avos pre-push git hook."""
    from avos_cli.commands.hook_install import HookUninstallOrchestrator
    from avos_cli.config.manager import find_repo_root
    from avos_cli.exceptions import RepositoryContextError

    try:
        repo_root = find_repo_root(Path.cwd())
    except RepositoryContextError as e:
        print_error(f"[REPOSITORY_CONTEXT_ERROR] {e}")
        raise typer.Exit(1) from e

    orchestrator = HookUninstallOrchestrator(repo_root=repo_root)
    code = orchestrator.run()
    raise typer.Exit(code)


@app.command(name="hook-sync", hidden=True)
def hook_sync(
    old_sha: str = typer.Argument(..., help="Base commit SHA (remote has this)."),
    new_sha: str = typer.Argument(..., help="Target commit SHA (pushing this)."),
) -> None:
    """Sync commits to Avos Memory (called by pre-push hook)."""
    from avos_cli.commands.hook_sync import HookSyncOrchestrator
    from avos_cli.config.hash_store import IngestHashStore
    from avos_cli.config.manager import find_repo_root
    from avos_cli.exceptions import RepositoryContextError
    from avos_cli.services.git_client import GitClient
    from avos_cli.services.memory_client import AvosMemoryClient

    api_key = os.environ.get("AVOS_API_KEY", "")
    api_url = os.environ.get("AVOS_API_URL", "https://api.avos.ai")

    if not api_key:
        return

    try:
        repo_root = find_repo_root(Path.cwd())
    except RepositoryContextError:
        return

    avos_dir = repo_root / ".avos"
    hash_store = IngestHashStore(avos_dir)
    hash_store.load()

    orchestrator = HookSyncOrchestrator(
        memory_client=AvosMemoryClient(api_key=api_key, api_url=api_url),
        git_client=GitClient(),
        hash_store=hash_store,
        repo_root=repo_root,
    )
    code = orchestrator.run(old_sha, new_sha)
    raise typer.Exit(code)


if __name__ == "__main__":
    app()
