"""Local Git operations wrapper using subprocess.

Provides commit log, branch detection, diff stats, remote parsing,
modified file listing, and worktree detection. All commands use fixed
templates (no shell interpolation) for safety.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from avos_cli.exceptions import (
    DependencyUnavailableError,
    RepositoryContextError,
    ServiceParseError,
)
from avos_cli.utils.logger import get_logger

_log = get_logger("git_client")
_TIMEOUT = 30


class GitClient:
    """Wrapper for local Git CLI operations.

    All methods accept a repo_path and shell out to the git binary.
    Errors are normalized to typed exceptions.
    """

    def _run_git(self, args: list[str], cwd: Path) -> str:
        """Execute a git command and return stdout.

        Args:
            args: Git subcommand and arguments (e.g. ['log', '--oneline']).
            cwd: Working directory for the command.

        Returns:
            Stripped stdout string.

        Raises:
            DependencyUnavailableError: If git binary is not found.
            RepositoryContextError: If cwd is not a git repo.
            ServiceParseError: If the command fails unexpectedly.
        """
        cmd = ["git", *args]
        try:
            result = subprocess.run(
                cmd,
                cwd=str(cwd),
                capture_output=True,
                text=True,
                timeout=_TIMEOUT,
            )
        except FileNotFoundError as e:
            raise DependencyUnavailableError("git") from e
        except subprocess.TimeoutExpired as e:
            raise ServiceParseError(f"Git command timed out: {' '.join(cmd)}") from e

        if result.returncode != 0:
            stderr = result.stderr.strip()
            if "not a git repository" in stderr.lower():
                raise RepositoryContextError(f"Not a Git repository: {cwd}")
            if result.returncode != 0 and stderr:
                _log.debug("git stderr: %s", stderr)
            if result.returncode != 0 and not result.stdout.strip():
                return ""
        return result.stdout.rstrip("\n\r")

    def current_branch(self, repo_path: Path) -> str:
        """Get the current branch name.

        Args:
            repo_path: Path to the git repository.

        Returns:
            Branch name string (e.g. 'main', 'feature/foo').
        """
        output = self._run_git(["rev-parse", "--abbrev-ref", "HEAD"], repo_path)
        if not output:
            raise ServiceParseError("Could not determine current branch")
        return output

    def user_name(self, repo_path: Path) -> str:
        """Get the configured git user.name."""
        return self._run_git(["config", "user.name"], repo_path)

    def user_email(self, repo_path: Path) -> str:
        """Get the configured git user.email."""
        return self._run_git(["config", "user.email"], repo_path)

    def commit_log(
        self, repo_path: Path, since_date: str | None = None
    ) -> list[dict[str, str]]:
        """Get commit log as a list of dicts.

        Args:
            repo_path: Path to the git repository.
            since_date: Optional ISO date string for lower bound filter.

        Returns:
            List of dicts with keys: hash, message, author, date.
        """
        args = [
            "log",
            "--format=%H|%s|%an|%aI",
        ]
        if since_date:
            args.append(f"--since={since_date}")

        output = self._run_git(args, repo_path)
        if not output:
            return []

        commits: list[dict[str, str]] = []
        for line in output.splitlines():
            parts = line.split("|", 3)
            if len(parts) >= 4:
                commits.append({
                    "hash": parts[0],
                    "message": parts[1],
                    "author": parts[2],
                    "date": parts[3],
                })
        return commits

    def commit_log_range(
        self, repo_path: Path, old_sha: str, new_sha: str
    ) -> list[dict[str, str]]:
        """Get commits between two SHAs (exclusive old, inclusive new).

        Used by hook-sync to get commits being pushed. The range old_sha..new_sha
        returns commits reachable from new_sha but not from old_sha.

        Args:
            repo_path: Path to the git repository.
            old_sha: Base commit SHA (exclusive). Use empty string for new branches.
            new_sha: Target commit SHA (inclusive).

        Returns:
            List of dicts with keys: hash, message, author, date.
            Returns empty list if range is invalid or empty.
        """
        if not new_sha:
            return []

        range_spec = f"{old_sha}..{new_sha}" if old_sha else new_sha

        args = ["log", "--format=%H|%s|%an|%aI", range_spec]
        output = self._run_git(args, repo_path)
        if not output:
            return []

        commits: list[dict[str, str]] = []
        for line in output.splitlines():
            parts = line.split("|", 3)
            if len(parts) >= 4:
                commits.append({
                    "hash": parts[0],
                    "message": parts[1],
                    "author": parts[2],
                    "date": parts[3],
                })
        return commits

    def diff_stats(self, repo_path: Path) -> str:
        """Get diff stats for staged changes.

        Args:
            repo_path: Path to the git repository.

        Returns:
            Diff stat summary string, or empty string if clean.
        """
        return self._run_git(["diff", "--cached", "--stat"], repo_path)

    def modified_files(self, repo_path: Path) -> list[str]:
        """List files modified or untracked in the working directory.

        Args:
            repo_path: Path to the git repository.

        Returns:
            List of relative file paths.
        """
        output = self._run_git(
            ["status", "--porcelain", "--untracked-files=all"],
            repo_path,
        )
        if not output:
            return []

        files: list[str] = []
        for line in output.splitlines():
            # porcelain format: "XY filename" where XY is 2 status chars + 1 space
            if len(line) >= 4:
                path = line[3:]
                if " -> " in path:
                    path = path.split(" -> ", 1)[1]
                files.append(path)
        return files

    def remote_origin(self, repo_path: Path) -> str | None:
        """Extract org/repo from the origin remote URL.

        Handles both HTTPS and SSH remote formats.

        Args:
            repo_path: Path to the git repository.

        Returns:
            'org/repo' string, or None if no origin remote.
        """
        output = self._run_git(["remote", "get-url", "origin"], repo_path)
        if not output:
            return None
        return _parse_remote_url(output)

    def worktree_add(self, repo_path: Path, path: Path, branch: str) -> Path:
        """Create a new git worktree with a new branch.

        Runs `git worktree add -b <branch> <path>`. The branch is created
        from the current HEAD of repo_path.

        Args:
            repo_path: Path to the source git repository.
            path: Filesystem path for the new worktree.
            branch: Name of the new branch to create.

        Returns:
            Resolved Path to the created worktree directory.

        Raises:
            ServiceParseError: If git worktree add fails (path exists,
                branch already checked out, etc.).
            RepositoryContextError: If repo_path is not a git repo.
        """
        resolved = path.resolve()
        result = subprocess.run(
            ["git", "worktree", "add", "-b", branch, str(resolved)],
            cwd=str(repo_path),
            capture_output=True,
            text=True,
            timeout=_TIMEOUT,
        )
        if result.returncode != 0:
            stderr = result.stderr.strip()
            if "not a git repository" in stderr.lower():
                raise RepositoryContextError(f"Not a Git repository: {repo_path}")
            raise ServiceParseError(
                f"git worktree add failed: {stderr or 'unknown error'}"
            )
        return resolved

    def worktree_list(self, repo_path: Path) -> list[Path]:
        """List all worktree paths for the repository.

        Parses `git worktree list --porcelain` output where each worktree
        block starts with a `worktree <path>` line.

        Args:
            repo_path: Path to any worktree or the main repo.

        Returns:
            List of resolved Paths for all worktrees (including main).
        """
        output = self._run_git(["worktree", "list", "--porcelain"], repo_path)
        paths: list[Path] = []
        for line in output.splitlines():
            if line.startswith("worktree "):
                wt_path = line[len("worktree "):]
                paths.append(Path(wt_path).resolve())
        return paths

    def is_worktree(self, repo_path: Path) -> bool:
        """Check if the repo path is a git worktree (not the main repo).

        Args:
            repo_path: Path to check.

        Returns:
            True if the path is a worktree.
        """
        git_path = repo_path / ".git"
        return git_path.is_file()


def _parse_remote_url(url: str) -> str | None:
    """Extract org/repo from a git remote URL.

    Supports:
    - https://github.com/org/repo.git
    - git@github.com:org/repo.git
    - https://github.com/org/repo

    Args:
        url: Remote URL string.

    Returns:
        'org/repo' string or None if unparseable.
    """
    # SSH format: git@github.com:org/repo.git
    ssh_match = re.match(r"git@[^:]+:(.+?)(?:\.git)?$", url)
    if ssh_match:
        return ssh_match.group(1)

    # HTTPS format: https://github.com/org/repo.git
    https_match = re.match(r"https?://[^/]+/(.+?)(?:\.git)?$", url)
    if https_match:
        return https_match.group(1)

    return None
