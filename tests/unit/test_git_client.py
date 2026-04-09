"""Tests for AVOS-006: Git client.

Uses real temporary git repos created via subprocess for fixture-based testing.
Covers commit log, branch detection, remote parsing, modified files, and error mapping.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from avos_cli.exceptions import RepositoryContextError
from avos_cli.services.git_client import GitClient


@pytest.fixture()
def git_repo(tmp_path: Path) -> Path:
    """Create a real temporary git repo with an initial commit."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=repo, capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=repo, capture_output=True, check=True,
    )
    # Create initial commit
    (repo / "README.md").write_text("# Test")
    subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "Initial commit"],
        cwd=repo, capture_output=True, check=True,
    )
    return repo


@pytest.fixture()
def client() -> GitClient:
    return GitClient()


class TestCurrentBranch:
    def test_returns_branch_name(self, git_repo: Path, client: GitClient):
        branch = client.current_branch(git_repo)
        assert branch in ("main", "master")

    def test_raises_on_non_repo(self, tmp_path: Path, client: GitClient):
        with pytest.raises(RepositoryContextError):
            client.current_branch(tmp_path)


class TestUserIdentity:
    def test_user_name(self, git_repo: Path, client: GitClient):
        name = client.user_name(git_repo)
        assert name == "Test User"

    def test_user_email(self, git_repo: Path, client: GitClient):
        email = client.user_email(git_repo)
        assert email == "test@example.com"


class TestCommitLog:
    def test_returns_commits(self, git_repo: Path, client: GitClient):
        commits = client.commit_log(git_repo)
        assert len(commits) >= 1
        assert commits[0]["message"] == "Initial commit"
        assert commits[0]["author"] == "Test User"
        assert "hash" in commits[0]
        assert "date" in commits[0]

    def test_with_multiple_commits(self, git_repo: Path, client: GitClient):
        (git_repo / "file2.py").write_text("print('hello')")
        subprocess.run(["git", "add", "."], cwd=git_repo, capture_output=True, check=True)
        subprocess.run(
            ["git", "commit", "-m", "Add file2"],
            cwd=git_repo, capture_output=True, check=True,
        )
        commits = client.commit_log(git_repo)
        assert len(commits) >= 2

    def test_with_since_date(self, git_repo: Path, client: GitClient):
        commits = client.commit_log(git_repo, since_date="2020-01-01")
        assert len(commits) >= 1

    def test_future_since_date_returns_empty(self, git_repo: Path, client: GitClient):
        commits = client.commit_log(git_repo, since_date="2099-01-01")
        assert len(commits) == 0


class TestModifiedFiles:
    def test_no_modifications(self, git_repo: Path, client: GitClient):
        files = client.modified_files(git_repo)
        assert files == []

    def test_with_modifications(self, git_repo: Path, client: GitClient):
        (git_repo / "README.md").write_text("# Modified")
        files = client.modified_files(git_repo)
        assert "README.md" in files

    def test_with_new_untracked_file(self, git_repo: Path, client: GitClient):
        (git_repo / "new.py").write_text("new file")
        files = client.modified_files(git_repo)
        assert "new.py" in files


class TestRemoteOrigin:
    def test_with_remote(self, git_repo: Path, client: GitClient):
        subprocess.run(
            ["git", "remote", "add", "origin", "https://github.com/org/repo.git"],
            cwd=git_repo, capture_output=True, check=True,
        )
        remote = client.remote_origin(git_repo)
        assert remote == "org/repo"

    def test_with_ssh_remote(self, git_repo: Path, client: GitClient):
        subprocess.run(
            ["git", "remote", "add", "origin", "git@github.com:org/repo.git"],
            cwd=git_repo, capture_output=True, check=True,
        )
        remote = client.remote_origin(git_repo)
        assert remote == "org/repo"

    def test_no_remote_returns_none(self, git_repo: Path, client: GitClient):
        remote = client.remote_origin(git_repo)
        assert remote is None


class TestDiffStats:
    def test_clean_repo(self, git_repo: Path, client: GitClient):
        stats = client.diff_stats(git_repo)
        assert stats == ""

    def test_with_changes(self, git_repo: Path, client: GitClient):
        (git_repo / "README.md").write_text("# Modified\nNew line")
        subprocess.run(["git", "add", "."], cwd=git_repo, capture_output=True, check=True)
        stats = client.diff_stats(git_repo)
        assert stats != ""


class TestIsWorktree:
    def test_normal_repo_is_not_worktree(self, git_repo: Path, client: GitClient):
        assert client.is_worktree(git_repo) is False


class TestCommitPatch:
    """Tests for commit_patch method."""

    def test_returns_unified_diff(self, git_repo: Path, client: GitClient):
        """Test that commit_patch returns a unified diff."""
        (git_repo / "file.py").write_text("def hello():\n    print('hello')\n")
        subprocess.run(["git", "add", "."], cwd=git_repo, capture_output=True, check=True)
        subprocess.run(
            ["git", "commit", "-m", "Add hello function"],
            cwd=git_repo, capture_output=True, check=True,
        )
        commits = client.commit_log(git_repo)
        sha = commits[0]["hash"]

        patch = client.commit_patch(git_repo, sha)
        assert "diff --git" in patch
        assert "file.py" in patch
        assert "+def hello():" in patch

    def test_with_short_sha(self, git_repo: Path, client: GitClient):
        """Test that commit_patch works with short SHA."""
        (git_repo / "file.py").write_text("content")
        subprocess.run(["git", "add", "."], cwd=git_repo, capture_output=True, check=True)
        subprocess.run(
            ["git", "commit", "-m", "Add file"],
            cwd=git_repo, capture_output=True, check=True,
        )
        commits = client.commit_log(git_repo)
        short_sha = commits[0]["hash"][:7]

        patch = client.commit_patch(git_repo, short_sha)
        assert "diff --git" in patch

    def test_initial_commit_diff(self, git_repo: Path, client: GitClient):
        """Test that initial commit (root) produces a valid diff."""
        commits = client.commit_log(git_repo)
        initial_sha = commits[-1]["hash"]

        patch = client.commit_patch(git_repo, initial_sha)
        assert "diff --git" in patch
        assert "README.md" in patch

    def test_invalid_sha_returns_empty(self, git_repo: Path, client: GitClient):
        """Test that invalid SHA returns empty string."""
        patch = client.commit_patch(git_repo, "0000000000000000000000000000000000000000")
        assert patch == ""

    def test_merge_commit_first_parent(self, git_repo: Path, client: GitClient):
        """Test that merge commits use first-parent diff."""
        subprocess.run(
            ["git", "checkout", "-b", "feature"],
            cwd=git_repo, capture_output=True, check=True,
        )
        (git_repo / "feature.py").write_text("feature code")
        subprocess.run(["git", "add", "."], cwd=git_repo, capture_output=True, check=True)
        subprocess.run(
            ["git", "commit", "-m", "Feature commit"],
            cwd=git_repo, capture_output=True, check=True,
        )

        subprocess.run(
            ["git", "checkout", "main"] if (git_repo / ".git" / "refs" / "heads" / "main").exists()
            else ["git", "checkout", "master"],
            cwd=git_repo, capture_output=True, check=True,
        )
        (git_repo / "main.py").write_text("main code")
        subprocess.run(["git", "add", "."], cwd=git_repo, capture_output=True, check=True)
        subprocess.run(
            ["git", "commit", "-m", "Main commit"],
            cwd=git_repo, capture_output=True, check=True,
        )

        subprocess.run(
            ["git", "merge", "feature", "--no-ff", "-m", "Merge feature"],
            cwd=git_repo, capture_output=True, check=True,
        )
        commits = client.commit_log(git_repo)
        merge_sha = commits[0]["hash"]

        patch = client.commit_patch(git_repo, merge_sha)
        assert "feature.py" in patch


class TestExpandShortSha:
    """Tests for expand_short_sha method."""

    def test_expands_short_sha(self, git_repo: Path, client: GitClient):
        """Test that short SHA is expanded to full 40-char SHA."""
        commits = client.commit_log(git_repo)
        full_sha = commits[0]["hash"]
        short_sha = full_sha[:7]

        expanded = client.expand_short_sha(git_repo, short_sha)
        assert expanded == full_sha
        assert len(expanded) == 40

    def test_full_sha_returns_same(self, git_repo: Path, client: GitClient):
        """Test that full SHA returns the same value."""
        commits = client.commit_log(git_repo)
        full_sha = commits[0]["hash"]

        expanded = client.expand_short_sha(git_repo, full_sha)
        assert expanded == full_sha

    def test_invalid_sha_returns_none(self, git_repo: Path, client: GitClient):
        """Test that invalid SHA returns None."""
        expanded = client.expand_short_sha(git_repo, "0000000")
        assert expanded is None

    def test_ambiguous_sha_returns_none(self, git_repo: Path, client: GitClient):
        """Test that ambiguous short SHA returns None.

        Note: This is hard to test reliably since we'd need many commits
        with colliding prefixes. We test the error handling path instead.
        """
        expanded = client.expand_short_sha(git_repo, "xyz")
        assert expanded is None

    def test_non_repo_raises(self, tmp_path: Path, client: GitClient):
        """Test that non-repo path raises RepositoryContextError."""
        with pytest.raises(RepositoryContextError):
            client.expand_short_sha(tmp_path, "abc1234")
