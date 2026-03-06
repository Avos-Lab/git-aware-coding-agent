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
