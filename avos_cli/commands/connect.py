"""Connect command orchestrator for AVOS CLI.

Implements the `avos connect org/repo` flow: validates Git repo,
verifies GitHub access, creates bootstrap note in Avos Memory,
and writes .avos/config.json.
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
from avos_cli.utils.output import print_error, print_info, print_json, print_success, render_kv_panel

_log = get_logger("commands.connect")

_BOOTSTRAP_MARKER = "repo_connected"
_SESSION_BOOTSTRAP_MARKER = "session_connected"


class ConnectOrchestrator:
    """Orchestrates the `avos connect` command.

    Precondition order (per Q7): Git repo -> remote parseable ->
    GitHub API accessible -> Avos API accessible -> write config.

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

    def run(self, repo_slug: str, json_output: bool = False) -> int:
        """Execute the connect flow.

        Args:
            repo_slug: Repository identifier in 'org/repo' format.
            json_output: If True, emit JSON output instead of human UI.

        Returns:
            Exit code: 0=success, 1=local precondition, 2=hard external.
        """
        self._json_output = json_output

        if not self._validate_slug(repo_slug):
            self._emit_error("REPOSITORY_CONTEXT_ERROR", "Invalid repo slug format. Expected 'org/repo'.")
            return 1

        owner, repo = repo_slug.split("/", 1)

        if not self._verify_git_remote(repo_slug):
            return 1

        if not self._verify_github_access(owner, repo):
            return self._last_exit_code

        memory_id = f"repo:{repo_slug}"
        memory_id_session = f"repo:{repo_slug}-session"

        if not self._verify_avos_access(memory_id, _BOOTSTRAP_MARKER):
            return self._last_exit_code

        if not self._bootstrap_exists and not self._send_bootstrap_note(
            memory_id, repo_slug, _BOOTSTRAP_MARKER
        ):
            return self._last_exit_code

        if not self._verify_avos_access(memory_id_session, _SESSION_BOOTSTRAP_MARKER):
            return self._last_exit_code

        if not self._bootstrap_exists and not self._send_bootstrap_note(
            memory_id_session, repo_slug, _SESSION_BOOTSTRAP_MARKER
        ):
            return self._last_exit_code

        self._write_config(repo_slug, memory_id, memory_id_session)

        config_path = str(self._repo_root / ".avos" / "config.json")
        if json_output:
            print_json(
                success=True,
                data={
                    "repo": repo_slug,
                    "memory_id": memory_id,
                    "memory_id_session": memory_id_session,
                    "config_path": config_path,
                },
                error=None,
            )
        else:
            render_kv_panel(
                f"Connected to {repo_slug}",
                [
                    ("Memory A (past)", memory_id),
                    ("Memory B (session)", memory_id_session),
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

    def _write_config(
        self, repo_slug: str, memory_id: str, memory_id_session: str
    ) -> None:
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
            and existing.get("memory_id_session") == memory_id_session
        ):
            connected_at = str(existing.get("connected_at", connected_at))

        new_data = {
            "repo": repo_slug,
            "memory_id": memory_id,
            "memory_id_session": memory_id_session,
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
