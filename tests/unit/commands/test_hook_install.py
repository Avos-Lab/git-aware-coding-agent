"""Tests for HookInstallOrchestrator and HookUninstallOrchestrator.

Covers hook installation, force overwrite, existing hook detection,
worktree support, and uninstallation.
"""

from __future__ import annotations

import json
import stat
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from avos_cli.commands.hook_install import (
    _PRE_PUSH_HOOK_SCRIPT,
    HookInstallOrchestrator,
    HookUninstallOrchestrator,
)
from avos_cli.exceptions import RepositoryContextError


def _make_config_json(
    avos_dir: Path,
    repo: str = "myorg/myrepo",
    memory_id: str = "repo:myorg/myrepo",
) -> None:
    """Write a minimal valid config.json for tests."""
    avos_dir.mkdir(parents=True, exist_ok=True)
    config = {
        "repo": repo,
        "memory_id": memory_id,
        "memory_id_session": f"{memory_id}-session",
        "api_url": "https://api.avos.ai",
        "api_key": "sk_test",
        "schema_version": "2",
    }
    (avos_dir / "config.json").write_text(json.dumps(config))


@pytest.fixture()
def git_repo(tmp_path: Path) -> Path:
    """Create a minimal git repo structure with avos config."""
    repo = tmp_path / "repo"
    repo.mkdir()
    git_dir = repo / ".git"
    git_dir.mkdir()
    (git_dir / "hooks").mkdir()
    avos = repo / ".avos"
    _make_config_json(avos)
    return repo


@pytest.fixture()
def mock_git_client() -> MagicMock:
    """Mock git client."""
    return MagicMock()


@pytest.fixture()
def orchestrator(git_repo: Path, mock_git_client: MagicMock) -> HookInstallOrchestrator:
    """Create orchestrator with mocked dependencies."""
    return HookInstallOrchestrator(
        git_client=mock_git_client,
        repo_root=git_repo,
    )


class TestHookInstallHappyPath:
    """Hook installation succeeds under normal conditions."""

    def test_installs_hook_returns_0(self, orchestrator: HookInstallOrchestrator):
        code = orchestrator.run()
        assert code == 0

    def test_creates_pre_push_hook_file(self, orchestrator: HookInstallOrchestrator, git_repo: Path):
        orchestrator.run()
        hook_path = git_repo / ".git" / "hooks" / "pre-push"
        assert hook_path.exists()

    def test_hook_content_contains_avos_sync(self, orchestrator: HookInstallOrchestrator, git_repo: Path):
        orchestrator.run()
        hook_path = git_repo / ".git" / "hooks" / "pre-push"
        content = hook_path.read_text()
        assert "avos hook-sync" in content

    def test_hook_is_executable(self, orchestrator: HookInstallOrchestrator, git_repo: Path):
        orchestrator.run()
        hook_path = git_repo / ".git" / "hooks" / "pre-push"
        mode = hook_path.stat().st_mode
        assert mode & stat.S_IXUSR

    def test_hook_has_shebang(self, orchestrator: HookInstallOrchestrator, git_repo: Path):
        orchestrator.run()
        hook_path = git_repo / ".git" / "hooks" / "pre-push"
        content = hook_path.read_text()
        assert content.startswith("#!/bin/sh")

    def test_hook_never_blocks_push(self, orchestrator: HookInstallOrchestrator, git_repo: Path):
        """Hook script should always exit 0."""
        orchestrator.run()
        hook_path = git_repo / ".git" / "hooks" / "pre-push"
        content = hook_path.read_text()
        assert "exit 0" in content
        assert "|| true" in content


class TestExistingHookHandling:
    """Handles existing hooks correctly."""

    def test_avos_hook_already_installed_returns_0(
        self, orchestrator: HookInstallOrchestrator, git_repo: Path
    ):
        """If avos hook exists, return success without rewriting."""
        hook_path = git_repo / ".git" / "hooks" / "pre-push"
        hook_path.write_text(_PRE_PUSH_HOOK_SCRIPT)

        code = orchestrator.run()
        assert code == 0

    def test_non_avos_hook_returns_1(
        self, orchestrator: HookInstallOrchestrator, git_repo: Path
    ):
        """Non-avos hook should not be overwritten without --force."""
        hook_path = git_repo / ".git" / "hooks" / "pre-push"
        hook_path.write_text("#!/bin/sh\necho 'custom hook'\n")

        code = orchestrator.run()
        assert code == 1

    def test_force_overwrites_non_avos_hook(
        self, orchestrator: HookInstallOrchestrator, git_repo: Path
    ):
        """--force should overwrite existing non-avos hook."""
        hook_path = git_repo / ".git" / "hooks" / "pre-push"
        hook_path.write_text("#!/bin/sh\necho 'custom hook'\n")

        code = orchestrator.run(force=True)
        assert code == 0
        assert "avos hook-sync" in hook_path.read_text()

    def test_force_overwrites_avos_hook(
        self, orchestrator: HookInstallOrchestrator, git_repo: Path
    ):
        """--force should also work on existing avos hook (reinstall)."""
        hook_path = git_repo / ".git" / "hooks" / "pre-push"
        hook_path.write_text("#!/bin/sh\n# old avos hook-sync version\n")

        code = orchestrator.run(force=True)
        assert code == 0


class TestNoConfig:
    """Handles missing avos config."""

    def test_no_config_returns_1(self, tmp_path: Path, mock_git_client: MagicMock):
        """Should fail when no avos config exists."""
        repo = tmp_path / "no_config_repo"
        repo.mkdir()
        (repo / ".git").mkdir()
        (repo / ".git" / "hooks").mkdir()

        orch = HookInstallOrchestrator(
            git_client=mock_git_client,
            repo_root=repo,
        )
        code = orch.run()
        assert code == 1


class TestWorktreeSupport:
    """Handles git worktrees correctly."""

    def test_worktree_installs_hook_in_gitdir(self, tmp_path: Path, mock_git_client: MagicMock):
        """Worktree should install hook in the gitdir location."""
        main_repo = tmp_path / "main"
        main_repo.mkdir()
        main_git = main_repo / ".git"
        main_git.mkdir()

        worktree = tmp_path / "worktree"
        worktree.mkdir()
        worktree_gitdir = main_git / "worktrees" / "worktree"
        worktree_gitdir.mkdir(parents=True)
        (worktree_gitdir / "hooks").mkdir()

        (worktree / ".git").write_text(f"gitdir: {worktree_gitdir}")

        avos = worktree / ".avos"
        _make_config_json(avos)

        orch = HookInstallOrchestrator(
            git_client=mock_git_client,
            repo_root=worktree,
        )
        code = orch.run()

        assert code == 0
        hook_path = worktree_gitdir / "hooks" / "pre-push"
        assert hook_path.exists()
        assert "avos hook-sync" in hook_path.read_text()


class TestHookUninstall:
    """HookUninstallOrchestrator tests."""

    def test_removes_avos_hook(self, git_repo: Path):
        """Should remove avos-installed hook."""
        hook_path = git_repo / ".git" / "hooks" / "pre-push"
        hook_path.write_text(_PRE_PUSH_HOOK_SCRIPT)

        orch = HookUninstallOrchestrator(repo_root=git_repo)
        code = orch.run()

        assert code == 0
        assert not hook_path.exists()

    def test_no_hook_returns_0(self, git_repo: Path):
        """Should succeed when no hook exists."""
        orch = HookUninstallOrchestrator(repo_root=git_repo)
        code = orch.run()
        assert code == 0

    def test_non_avos_hook_returns_1(self, git_repo: Path):
        """Should not remove non-avos hook."""
        hook_path = git_repo / ".git" / "hooks" / "pre-push"
        hook_path.write_text("#!/bin/sh\necho 'custom'\n")

        orch = HookUninstallOrchestrator(repo_root=git_repo)
        code = orch.run()

        assert code == 1
        assert hook_path.exists()


class TestHookScriptContent:
    """Verify hook script content is correct."""

    def test_script_handles_null_sha(self):
        """Script should handle null SHA (40 zeros) for new branches."""
        assert "0000000000000000000000000000000000000000" in _PRE_PUSH_HOOK_SCRIPT

    def test_script_reads_stdin(self):
        """Script should read refs from stdin."""
        assert "while read" in _PRE_PUSH_HOOK_SCRIPT

    def test_script_has_header_comment(self):
        """Script should have identifying header."""
        assert "Avos Memory Auto-Sync" in _PRE_PUSH_HOOK_SCRIPT
        assert "avos hook-install" in _PRE_PUSH_HOOK_SCRIPT


class TestHooksDirCreation:
    """Handles missing hooks directory."""

    def test_creates_hooks_dir_if_missing(self, tmp_path: Path, mock_git_client: MagicMock):
        """Should create hooks directory if it doesn't exist."""
        repo = tmp_path / "repo"
        repo.mkdir()
        git_dir = repo / ".git"
        git_dir.mkdir()

        avos = repo / ".avos"
        _make_config_json(avos)

        orch = HookInstallOrchestrator(
            git_client=mock_git_client,
            repo_root=repo,
        )
        code = orch.run()

        assert code == 0
        assert (git_dir / "hooks" / "pre-push").exists()


class TestEdgeCases:
    """Edge cases and error handling."""

    def test_no_git_dir_returns_1(self, tmp_path: Path, mock_git_client: MagicMock):
        """Should fail when .git doesn't exist."""
        repo = tmp_path / "not_a_repo"
        repo.mkdir()
        avos = repo / ".avos"
        _make_config_json(avos)

        orch = HookInstallOrchestrator(
            git_client=mock_git_client,
            repo_root=repo,
        )
        code = orch.run()
        assert code == 1

    def test_invalid_gitdir_file_returns_1(self, tmp_path: Path, mock_git_client: MagicMock):
        """Should fail when .git file has invalid format."""
        repo = tmp_path / "bad_worktree"
        repo.mkdir()
        (repo / ".git").write_text("invalid content")
        avos = repo / ".avos"
        _make_config_json(avos)

        orch = HookInstallOrchestrator(
            git_client=mock_git_client,
            repo_root=repo,
        )
        code = orch.run()
        assert code == 1


class TestAdditionalCoverageBranches:
    """Additional branch coverage for install/uninstall paths."""

    def test_install_handles_avos_error_from_config(self, git_repo: Path, mock_git_client: MagicMock):
        orch = HookInstallOrchestrator(git_client=mock_git_client, repo_root=git_repo)
        with patch(
            "avos_cli.commands.hook_install.load_config",
            side_effect=RepositoryContextError("bad context"),
        ):
            code = orch.run()
        assert code == 1

    def test_install_handles_oserror_during_write(self, git_repo: Path, mock_git_client: MagicMock):
        orch = HookInstallOrchestrator(git_client=mock_git_client, repo_root=git_repo)
        with patch.object(orch, "_install_hook", side_effect=OSError("disk full")):
            code = orch.run(force=True)
        assert code == 1

    def test_relative_gitdir_file_branch(self, tmp_path: Path, mock_git_client: MagicMock):
        repo = tmp_path / "repo"
        repo.mkdir()
        gitdir = tmp_path / "realgit"
        gitdir.mkdir()
        (repo / ".git").write_text("gitdir: ../realgit")
        _make_config_json(repo / ".avos")

        orch = HookInstallOrchestrator(git_client=mock_git_client, repo_root=repo)
        code = orch.run()
        assert code == 0
        assert (gitdir / "hooks" / "pre-push").exists()

    def test_uninstall_invalid_git_file_format(self, tmp_path: Path):
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".git").write_text("invalid")
        orch = HookUninstallOrchestrator(repo_root=repo)
        assert orch.run() == 1

    def test_uninstall_no_git_found(self, tmp_path: Path):
        repo = tmp_path / "repo"
        repo.mkdir()
        orch = HookUninstallOrchestrator(repo_root=repo)
        assert orch.run() == 1

    def test_uninstall_unlink_oserror_returns_1(self, git_repo: Path):
        hook_path = git_repo / ".git" / "hooks" / "pre-push"
        hook_path.write_text(_PRE_PUSH_HOOK_SCRIPT)
        orch = HookUninstallOrchestrator(repo_root=git_repo)
        with patch("pathlib.Path.unlink", side_effect=OSError("permission denied")):
            assert orch.run() == 1
