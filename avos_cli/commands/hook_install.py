"""Hook install command for setting up automatic commit sync on git push.

Installs a pre-push git hook that automatically syncs pushed commits
to Avos Memory. This enables real-time team synchronization without
requiring manual `avos ingest` runs.
"""

from __future__ import annotations

import stat
from pathlib import Path

from avos_cli.config.manager import load_config
from avos_cli.exceptions import (
    AvosError,
    ConfigurationNotInitializedError,
)
from avos_cli.services.git_client import GitClient
from avos_cli.utils.logger import get_logger
from avos_cli.utils.output import print_error, print_info, print_success, print_warning

_log = get_logger("commands.hook_install")

_PRE_PUSH_HOOK_SCRIPT = """\
#!/bin/sh
# =============================================================================
# Avos Memory Auto-Sync Hook
# =============================================================================
# Installed by: avos hook-install
# Purpose: Automatically sync pushed commits to Avos Memory
#
# This hook runs before git push and extracts commits being pushed,
# then inserts them into Avos Memory for team synchronization.
#
# To uninstall: rm .git/hooks/pre-push
# =============================================================================

remote="$1"
url="$2"

# Read refs from stdin (format: local_ref local_sha remote_ref remote_sha)
while read local_ref local_sha remote_ref remote_sha; do
    # Skip if deleting a ref (local_sha is null)
    if [ "$local_sha" = "0000000000000000000000000000000000000000" ]; then
        continue
    fi

    # For new branches, remote_sha is null - use empty string
    if [ "$remote_sha" = "0000000000000000000000000000000000000000" ]; then
        remote_sha=""
    fi

    # Sync commits to Avos Memory (never blocks push)
    avos hook-sync "$remote_sha" "$local_sha" 2>&1 || true
done

# Always allow push to proceed
exit 0
"""


class HookInstallOrchestrator:
    """Orchestrates installation of the pre-push git hook.

    The hook enables automatic commit sync to Avos Memory on every
    git push, allowing team members to see each other's work in
    real-time via `avos ask` and `avos history`.

    Args:
        git_client: Local git operations wrapper.
        repo_root: Path to the repository root.
    """

    def __init__(self, git_client: GitClient, repo_root: Path) -> None:
        self._git = git_client
        self._repo_root = repo_root

    def run(self, force: bool = False, quiet: bool = False) -> int:
        """Install the pre-push hook for automatic commit sync.

        Args:
            force: If True, overwrite existing hook without prompting.
            quiet: If True, suppress all output (for auto-install from connect).

        Returns:
            Exit code: 0 on success, 1 on failure.
        """
        try:
            config = load_config(self._repo_root)
        except ConfigurationNotInitializedError:
            if not quiet:
                print_error(
                    "[CONFIG_NOT_INITIALIZED] Repository not connected. "
                    "Run 'avos connect org/repo' first."
                )
            return 1
        except AvosError as e:
            if not quiet:
                print_error(f"[{e.code}] {e}")
            return 1

        hooks_dir = self._get_hooks_dir()
        if hooks_dir is None:
            if not quiet:
                print_error("[REPOSITORY_CONTEXT_ERROR] Could not locate .git/hooks directory.")
            return 1

        hook_path = hooks_dir / "pre-push"

        if hook_path.exists() and not force:
            if self._is_avos_hook(hook_path):
                if not quiet:
                    print_info("Avos pre-push hook is already installed.")
                return 0
            else:
                if not quiet:
                    print_warning(
                        "A pre-push hook already exists and was not installed by avos.\n"
                        "Use --force to overwrite, or manually integrate avos hook-sync."
                    )
                _log.debug("Existing non-avos hook found, skipping auto-install")
                return 1

        try:
            self._install_hook(hook_path)
        except OSError as e:
            if not quiet:
                print_error(f"[HOOK_INSTALL_ERROR] Failed to install hook: {e}")
            return 1

        if not quiet:
            print_success(f"Installed pre-push hook: {hook_path}")
            print_info(
                "Commits will now auto-sync to Avos Memory on every git push.\n"
                f"Connected to memory: {config.memory_id}"
            )
        else:
            _log.debug("Auto-installed pre-push hook at %s", hook_path)
        return 0

    def _get_hooks_dir(self) -> Path | None:
        """Get the path to the git hooks directory.

        Handles both regular repos (.git/hooks) and worktrees.

        Returns:
            Path to hooks directory, or None if not found.
        """
        git_path = self._repo_root / ".git"

        if git_path.is_dir():
            hooks_dir = git_path / "hooks"
            hooks_dir.mkdir(exist_ok=True)
            return hooks_dir

        if git_path.is_file():
            try:
                content = git_path.read_text().strip()
                if content.startswith("gitdir:"):
                    gitdir = content[7:].strip()
                    gitdir_path = Path(gitdir)
                    if not gitdir_path.is_absolute():
                        gitdir_path = (self._repo_root / gitdir_path).resolve()
                    hooks_dir = gitdir_path / "hooks"
                    hooks_dir.mkdir(exist_ok=True)
                    return hooks_dir
            except (OSError, ValueError):
                pass

        return None

    def _is_avos_hook(self, hook_path: Path) -> bool:
        """Check if an existing hook was installed by avos.

        Args:
            hook_path: Path to the hook file.

        Returns:
            True if the hook contains avos signature.
        """
        try:
            content = hook_path.read_text()
            return "avos hook-sync" in content or "Avos Memory Auto-Sync" in content
        except OSError:
            return False

    def _install_hook(self, hook_path: Path) -> None:
        """Write the pre-push hook script and make it executable.

        Args:
            hook_path: Path where the hook should be installed.

        Raises:
            OSError: If writing or chmod fails.
        """
        hook_path.write_text(_PRE_PUSH_HOOK_SCRIPT)
        hook_path.chmod(hook_path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        _log.info("Installed pre-push hook at %s", hook_path)


class HookUninstallOrchestrator:
    """Orchestrates removal of the pre-push git hook.

    Args:
        repo_root: Path to the repository root.
    """

    def __init__(self, repo_root: Path) -> None:
        self._repo_root = repo_root

    def run(self) -> int:
        """Remove the avos pre-push hook if it exists.

        Returns:
            Exit code: 0 on success, 1 if hook wasn't avos-installed.
        """
        git_path = self._repo_root / ".git"
        if git_path.is_dir():
            hook_path = git_path / "hooks" / "pre-push"
        elif git_path.is_file():
            try:
                content = git_path.read_text().strip()
                if content.startswith("gitdir:"):
                    gitdir = content[7:].strip()
                    gitdir_path = Path(gitdir)
                    if not gitdir_path.is_absolute():
                        gitdir_path = (self._repo_root / gitdir_path).resolve()
                    hook_path = gitdir_path / "hooks" / "pre-push"
                else:
                    print_error("[REPOSITORY_CONTEXT_ERROR] Invalid .git file format.")
                    return 1
            except OSError:
                print_error("[REPOSITORY_CONTEXT_ERROR] Could not read .git file.")
                return 1
        else:
            print_error("[REPOSITORY_CONTEXT_ERROR] No .git found.")
            return 1

        if not hook_path.exists():
            print_info("No pre-push hook installed.")
            return 0

        try:
            content = hook_path.read_text()
            if "avos hook-sync" not in content and "Avos Memory Auto-Sync" not in content:
                print_warning(
                    "The existing pre-push hook was not installed by avos.\n"
                    "Remove it manually if needed."
                )
                return 1
        except OSError:
            pass

        try:
            hook_path.unlink()
            print_success("Removed avos pre-push hook.")
            return 0
        except OSError as e:
            print_error(f"[HOOK_UNINSTALL_ERROR] Failed to remove hook: {e}")
            return 1
