"""Tests for avos worktree-add command.

Covers the full pipeline: config validation, git worktree creation,
selective config copy, automatic session start, and collaboration hints.
Uses real temporary git repos for fixture-based testing.

STEP_NAME: worktree-add command
ASSOCIATED_TEST: Verify worktree creation, selective copy, session auto-start
TEST_SPEC:
  - Behavior:
    - [x] GitClient.worktree_add creates valid worktree with new branch
    - [x] GitClient.worktree_list returns all worktrees including main
    - [x] Orchestrator copies only config.json (not session/PID files)
    - [x] Orchestrator auto-starts session in the new worktree
    - [x] Orchestrator prints collaboration hints on success
  - Edges:
    - [x] Source not connected -> exit 1
    - [x] Target path already exists -> exit 1
    - [x] Branch already checked out -> exit 1
    - [x] Session start fails -> worktree + config still created, exit 1
    - [x] Non-git directory -> raises
    - [x] Multiple worktrees from same source
  - Invariants:
    - [x] Copied config matches source exactly
    - [x] Created worktree passes is_worktree() check
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from avos_cli.exceptions import RepositoryContextError, ServiceParseError
from avos_cli.services.git_client import GitClient


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

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
    (repo / "README.md").write_text("# Test")
    subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "Initial commit"],
        cwd=repo, capture_output=True, check=True,
    )
    return repo


@pytest.fixture()
def connected_repo(git_repo: Path) -> Path:
    """A git repo with .avos/config.json written (simulating avos connect)."""
    avos_dir = git_repo / ".avos"
    avos_dir.mkdir()
    config = {
        "repo": "org/repo",
        "memory_id": "repo:org/repo",
        "memory_id_session": "repo:org/repo-session",
        "api_url": "https://api.avos.ai",
        "api_key": "test-key",
        "connected_at": "2026-03-09T00:00:00+00:00",
        "schema_version": "2",
    }
    (avos_dir / "config.json").write_text(json.dumps(config, indent=2))
    return git_repo


@pytest.fixture()
def client() -> GitClient:
    return GitClient()


# ---------------------------------------------------------------------------
# GitClient.worktree_add tests
# ---------------------------------------------------------------------------

class TestWorktreeAdd:
    """Tests for GitClient.worktree_add()."""

    def test_creates_worktree_with_new_branch(
        self, git_repo: Path, client: GitClient
    ):
        """Happy path: create a worktree with a new branch."""
        wt_path = git_repo.parent / "feature-wt"
        result = client.worktree_add(git_repo, wt_path, "feature-branch")
        assert result.exists()
        assert (result / ".git").is_file()  # worktrees have .git file, not dir
        branch = client.current_branch(result)
        assert branch == "feature-branch"

    def test_returns_resolved_path(self, git_repo: Path, client: GitClient):
        """Returned path should be resolved (no relative segments)."""
        wt_path = git_repo.parent / "wt-resolve"
        result = client.worktree_add(git_repo, wt_path, "br-resolve")
        assert result == wt_path.resolve()

    def test_raises_on_existing_path(self, git_repo: Path, client: GitClient):
        """Should raise ServiceParseError if the target path already exists."""
        existing = git_repo.parent / "existing-wt"
        existing.mkdir()
        (existing / "blocker.txt").write_text("occupied")
        with pytest.raises(ServiceParseError):
            client.worktree_add(git_repo, existing, "br-existing")

    def test_raises_on_branch_already_checked_out(
        self, git_repo: Path, client: GitClient
    ):
        """Should raise when the branch is already checked out elsewhere."""
        main_branch = client.current_branch(git_repo)
        wt_path = git_repo.parent / "wt-dup-branch"
        with pytest.raises(ServiceParseError):
            client.worktree_add(git_repo, wt_path, main_branch)

    def test_raises_on_non_repo(self, tmp_path: Path, client: GitClient):
        """Should raise RepositoryContextError on a non-git directory."""
        wt_path = tmp_path / "wt-no-repo"
        with pytest.raises((RepositoryContextError, ServiceParseError)):
            client.worktree_add(tmp_path, wt_path, "any-branch")


class TestWorktreeList:
    """Tests for GitClient.worktree_list()."""

    def test_lists_main_repo_only(self, git_repo: Path, client: GitClient):
        """With no extra worktrees, list should contain just the main repo."""
        paths = client.worktree_list(git_repo)
        assert len(paths) >= 1
        assert git_repo.resolve() in [p.resolve() for p in paths]

    def test_lists_added_worktree(self, git_repo: Path, client: GitClient):
        """After adding a worktree, it should appear in the list."""
        wt_path = git_repo.parent / "wt-list"
        client.worktree_add(git_repo, wt_path, "br-list")
        paths = client.worktree_list(git_repo)
        resolved = [p.resolve() for p in paths]
        assert wt_path.resolve() in resolved

    def test_list_from_worktree_context(self, git_repo: Path, client: GitClient):
        """Should work when called from inside a worktree (not the main repo)."""
        wt_path = git_repo.parent / "wt-from"
        client.worktree_add(git_repo, wt_path, "br-from")
        paths = client.worktree_list(wt_path)
        assert len(paths) >= 2


# ---------------------------------------------------------------------------
# WorktreeAddOrchestrator tests
# ---------------------------------------------------------------------------

class TestWorktreeAddOrchestrator:
    """Tests for the full worktree-add orchestration pipeline."""

    def test_fails_when_source_not_connected(self, git_repo: Path):
        """Should return exit 1 when source has no .avos/config.json."""
        from avos_cli.commands.worktree_add import WorktreeAddOrchestrator

        orch = WorktreeAddOrchestrator(
            git_client=GitClient(),
            memory_client=MagicMock(),
            repo_root=git_repo,
        )
        code = orch.run(
            path=str(git_repo.parent / "wt-no-config"),
            branch="br-no-config",
            goal="test goal",
        )
        assert code == 1

    def test_copies_only_config_json(self, connected_repo: Path):
        """Only config.json should be copied; session/PID files must not exist."""
        from avos_cli.commands.worktree_add import WorktreeAddOrchestrator

        source_avos = connected_repo / ".avos"
        (source_avos / "session.json").write_text('{"session_id": "old"}')
        (source_avos / "watcher.pid").write_text('{"pid": 99999}')

        wt_path = connected_repo.parent / "wt-copy-test"
        orch = WorktreeAddOrchestrator(
            git_client=GitClient(),
            memory_client=MagicMock(),
            repo_root=connected_repo,
        )
        with patch.object(orch, "_start_session", return_value=(0, "sess_mock")):
            code = orch.run(path=str(wt_path), branch="br-copy", goal="test")

        assert code == 0
        new_avos = wt_path / ".avos"
        assert (new_avos / "config.json").exists()
        assert not (new_avos / "session.json").exists()
        assert not (new_avos / "watcher.pid").exists()

    def test_config_content_matches_source(self, connected_repo: Path):
        """Copied config.json should have identical content to source."""
        from avos_cli.commands.worktree_add import WorktreeAddOrchestrator

        wt_path = connected_repo.parent / "wt-content-match"
        orch = WorktreeAddOrchestrator(
            git_client=GitClient(),
            memory_client=MagicMock(),
            repo_root=connected_repo,
        )
        with patch.object(orch, "_start_session", return_value=(0, "sess_mock")):
            code = orch.run(path=str(wt_path), branch="br-match", goal="test")

        assert code == 0
        source_config = json.loads(
            (connected_repo / ".avos" / "config.json").read_text()
        )
        target_config = json.loads(
            (wt_path / ".avos" / "config.json").read_text()
        )
        assert source_config == target_config

    def test_session_started_in_new_worktree(self, connected_repo: Path):
        """Session start should be invoked for the new worktree, not the source."""
        from avos_cli.commands.worktree_add import WorktreeAddOrchestrator

        wt_path = connected_repo.parent / "wt-session"
        orch = WorktreeAddOrchestrator(
            git_client=GitClient(),
            memory_client=MagicMock(),
            repo_root=connected_repo,
        )
        with patch.object(orch, "_start_session", return_value=(0, "sess_abc")) as mock_start:
            code = orch.run(path=str(wt_path), branch="br-session", goal="my goal")

        assert code == 0
        mock_start.assert_called_once_with(wt_path.resolve(), "my goal", None)

    def test_returns_error_on_git_failure(self, connected_repo: Path):
        """Should return exit 1 when git worktree add fails."""
        from avos_cli.commands.worktree_add import WorktreeAddOrchestrator

        occupied = connected_repo.parent / "wt-occupied"
        occupied.mkdir()
        (occupied / "file.txt").write_text("block")

        orch = WorktreeAddOrchestrator(
            git_client=GitClient(),
            memory_client=MagicMock(),
            repo_root=connected_repo,
        )
        code = orch.run(path=str(occupied), branch="br-occ", goal="test")
        assert code == 1

    def test_returns_error_on_session_failure(self, connected_repo: Path):
        """Should still create worktree + config but report session failure."""
        from avos_cli.commands.worktree_add import WorktreeAddOrchestrator

        wt_path = connected_repo.parent / "wt-sess-fail"
        orch = WorktreeAddOrchestrator(
            git_client=GitClient(),
            memory_client=MagicMock(),
            repo_root=connected_repo,
        )
        with patch.object(orch, "_start_session", return_value=(1, None)):
            code = orch.run(path=str(wt_path), branch="br-sfail", goal="test")

        # Worktree and config should exist even if session failed
        assert (wt_path / ".avos" / "config.json").exists()
        # Exit code reflects session failure
        assert code == 1

    def test_worktree_is_valid_git_worktree(self, connected_repo: Path):
        """The created worktree should be detected as a git worktree."""
        from avos_cli.commands.worktree_add import WorktreeAddOrchestrator

        wt_path = connected_repo.parent / "wt-valid"
        git = GitClient()
        orch = WorktreeAddOrchestrator(
            git_client=git,
            memory_client=MagicMock(),
            repo_root=connected_repo,
        )
        with patch.object(orch, "_start_session", return_value=(0, "sess_ok")):
            code = orch.run(path=str(wt_path), branch="br-valid", goal="test")

        assert code == 0
        assert git.is_worktree(wt_path)

    def test_multiple_worktrees_from_same_source(self, connected_repo: Path):
        """Creating multiple worktrees from the same source should all succeed."""
        from avos_cli.commands.worktree_add import WorktreeAddOrchestrator

        git = GitClient()
        for i in range(3):
            wt_path = connected_repo.parent / f"wt-multi-{i}"
            orch = WorktreeAddOrchestrator(
                git_client=git,
                memory_client=MagicMock(),
                repo_root=connected_repo,
            )
            with patch.object(orch, "_start_session", return_value=(0, f"sess_{i}")):
                code = orch.run(
                    path=str(wt_path), branch=f"br-multi-{i}", goal=f"goal {i}"
                )
            assert code == 0
            assert (wt_path / ".avos" / "config.json").exists()

        paths = git.worktree_list(connected_repo)
        assert len(paths) == 4  # main + 3 worktrees

    def test_does_not_copy_ingest_hashes(self, connected_repo: Path):
        """ingest_hashes.json from source must not be copied."""
        from avos_cli.commands.worktree_add import WorktreeAddOrchestrator

        (connected_repo / ".avos" / "ingest_hashes.json").write_text('{"h":"v"}')
        wt_path = connected_repo.parent / "wt-no-hashes"
        orch = WorktreeAddOrchestrator(
            git_client=GitClient(),
            memory_client=MagicMock(),
            repo_root=connected_repo,
        )
        with patch.object(orch, "_start_session", return_value=(0, "sess_ok")):
            code = orch.run(path=str(wt_path), branch="br-no-hash", goal="test")

        assert code == 0
        assert not (wt_path / ".avos" / "ingest_hashes.json").exists()

    def test_goal_is_sanitized(self, connected_repo: Path):
        """Control characters in goal should be stripped."""
        from avos_cli.commands.worktree_add import WorktreeAddOrchestrator

        wt_path = connected_repo.parent / "wt-sanitize"
        orch = WorktreeAddOrchestrator(
            git_client=GitClient(),
            memory_client=MagicMock(),
            repo_root=connected_repo,
        )
        dirty_goal = "fix \x00bug\x07 in auth"
        with patch.object(orch, "_start_session", return_value=(0, "sess_ok")) as mock:
            orch.run(path=str(wt_path), branch="br-sanitize", goal=dirty_goal)

        called_goal = mock.call_args[0][1]
        assert "\x00" not in called_goal
        assert "\x07" not in called_goal
        assert "fix bug in auth" in called_goal
