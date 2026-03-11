"""Worktree-init command orchestrator.

Initializes avos in an existing git worktree by copying config.json
from a sibling worktree. Only works inside a worktree (not the main
repo). Follows the existing orchestrator pattern: constructor DI,
run() -> exit code.

Exit codes:
    0: success (config copied from sibling)
    1: precondition failure (not a worktree, config exists, no sibling)
"""

from __future__ import annotations

import shutil
from pathlib import Path

from avos_cli.services.git_client import GitClient
from avos_cli.utils.logger import get_logger
from avos_cli.utils.output import (
    print_error,
    print_info,
    render_kv_panel,
)

_log = get_logger("commands.worktree_init")


class WorktreeInitOrchestrator:
    """Orchestrates the `avos worktree-init` command.

    Pipeline: verify worktree -> check no config -> find sibling config ->
    copy config.json only -> print hints.

    Args:
        git_client: Local git operations wrapper.
        repo_root: Path to the current worktree root.
    """

    def __init__(
        self,
        git_client: GitClient,
        repo_root: Path,
    ) -> None:
        self._git = git_client
        self._repo_root = repo_root
        self._avos_dir = repo_root / ".avos"

    def run(self) -> int:
        """Execute the worktree-init flow.

        Returns:
            Exit code: 0 success, 1 precondition failure.
        """
        if not self._git.is_worktree(self._repo_root):
            print_error(
                "[WORKTREE_REQUIRED] This command only works inside a git worktree. "
                "Use 'avos connect org/repo' in the main repository."
            )
            return 1

        config_path = self._avos_dir / "config.json"
        if config_path.exists():
            print_error(
                "[ALREADY_INITIALIZED] This worktree already has .avos/config.json. "
                "No action needed."
            )
            return 1

        sibling_config = self._find_sibling_config()
        if sibling_config is None:
            print_error(
                "[NO_SIBLING_CONFIG] No sibling worktree has .avos/config.json. "
                "Run 'avos connect org/repo' in the main repository first."
            )
            return 1

        self._avos_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(sibling_config), str(config_path))

        render_kv_panel(
            "Worktree Initialized",
            [
                ("Config from", str(sibling_config.parent.parent)),
                ("Ready", "All avos commands are now available"),
            ],
            style="success",
        )
        print_info("Next steps:")
        print_info("  avos session-start \"your goal\"  - Start a session")
        print_info("  avos team                       - See active team members")
        print_info("  avos watch                      - Publish WIP activity")

        return 0

    def _find_sibling_config(self) -> Path | None:
        """Search sibling worktrees for one that has .avos/config.json.

        Skips the current worktree. Returns the first config.json found.

        Returns:
            Path to the sibling's config.json, or None if not found.
        """
        current_resolved = self._repo_root.resolve()
        try:
            worktrees = self._git.worktree_list(self._repo_root)
        except Exception:
            _log.warning("Failed to list worktrees", exc_info=True)
            return None

        for wt_path in worktrees:
            if wt_path.resolve() == current_resolved:
                continue
            candidate = wt_path / ".avos" / "config.json"
            if candidate.exists():
                return candidate

        return None
