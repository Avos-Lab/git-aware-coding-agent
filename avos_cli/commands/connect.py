"""Connect command orchestrator for AVOS CLI.

Implements the `avos connect` flow: validates Git repo, optionally
accepts `org/repo` or derives it from `origin`, verifies GitHub access,
creates bootstrap note in Avos Memory, and writes .avos/config.json
(including `repo` for later use as default context).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from avos_cli.config.manager import save_config
from avos_cli.config.state import read_json_safe
from avos_cli.exceptions import (
    AuthError,
    AvosError,
    RepositoryContextError,
    UpstreamUnavailableError,
)
from avos_cli.services.git_client import GitClient
from avos_cli.services.github_client import GitHubClient
from avos_cli.services.memory_client import AvosMemoryClient
from avos_cli.utils.logger import get_logger
from avos_cli.utils.output import (
    print_error,
    print_json,
    render_kv_panel,
)

_log = get_logger("commands.connect")

_BOOTSTRAP_MARKER = "repo_connected"


class ConnectOrchestrator:
    """Orchestrates the `avos connect` command.

    Precondition order (per Q7): Git repo -> slug (explicit or from
    origin) -> when explicit, remote must match -> GitHub API accessible
    -> Avos API accessible -> write config with `repo` slug persisted.

    Args:
        git_client: Local git operations wrapper.
        github_client: GitHub REST API client.
        memory_client: Avos Memory API client.
        repo_root: Path to the repository root.
    """

    def __init__(
        self,
        git_client: GitClient,
        github_client: GitHubClient,
        memory_client: AvosMemoryClient,
        repo_root: Path,
    ) -> None:
        self._git = git_client
        self._github = github_client
        self._memory = memory_client
        self._repo_root = repo_root

    def run(self, repo_slug: str | None = None, json_output: bool = False) -> int:
        """Execute the connect flow.

        Args:
            repo_slug: Repository identifier in 'org/repo' format. When
                omitted, the slug is read from ``git remote origin`` (GitHub
                HTTPS or SSH URL) and stored in config for later commands.
            json_output: If True, emit JSON output instead of human UI.

        Returns:
            Exit code: 0=success, 1=local precondition, 2=hard external.
        """
        self._json_output = json_output

        resolved = self._resolve_repo_slug(repo_slug)
        if resolved is None:
            return 1

        owner, repo = resolved.split("/", 1)

        if not self._verify_github_access(owner, repo):
            return self._last_exit_code

        memory_id = f"repo:{resolved}"

        if not self._verify_avos_access(memory_id, _BOOTSTRAP_MARKER):
            return self._last_exit_code

        if not self._bootstrap_exists and not self._send_bootstrap_note(
            memory_id, resolved, _BOOTSTRAP_MARKER
        ):
            return self._last_exit_code

        self._write_config(resolved, memory_id)

        # Auto-install pre-push hook for automatic commit sync
        hook_installed = self._auto_install_hook()

        config_path = str(self._repo_root / ".avos" / "config.json")
        if json_output:
            print_json(
                success=True,
                data={
                    "repo": resolved,
                    "memory_id": memory_id,
                    "config_path": config_path,
                    "hook_installed": hook_installed,
                },
                error=None,
            )
        else:
            hook_status = "installed" if hook_installed else "skipped (existing hook found)"
            render_kv_panel(
                f"Connected to {resolved}",
                [
                    ("Memory", memory_id),
                    ("Pre-push hook", hook_status),
                    ("Next step", "avos ingest"),
                ],
                style="success",
            )
        return 0

    def _emit_error(
        self, code: str, message: str, hint: str | None = None, retryable: bool = False
    ) -> None:
        """Emit error in JSON or human format based on mode."""
        if self._json_output:
            print_json(
                success=False,
                data=None,
                error={"code": code, "message": message, "hint": hint, "retryable": retryable},
            )
        else:
            print_error(f"[{code}] {message}")

    def _validate_slug(self, slug: str) -> bool:
        """Validate that slug is in 'org/repo' format."""
        if not slug or "/" not in slug:
            return False
        parts = slug.split("/", 1)
        return bool(parts[0]) and bool(parts[1])

    def _resolve_repo_slug(self, repo_slug: str | None) -> str | None:
        """Normalize user input or infer org/repo from ``origin``.

        When ``repo_slug`` is None or whitespace-only, uses
        ``GitClient.remote_origin`` (same parsing as explicit connect).

        When a non-empty slug is provided, validates format and checks it
        matches ``origin`` so forks cannot accidentally connect as upstream.

        Args:
            repo_slug: Explicit slug from CLI, or None to infer from git.

        Returns:
            ``org/repo`` string, or None after emitting an error.
        """
        if repo_slug is None:
            return self._infer_repo_slug_from_origin()

        trimmed = repo_slug.strip()
        if not trimmed:
            self._emit_error(
                "REPOSITORY_CONTEXT_ERROR",
                "Invalid repo slug format. Expected 'org/repo'.",
            )
            return None

        if not self._validate_slug(trimmed):
            self._emit_error(
                "REPOSITORY_CONTEXT_ERROR",
                "Invalid repo slug format. Expected 'org/repo'.",
            )
            return None

        if not self._verify_git_remote(trimmed):
            return None

        return trimmed

    def _infer_repo_slug_from_origin(self) -> str | None:
        """Read ``org/repo`` from ``git remote get-url origin``.

        Returns:
            Valid slug, or None after emitting an error.
        """
        try:
            remote = self._git.remote_origin(self._repo_root)
        except (RepositoryContextError, AvosError) as e:
            self._emit_error("REPOSITORY_CONTEXT_ERROR", str(e))
            return None

        if remote is None:
            self._emit_error(
                "REPOSITORY_CONTEXT_ERROR",
                "No origin remote found, or origin URL could not be parsed as "
                "org/repo. Add a GitHub remote or run: avos connect org/repo",
            )
            return None

        if not self._validate_slug(remote):
            self._emit_error(
                "REPOSITORY_CONTEXT_ERROR",
                f"Origin produced an invalid slug ({remote!r}). "
                "Run: avos connect org/repo",
            )
            return None

        return remote

    def _verify_git_remote(self, repo_slug: str) -> bool:
        """Verify git repo exists and remote matches the slug.

        Returns:
            True if valid, False with error output if not.
        """
        try:
            remote = self._git.remote_origin(self._repo_root)
        except (RepositoryContextError, AvosError) as e:
            self._emit_error("REPOSITORY_CONTEXT_ERROR", str(e))
            return False

        if remote is None:
            self._emit_error("REPOSITORY_CONTEXT_ERROR", "No origin remote found.")
            return False

        if remote != repo_slug:
            self._emit_error(
                "REPOSITORY_CONTEXT_ERROR",
                f"Remote origin '{remote}' does not match '{repo_slug}'.",
            )
            return False

        return True

    def _verify_github_access(self, owner: str, repo: str) -> bool:
        """Verify GitHub API access and repo existence.

        Sets self._last_exit_code on failure.
        """
        try:
            accessible = self._github.validate_repo(owner, repo)
        except AuthError as e:
            self._emit_error("AUTH_ERROR", f"GitHub: {e}")
            self._last_exit_code = 1
            return False
        except UpstreamUnavailableError as e:
            self._emit_error("UPSTREAM_UNAVAILABLE", f"GitHub: {e}", retryable=True)
            self._last_exit_code = 2
            return False

        if not accessible:
            self._emit_error(
                "RESOURCE_NOT_FOUND",
                f"Repository {owner}/{repo} not found on GitHub.",
            )
            self._last_exit_code = 1
            return False

        return True

    def _verify_avos_access(self, memory_id: str, marker: str) -> bool:
        """Check Avos Memory API access and whether bootstrap note exists.

        Sets self._bootstrap_exists and self._last_exit_code.
        """
        try:
            result = self._memory.search(
                memory_id=memory_id,
                query=f"[type: {marker}]",
                k=1,
            )
            self._bootstrap_exists = bool(result.results)
            return True
        except AuthError as e:
            self._emit_error("AUTH_ERROR", f"Avos Memory: {e}")
            self._last_exit_code = 1
            return False
        except UpstreamUnavailableError as e:
            self._emit_error("UPSTREAM_UNAVAILABLE", f"Avos Memory: {e}", retryable=True)
            self._last_exit_code = 2
            return False

    def _send_bootstrap_note(
        self, memory_id: str, repo_slug: str, marker: str
    ) -> bool:
        """Send the bootstrap note to Avos Memory.

        Sets self._last_exit_code on failure.
        """
        content = (
            f"[type: {marker}]\n"
            f"Repository {repo_slug} connected to Avos Memory"
        )
        try:
            self._memory.add_memory(memory_id=memory_id, content=content)
            return True
        except UpstreamUnavailableError as e:
            self._emit_error(
                "UPSTREAM_UNAVAILABLE",
                f"Failed to store bootstrap note: {e}",
                retryable=True,
            )
            self._last_exit_code = 2
            return False
        except AvosError as e:
            self._emit_error(e.code, f"Failed to store bootstrap note: {e}")
            self._last_exit_code = 2
            return False

    def _write_config(self, repo_slug: str, memory_id: str) -> None:
        """Write .avos/config.json only if content would change.

        Preserves connected_at from existing config to guarantee
        strict idempotent rerun semantics (no observable mutation).
        """
        config_path = self._repo_root / ".avos" / "config.json"
        existing = read_json_safe(config_path) if config_path.exists() else None

        connected_at = datetime.now(tz=timezone.utc).isoformat()
        if (
            existing
            and existing.get("repo") == repo_slug
            and existing.get("memory_id") == memory_id
        ):
            connected_at = str(existing.get("connected_at", connected_at))

        new_data = {
            "repo": repo_slug,
            "memory_id": memory_id,
            "api_url": "",
            "api_key": "",
            "connected_at": connected_at,
            "schema_version": "2",
        }

        if existing is not None:
            existing_canonical = json.dumps(existing, indent=2, sort_keys=True)
            new_canonical = json.dumps(new_data, indent=2, sort_keys=True)
            if existing_canonical == new_canonical:
                return

        save_config(self._repo_root, new_data)

    def _auto_install_hook(self) -> bool:
        """Silently attempt to install pre-push hook after connect.

        This is best-effort: connect succeeds even if hook install fails.
        The hook enables automatic commit sync to Avos Memory on every
        git push, keeping team memory up-to-date without manual ingest.

        Returns:
            True if hook was installed or already exists, False otherwise.
        """
        from avos_cli.commands.hook_install import HookInstallOrchestrator

        hook_orch = HookInstallOrchestrator(
            git_client=self._git,
            repo_root=self._repo_root,
        )
        exit_code = hook_orch.run(force=False, quiet=True)
        if exit_code != 0:
            _log.debug("Hook auto-install skipped or failed (exit=%d)", exit_code)
            return False
        return True
