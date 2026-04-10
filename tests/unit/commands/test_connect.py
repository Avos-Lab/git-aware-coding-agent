"""Tests for AVOS-009: ConnectOrchestrator.

Covers happy path, idempotent rerun, all precondition failures,
API failures, and exit code correctness.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from avos_cli.commands.connect import ConnectOrchestrator
from avos_cli.exceptions import (
    AuthError,
    RepositoryContextError,
    UpstreamUnavailableError,
)
from avos_cli.models.api import NoteResponse, SearchResult


@pytest.fixture()
def git_repo(tmp_path: Path) -> Path:
    """Create a minimal git repo with origin remote."""
    (tmp_path / ".git").mkdir()
    return tmp_path


@pytest.fixture()
def mock_git_client() -> MagicMock:
    client = MagicMock()
    client.remote_origin.return_value = "myorg/myrepo"
    return client


@pytest.fixture()
def mock_github_client() -> MagicMock:
    client = MagicMock()
    client.validate_repo.return_value = True
    return client


@pytest.fixture()
def mock_memory_client() -> MagicMock:
    client = MagicMock()
    client.search.return_value = SearchResult(results=[], total_count=0)
    client.add_memory.return_value = NoteResponse(
        note_id="note-1", content="bootstrap", created_at="2026-03-06T00:00:00Z"
    )
    return client


@pytest.fixture()
def orchestrator(
    git_repo: Path,
    mock_git_client: MagicMock,
    mock_github_client: MagicMock,
    mock_memory_client: MagicMock,
) -> ConnectOrchestrator:
    return ConnectOrchestrator(
        git_client=mock_git_client,
        github_client=mock_github_client,
        memory_client=mock_memory_client,
        repo_root=git_repo,
    )


class TestHappyPath:
    def test_fresh_connect_returns_0(self, orchestrator: ConnectOrchestrator):
        code = orchestrator.run("myorg/myrepo")
        assert code == 0

    def test_creates_config_file(
        self, orchestrator: ConnectOrchestrator, git_repo: Path
    ):
        orchestrator.run("myorg/myrepo")
        config_path = git_repo / ".avos" / "config.json"
        assert config_path.exists()

    def test_config_has_correct_memory_id(
        self, orchestrator: ConnectOrchestrator, git_repo: Path
    ):
        orchestrator.run("myorg/myrepo")
        data = json.loads((git_repo / ".avos" / "config.json").read_text())
        assert data["memory_id"] == "repo:myorg/myrepo"

    def test_config_has_repo_slug(
        self, orchestrator: ConnectOrchestrator, git_repo: Path
    ):
        orchestrator.run("myorg/myrepo")
        data = json.loads((git_repo / ".avos" / "config.json").read_text())
        assert data["repo"] == "myorg/myrepo"

    def test_config_has_connected_at(
        self, orchestrator: ConnectOrchestrator, git_repo: Path
    ):
        orchestrator.run("myorg/myrepo")
        data = json.loads((git_repo / ".avos" / "config.json").read_text())
        assert "connected_at" in data

    def test_config_has_schema_version(
        self, orchestrator: ConnectOrchestrator, git_repo: Path
    ):
        orchestrator.run("myorg/myrepo")
        data = json.loads((git_repo / ".avos" / "config.json").read_text())
        assert data["schema_version"] == "2"

    def test_bootstrap_note_sent(
        self, orchestrator: ConnectOrchestrator, mock_memory_client: MagicMock
    ):
        orchestrator.run("myorg/myrepo")
        assert mock_memory_client.add_memory.call_count == 1
        calls = mock_memory_client.add_memory.call_args_list
        memory_ids = [c.kwargs.get("memory_id", c.args[0] if c.args else "") for c in calls]
        assert "repo:myorg/myrepo" in memory_ids

    def test_search_called_for_bootstrap_check(
        self, orchestrator: ConnectOrchestrator, mock_memory_client: MagicMock
    ):
        orchestrator.run("myorg/myrepo")
        assert mock_memory_client.search.call_count == 1

    def test_github_validation_called(
        self, orchestrator: ConnectOrchestrator, mock_github_client: MagicMock
    ):
        orchestrator.run("myorg/myrepo")
        mock_github_client.validate_repo.assert_called_once_with("myorg", "myrepo")


class TestIdempotentRerun:
    def test_rerun_returns_0(self, orchestrator: ConnectOrchestrator, git_repo: Path):
        orchestrator.run("myorg/myrepo")
        code = orchestrator.run("myorg/myrepo")
        assert code == 0

    def test_rerun_preserves_connected_at(
        self, orchestrator: ConnectOrchestrator, git_repo: Path
    ):
        """Strict idempotency: rerun must NOT mutate connected_at."""
        from avos_cli.models.api import SearchHit

        orchestrator.run("myorg/myrepo")
        config_path = git_repo / ".avos" / "config.json"
        first_data = json.loads(config_path.read_text())
        first_connected_at = first_data["connected_at"]
        first_mtime = config_path.stat().st_mtime

        orchestrator._memory.search.return_value = SearchResult(
            results=[
                SearchHit(
                    note_id="existing",
                    content="[type: repo_connected]",
                    created_at="2026-03-06T00:00:00Z",
                    rank=1,
                )
            ],
            total_count=1,
        )

        code = orchestrator.run("myorg/myrepo")
        assert code == 0

        second_data = json.loads(config_path.read_text())
        assert second_data["connected_at"] == first_connected_at, (
            "connected_at must not change on idempotent rerun"
        )
        assert config_path.stat().st_mtime == first_mtime, (
            "config file must not be rewritten when content is identical"
        )

    def test_rerun_does_not_send_duplicate_bootstrap(
        self,
        orchestrator: ConnectOrchestrator,
        mock_memory_client: MagicMock,
        git_repo: Path,
    ):
        from avos_cli.models.api import SearchHit

        orchestrator.run("myorg/myrepo")

        mock_memory_client.search.return_value = SearchResult(
            results=[
                SearchHit(
                    note_id="existing",
                    content="[type: repo_connected]",
                    created_at="2026-03-06T00:00:00Z",
                    rank=1,
                )
            ],
            total_count=1,
        )
        mock_memory_client.add_memory.reset_mock()

        code = orchestrator.run("myorg/myrepo")
        assert code == 0
        mock_memory_client.add_memory.assert_not_called()


class TestPreconditionFailures:
    def test_no_git_repo_returns_1(
        self,
        mock_git_client: MagicMock,
        mock_github_client: MagicMock,
        mock_memory_client: MagicMock,
        tmp_path: Path,
    ):
        repo_root = tmp_path / "no_git"
        repo_root.mkdir()
        orch = ConnectOrchestrator(
            git_client=mock_git_client,
            github_client=mock_github_client,
            memory_client=mock_memory_client,
            repo_root=repo_root,
        )
        mock_git_client.remote_origin.side_effect = RepositoryContextError(
            "Not a git repo"
        )
        code = orch.run("myorg/myrepo")
        assert code == 1

    def test_remote_mismatch_returns_1(
        self, orchestrator: ConnectOrchestrator, mock_git_client: MagicMock
    ):
        mock_git_client.remote_origin.return_value = "other/repo"
        code = orchestrator.run("myorg/myrepo")
        assert code == 1

    def test_no_remote_returns_1(
        self, orchestrator: ConnectOrchestrator, mock_git_client: MagicMock
    ):
        mock_git_client.remote_origin.return_value = None
        code = orchestrator.run("myorg/myrepo")
        assert code == 1


class TestExternalFailures:
    def test_github_inaccessible_returns_2(
        self, orchestrator: ConnectOrchestrator, mock_github_client: MagicMock
    ):
        mock_github_client.validate_repo.side_effect = UpstreamUnavailableError(
            "GitHub down"
        )
        code = orchestrator.run("myorg/myrepo")
        assert code == 2

    def test_github_auth_failure_returns_1(
        self, orchestrator: ConnectOrchestrator, mock_github_client: MagicMock
    ):
        mock_github_client.validate_repo.side_effect = AuthError(
            "Bad token", service="GitHub"
        )
        code = orchestrator.run("myorg/myrepo")
        assert code == 1

    def test_github_repo_not_found_returns_1(
        self, orchestrator: ConnectOrchestrator, mock_github_client: MagicMock
    ):
        mock_github_client.validate_repo.return_value = False
        code = orchestrator.run("myorg/myrepo")
        assert code == 1

    def test_avos_api_down_returns_2(
        self, orchestrator: ConnectOrchestrator, mock_memory_client: MagicMock
    ):
        mock_memory_client.search.side_effect = UpstreamUnavailableError(
            "Avos API down"
        )
        code = orchestrator.run("myorg/myrepo")
        assert code == 2

    def test_avos_auth_failure_returns_1(
        self, orchestrator: ConnectOrchestrator, mock_memory_client: MagicMock
    ):
        mock_memory_client.search.side_effect = AuthError(
            "Bad API key", service="Avos Memory"
        )
        code = orchestrator.run("myorg/myrepo")
        assert code == 1


class TestRepoSlugParsing:
    def test_accepts_org_slash_repo(self, orchestrator: ConnectOrchestrator):
        code = orchestrator.run("myorg/myrepo")
        assert code == 0

    def test_invalid_slug_returns_1(self, orchestrator: ConnectOrchestrator):
        code = orchestrator.run("invalid-no-slash")
        assert code == 1


class TestInferSlugFromOrigin:
    """When repo slug is omitted, connect derives org/repo from origin."""

    def test_none_slug_uses_remote_origin(
        self, orchestrator: ConnectOrchestrator, git_repo: Path
    ):
        code = orchestrator.run(None)
        assert code == 0
        data = json.loads((git_repo / ".avos" / "config.json").read_text())
        assert data["repo"] == "myorg/myrepo"

    @pytest.mark.parametrize("blank", ["", "   ", "\t\n "])
    def test_blank_slug_infers_like_omitted(
        self,
        blank: str,
        orchestrator: ConnectOrchestrator,
        git_repo: Path,
    ):
        """Empty or whitespace-only CLI slug uses origin like ``None``."""
        code = orchestrator.run(blank)
        assert code == 0
        data = json.loads((git_repo / ".avos" / "config.json").read_text())
        assert data["repo"] == "myorg/myrepo"

    def test_infer_uses_origin_slug_verbatim(
        self,
        orchestrator: ConnectOrchestrator,
        mock_git_client: MagicMock,
        git_repo: Path,
    ):
        """No explicit org/repo: persisted slug is exactly what origin parses to."""
        mock_git_client.remote_origin.return_value = "acme/custom-name"
        code = orchestrator.run(None)
        assert code == 0
        data = json.loads((git_repo / ".avos" / "config.json").read_text())
        assert data["repo"] == "acme/custom-name"

    def test_none_slug_no_origin_returns_1(
        self, orchestrator: ConnectOrchestrator, mock_git_client: MagicMock
    ):
        mock_git_client.remote_origin.return_value = None
        code = orchestrator.run(None)
        assert code == 1

    def test_whitespace_slug_no_origin_returns_1(
        self, orchestrator: ConnectOrchestrator, mock_git_client: MagicMock
    ):
        """Blank slug must not report invalid format when infer fails."""
        mock_git_client.remote_origin.return_value = None
        code = orchestrator.run("  \t  ")
        assert code == 1

    def test_none_slug_git_error_returns_1(
        self,
        mock_git_client: MagicMock,
        mock_github_client: MagicMock,
        mock_memory_client: MagicMock,
        git_repo: Path,
    ):
        mock_git_client.remote_origin.side_effect = RepositoryContextError(
            "Not a git repo"
        )
        orch = ConnectOrchestrator(
            git_client=mock_git_client,
            github_client=mock_github_client,
            memory_client=mock_memory_client,
            repo_root=git_repo,
        )
        code = orch.run(None)
        assert code == 1


class TestAutoHookInstall:
    """Tests for automatic pre-push hook installation on connect."""

    def test_hook_installed_on_successful_connect(
        self, orchestrator: ConnectOrchestrator, git_repo: Path
    ):
        """Hook should be auto-installed when connect succeeds."""
        code = orchestrator.run("myorg/myrepo")
        assert code == 0
        hook_path = git_repo / ".git" / "hooks" / "pre-push"
        assert hook_path.exists(), "Pre-push hook should be auto-installed"
        content = hook_path.read_text()
        assert "avos hook-sync" in content

    def test_hook_is_executable(
        self, orchestrator: ConnectOrchestrator, git_repo: Path
    ):
        """Installed hook should have executable permissions."""
        import stat

        orchestrator.run("myorg/myrepo")
        hook_path = git_repo / ".git" / "hooks" / "pre-push"
        mode = hook_path.stat().st_mode
        assert mode & stat.S_IXUSR, "Hook should be executable by owner"

    def test_connect_succeeds_even_if_hook_exists(
        self, orchestrator: ConnectOrchestrator, git_repo: Path
    ):
        """Connect should succeed even if a non-avos hook already exists."""
        hooks_dir = git_repo / ".git" / "hooks"
        hooks_dir.mkdir(parents=True, exist_ok=True)
        existing_hook = hooks_dir / "pre-push"
        existing_hook.write_text("#!/bin/sh\necho 'custom hook'\n")

        code = orchestrator.run("myorg/myrepo")
        assert code == 0, "Connect should succeed even if hook install is skipped"
        content = existing_hook.read_text()
        assert "custom hook" in content, "Existing hook should not be overwritten"

    def test_json_output_includes_hook_installed_true(
        self, orchestrator: ConnectOrchestrator, git_repo: Path, capsys: pytest.CaptureFixture[str]
    ):
        """JSON output should include hook_installed=true when hook is installed."""
        code = orchestrator.run("myorg/myrepo", json_output=True)
        assert code == 0
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["success"] is True
        assert data["data"]["hook_installed"] is True

    def test_json_output_includes_hook_installed_false_when_skipped(
        self, orchestrator: ConnectOrchestrator, git_repo: Path, capsys: pytest.CaptureFixture[str]
    ):
        """JSON output should include hook_installed=false when hook is skipped."""
        hooks_dir = git_repo / ".git" / "hooks"
        hooks_dir.mkdir(parents=True, exist_ok=True)
        existing_hook = hooks_dir / "pre-push"
        existing_hook.write_text("#!/bin/sh\necho 'custom hook'\n")

        code = orchestrator.run("myorg/myrepo", json_output=True)
        assert code == 0
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["success"] is True
        assert data["data"]["hook_installed"] is False

    def test_hook_not_installed_when_connect_fails(
        self,
        mock_git_client: MagicMock,
        mock_github_client: MagicMock,
        mock_memory_client: MagicMock,
        git_repo: Path,
    ):
        """Hook should not be installed if connect fails early."""
        mock_github_client.validate_repo.side_effect = AuthError(
            "Bad token", service="GitHub"
        )
        orch = ConnectOrchestrator(
            git_client=mock_git_client,
            github_client=mock_github_client,
            memory_client=mock_memory_client,
            repo_root=git_repo,
        )
        code = orch.run("myorg/myrepo")
        assert code == 1
        hook_path = git_repo / ".git" / "hooks" / "pre-push"
        assert not hook_path.exists(), "Hook should not be installed on failed connect"

    def test_rerun_connect_does_not_reinstall_hook(
        self, orchestrator: ConnectOrchestrator, git_repo: Path
    ):
        """Rerunning connect should detect existing avos hook and skip reinstall."""
        orchestrator.run("myorg/myrepo")
        hook_path = git_repo / ".git" / "hooks" / "pre-push"
        first_mtime = hook_path.stat().st_mtime

        orchestrator.run("myorg/myrepo")
        assert hook_path.stat().st_mtime == first_mtime, (
            "Hook file should not be rewritten on rerun"
        )
