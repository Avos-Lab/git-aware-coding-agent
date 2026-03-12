"""Worktree-add command orchestrator.

Creates a git worktree, copies only config.json from the source,
automatically starts a session in the new worktree, and prints
collaboration hints. Follows the existing orchestrator pattern:
constructor DI, run() -> exit code.

Exit codes:
    0: success (worktree created, config copied, session started)
    1: precondition failure (no config, git error, session error)
"""

from __future__ import annotations

import shutil
import unicodedata
from pathlib import Path

from avos_cli.config.state import read_json_safe
from avos_cli.exceptions import AvosError, ServiceParseError
from avos_cli.services.git_client import GitClient
from avos_cli.services.memory_client import AvosMemoryClient
from avos_cli.utils.logger import get_logger
from avos_cli.utils.output import (
    print_error,
    print_info,
    print_warning,
    render_kv_panel,
)

_log = get_logger("commands.worktree_add")

_MAX_GOAL_LENGTH = 1000


class WorktreeAddOrchestrator:
    """Orchestrates the `avos worktree-add` command.

    Pipeline: validate source config -> git worktree add -> copy config.json ->
    start session in new worktree -> print collaboration hints.

    Args:
        git_client: Local git operations wrapper.
        memory_client: Avos Memory API client.
        repo_root: Path to the source repository root (must be connected).
    """

    def __init__(
        self,
        git_client: GitClient,
        memory_client: AvosMemoryClient,
        repo_root: Path,
    ) -> None:
        self._git = git_client
        self._memory = memory_client
        self._repo_root = repo_root
        self._avos_dir = repo_root / ".avos"

    def run(
        self, path: str, branch: str, goal: str, agent: str | None = None
    ) -> int:
        """Execute the worktree-add flow.

        Args:
            path: Filesystem path for the new worktree.
            branch: Branch name to create in the new worktree.
            goal: Session goal description for the new worktree.
            agent: Optional custom agent/developer name for the session.

        Returns:
            Exit code: 0 success, 1 precondition or session failure.
        """
        source_config_path = self._avos_dir / "config.json"
        if not source_config_path.exists():
            print_error(
                "[CONFIG_NOT_INITIALIZED] Source repository is not connected. "
                "Run 'avos connect org/repo' first."
            )
            return 1

        target_path = Path(path)
        try:
            worktree_root = self._git.worktree_add(
                self._repo_root, target_path, branch
            )
        except (ServiceParseError, AvosError) as e:
            print_error(f"[WORKTREE_ADD_FAILED] {e}")
            return 1

        target_avos = worktree_root / ".avos"
        target_avos.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(source_config_path), str(target_avos / "config.json"))

        sanitized_goal = self._sanitize_goal(goal)
        session_code, session_id = self._start_session(
            worktree_root, sanitized_goal, agent
        )

        if session_code != 0:
            print_warning(
                "Worktree created and config copied, but session start failed. "
                f"Run 'avos session-start \"{sanitized_goal}\"' manually in {worktree_root}."
            )
            return 1

        render_kv_panel(
            f"Worktree Created: {worktree_root}",
            [
                ("Branch", branch),
                ("Session", session_id or "unknown"),
                ("Goal", sanitized_goal),
            ],
            style="success",
        )
        return 0

    def _start_session(
        self, worktree_root: Path, goal: str, agent: str | None = None
    ) -> tuple[int, str | None]:
        """Start a session in the new worktree using SessionStartOrchestrator.

        Args:
            worktree_root: Root path of the new worktree.
            goal: Sanitized session goal text.
            agent: Optional custom agent/developer name.

        Returns:
            Tuple of (exit_code, session_id or None on failure).
        """
        from avos_cli.commands.session_start import SessionStartOrchestrator

        orch = SessionStartOrchestrator(
            git_client=self._git,
            memory_client=self._memory,
            repo_root=worktree_root,
        )
        code = orch.run(goal, agent=agent)
        if code != 0:
            return code, None

        session_data = read_json_safe(worktree_root / ".avos" / "session.json")
        session_id = (
            str(session_data.get("session_id", "unknown"))
            if session_data
            else "unknown"
        )
        return 0, session_id

    @staticmethod
    def _sanitize_goal(goal: str) -> str:
        """Sanitize user-provided goal text.

        Strips control characters and limits length.
        """
        cleaned = "".join(
            ch for ch in goal
            if unicodedata.category(ch)[0] != "C" or ch in ("\n", "\t")
        )
        return cleaned.strip()[:_MAX_GOAL_LENGTH]
