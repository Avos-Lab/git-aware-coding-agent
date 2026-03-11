"""CLI-path integration tests for `avos connect` and `avos ingest`.

Exercises the real Typer command wiring in cli/main.py via CliRunner,
verifying argument parsing, env-var resolution, error messages, and
exit codes through the actual CLI entrypoint.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from avos_cli.cli.main import app
from avos_cli.models.api import NoteResponse, SearchResult

runner = CliRunner()


@pytest.fixture()
def git_repo(tmp_path: Path) -> Path:
    """Minimal git repo."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    return repo


@pytest.fixture()
def configured_repo(git_repo: Path) -> Path:
    """Git repo with .avos/config.json already written (post-connect)."""
    avos = git_repo / ".avos"
    avos.mkdir()
    config = {
        "api_key": "",
        "api_url": "",
        "connected_at": "2026-03-06T00:00:00+00:00",
        "memory_id": "repo:testorg/testrepo",
        "memory_id_session": "repo:testorg/testrepo-session",
        "repo": "testorg/testrepo",
        "schema_version": "2",
    }
    (avos / "config.json").write_text(json.dumps(config, indent=2, sort_keys=True))
    (git_repo / "README.md").write_text("# Test\n")
    return git_repo


def _note_response(n: int = 1, **kwargs: Any) -> NoteResponse:
    return NoteResponse(
        note_id=f"note-{n}",
        content=kwargs.get("content", "ok"),
        created_at="2026-03-06T00:00:00Z",
    )


def _env_patch(overrides: dict[str, str] | None = None):
    """Patch os.environ to contain only the specified keys for CLI tests."""
    base = {
        "AVOS_API_KEY": "test-key",
        "AVOS_API_URL": "http://localhost:8000",
        "GITHUB_TOKEN": "gh-tok",
        "ANTHROPIC_API_KEY": "test-anthropic-key",
    }
    if overrides is not None:
        base.update(overrides)
    return patch.dict("os.environ", base, clear=True)


def _setup_service_mocks(
    remote: str = "testorg/testrepo",
    validate: bool = True,
    prs: list | None = None,
    issues: list | None = None,
    commits: list | None = None,
) -> tuple[MagicMock, MagicMock, MagicMock]:
    """Create mock instances for all three service classes."""
    git_mock = MagicMock()
    git_mock.remote_origin.return_value = remote
    git_mock.commit_log.return_value = commits or []

    gh_mock = MagicMock()
    gh_mock.validate_repo.return_value = validate
    gh_mock.list_pull_requests.return_value = prs or []
    gh_mock.list_issues.return_value = issues or []

    mem_mock = MagicMock()
    mem_mock.search.return_value = SearchResult(results=[], total_count=0)
    counter = [0]

    def _add_mem(**kwargs: Any) -> NoteResponse:
        counter[0] += 1
        return _note_response(counter[0], **kwargs)

    mem_mock.add_memory.side_effect = _add_mem

    return git_mock, gh_mock, mem_mock


class TestConnectCLI:
    """Tests that exercise `avos connect` through the CLI entrypoint."""

    def test_missing_api_key_exits_1(self, git_repo: Path):
        with (
            _env_patch({"AVOS_API_KEY": ""}),
            patch("avos_cli.config.manager.find_repo_root", return_value=git_repo),
        ):
            result = runner.invoke(app, ["connect", "org/repo"])
        assert result.exit_code == 1

    def test_missing_github_token_exits_1(self, git_repo: Path):
        with (
            _env_patch({"GITHUB_TOKEN": ""}),
            patch("avos_cli.config.manager.find_repo_root", return_value=git_repo),
        ):
            result = runner.invoke(app, ["connect", "org/repo"])
        assert result.exit_code == 1

    def test_connect_happy_path(self, git_repo: Path):
        git_m, gh_m, mem_m = _setup_service_mocks()
        with (
            _env_patch(),
            patch("avos_cli.config.manager.find_repo_root", return_value=git_repo),
            patch("avos_cli.services.git_client.GitClient", return_value=git_m),
            patch("avos_cli.services.github_client.GitHubClient", return_value=gh_m),
            patch("avos_cli.services.memory_client.AvosMemoryClient", return_value=mem_m),
        ):
            result = runner.invoke(app, ["connect", "testorg/testrepo"])

        assert result.exit_code == 0
        assert (git_repo / ".avos" / "config.json").exists()

    def test_connect_invalid_slug_exits_1(self, git_repo: Path):
        git_m, gh_m, mem_m = _setup_service_mocks()
        with (
            _env_patch(),
            patch("avos_cli.config.manager.find_repo_root", return_value=git_repo),
            patch("avos_cli.services.git_client.GitClient", return_value=git_m),
            patch("avos_cli.services.github_client.GitHubClient", return_value=gh_m),
            patch("avos_cli.services.memory_client.AvosMemoryClient", return_value=mem_m),
        ):
            result = runner.invoke(app, ["connect", "noslash"])
        assert result.exit_code == 1

    def test_no_args_shows_help(self):
        result = runner.invoke(app, [])
        assert result.exit_code == 0
        assert "Usage" in result.output or "avos" in result.output

    def test_version_flag(self):
        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0
        assert "avos" in result.output

    def test_connect_remote_mismatch_exits_1(self, git_repo: Path):
        git_m, gh_m, mem_m = _setup_service_mocks(remote="other/repo")
        with (
            _env_patch(),
            patch("avos_cli.config.manager.find_repo_root", return_value=git_repo),
            patch("avos_cli.services.git_client.GitClient", return_value=git_m),
            patch("avos_cli.services.github_client.GitHubClient", return_value=gh_m),
            patch("avos_cli.services.memory_client.AvosMemoryClient", return_value=mem_m),
        ):
            result = runner.invoke(app, ["connect", "testorg/testrepo"])
        assert result.exit_code == 1


class TestIngestCLI:
    """Tests that exercise `avos ingest` through the CLI entrypoint."""

    def test_missing_api_key_exits_1(self, configured_repo: Path):
        with (
            _env_patch({"AVOS_API_KEY": ""}),
            patch("avos_cli.config.manager.find_repo_root", return_value=configured_repo),
        ):
            result = runner.invoke(app, ["ingest", "testorg/testrepo"])
        assert result.exit_code == 1

    def test_missing_github_token_exits_1(self, configured_repo: Path):
        with (
            _env_patch({"GITHUB_TOKEN": ""}),
            patch("avos_cli.config.manager.find_repo_root", return_value=configured_repo),
        ):
            result = runner.invoke(app, ["ingest", "testorg/testrepo"])
        assert result.exit_code == 1

    def test_ingest_happy_path(self, configured_repo: Path):
        commits = [
            {"hash": "abc123", "message": "init", "author": "dev", "date": "2026-02-01"},
        ]
        git_m, gh_m, mem_m = _setup_service_mocks(commits=commits)
        with (
            _env_patch(),
            patch("avos_cli.config.manager.find_repo_root", return_value=configured_repo),
            patch("avos_cli.services.git_client.GitClient", return_value=git_m),
            patch("avos_cli.services.github_client.GitHubClient", return_value=gh_m),
            patch("avos_cli.services.memory_client.AvosMemoryClient", return_value=mem_m),
        ):
            result = runner.invoke(app, ["ingest", "testorg/testrepo"])
        assert result.exit_code == 0

    def test_ingest_since_option_parsed(self, configured_repo: Path):
        git_m, gh_m, mem_m = _setup_service_mocks()
        with (
            _env_patch(),
            patch("avos_cli.config.manager.find_repo_root", return_value=configured_repo),
            patch("avos_cli.services.git_client.GitClient", return_value=git_m),
            patch("avos_cli.services.github_client.GitHubClient", return_value=gh_m),
            patch("avos_cli.services.memory_client.AvosMemoryClient", return_value=mem_m),
        ):
            result = runner.invoke(
                app, ["ingest", "testorg/testrepo", "--since", "30d"]
            )
        assert result.exit_code == 0

    def test_ingest_invalid_since_exits_error(self, configured_repo: Path):
        git_m, gh_m, mem_m = _setup_service_mocks()
        with (
            _env_patch(),
            patch("avos_cli.config.manager.find_repo_root", return_value=configured_repo),
            patch("avos_cli.services.git_client.GitClient", return_value=git_m),
            patch("avos_cli.services.github_client.GitHubClient", return_value=gh_m),
            patch("avos_cli.services.memory_client.AvosMemoryClient", return_value=mem_m),
        ):
            result = runner.invoke(
                app, ["ingest", "testorg/testrepo", "--since", "abc"]
            )
        assert result.exit_code != 0

    def test_ingest_no_config_exits_1(self, git_repo: Path):
        """Ingest on a repo without .avos/config.json should exit 1."""
        git_m, gh_m, mem_m = _setup_service_mocks()
        with (
            _env_patch(),
            patch("avos_cli.config.manager.find_repo_root", return_value=git_repo),
            patch("avos_cli.services.git_client.GitClient", return_value=git_m),
            patch("avos_cli.services.github_client.GitHubClient", return_value=gh_m),
            patch("avos_cli.services.memory_client.AvosMemoryClient", return_value=mem_m),
        ):
            result = runner.invoke(app, ["ingest", "testorg/testrepo"])
        assert result.exit_code == 1

    def test_ingest_since_zero_exits_error(self, configured_repo: Path):
        with _env_patch():
            result = runner.invoke(
                app, ["ingest", "testorg/testrepo", "--since", "0d"]
            )
        assert result.exit_code != 0

    def test_ingest_since_negative_exits_error(self, configured_repo: Path):
        with _env_patch():
            result = runner.invoke(
                app, ["ingest", "testorg/testrepo", "--since", "-5d"]
            )
        assert result.exit_code != 0


class TestAskCLI:
    """Tests that exercise `avos ask` through the CLI entrypoint."""

    def test_missing_api_key_exits_1(self, git_repo: Path):
        with (
            _env_patch({"AVOS_API_KEY": ""}),
            patch("avos_cli.config.manager.find_repo_root", return_value=git_repo),
        ):
            result = runner.invoke(app, ["ask", "How does auth work?"])
        assert result.exit_code == 1

    def test_missing_anthropic_key_exits_1(self, configured_repo: Path):
        with (
            _env_patch({"ANTHROPIC_API_KEY": ""}),
            patch("avos_cli.config.manager.find_repo_root", return_value=configured_repo),
        ):
            result = runner.invoke(app, ["ask", "How does auth work?"])
        assert result.exit_code == 1
        assert "ANTHROPIC_API_KEY" in result.output

    def test_ask_help_shows(self):
        result = runner.invoke(app, ["ask", "--help"])
        assert result.exit_code == 0
        assert "question" in result.output.lower() or "QUESTION" in result.output

    def test_ask_no_config_exits_1(self, git_repo: Path):
        with (
            _env_patch(),
            patch("avos_cli.config.manager.find_repo_root", return_value=git_repo),
            patch("avos_cli.services.memory_client.AvosMemoryClient"),
            patch("avos_cli.services.llm_client.LLMClient"),
        ):
            result = runner.invoke(app, ["ask", "How does auth work?"])
        assert result.exit_code == 1

    def test_ask_empty_results(self, configured_repo: Path):
        mem_m = MagicMock()
        mem_m.search.return_value = SearchResult(results=[], total_count=0)
        with (
            _env_patch(),
            patch("avos_cli.config.manager.find_repo_root", return_value=configured_repo),
            patch("avos_cli.services.memory_client.AvosMemoryClient", return_value=mem_m),
            patch("avos_cli.services.llm_client.LLMClient"),
        ):
            result = runner.invoke(app, ["ask", "How does auth work?"])
        assert result.exit_code == 0

    def test_ask_json_mode_empty_results(self, configured_repo: Path):
        mem_m = MagicMock()
        mem_m.search.return_value = SearchResult(results=[], total_count=0)
        with (
            _env_patch(),
            patch("avos_cli.config.manager.find_repo_root", return_value=configured_repo),
            patch("avos_cli.services.memory_client.AvosMemoryClient", return_value=mem_m),
            patch("avos_cli.services.llm_client.LLMClient"),
        ):
            result = runner.invoke(app, ["--json", "ask", "How does auth work?"])
        assert result.exit_code == 0
        assert '"success": true' in result.output or '"success":true' in result.output
        assert "avos.ask.v1" in result.output


class TestSessionAskCLI:
    """Tests that exercise `avos session-ask` through the CLI entrypoint."""

    def test_session_ask_help_shows(self):
        result = runner.invoke(app, ["session-ask", "--help"])
        assert result.exit_code == 0
        assert "question" in result.output.lower() or "QUESTION" in result.output

    def test_session_ask_empty_results(self, configured_repo: Path):
        mem_m = MagicMock()
        mem_m.search.return_value = SearchResult(results=[], total_count=0)
        with (
            _env_patch(),
            patch("avos_cli.config.manager.find_repo_root", return_value=configured_repo),
            patch("avos_cli.services.memory_client.AvosMemoryClient", return_value=mem_m),
            patch("avos_cli.services.llm_client.LLMClient"),
        ):
            result = runner.invoke(app, ["session-ask", "What is the team working on?"])
        assert result.exit_code == 0


class TestHistoryCLI:
    """Tests that exercise `avos history` through the CLI entrypoint."""

    def test_missing_api_key_exits_1(self, git_repo: Path):
        with (
            _env_patch({"AVOS_API_KEY": ""}),
            patch("avos_cli.config.manager.find_repo_root", return_value=git_repo),
        ):
            result = runner.invoke(app, ["history", "payment system"])
        assert result.exit_code == 1

    def test_missing_anthropic_key_exits_1(self, configured_repo: Path):
        with (
            _env_patch({"ANTHROPIC_API_KEY": ""}),
            patch("avos_cli.config.manager.find_repo_root", return_value=configured_repo),
        ):
            result = runner.invoke(app, ["history", "payment system"])
        assert result.exit_code == 1
        assert "ANTHROPIC_API_KEY" in result.output

    def test_history_help_shows(self):
        result = runner.invoke(app, ["history", "--help"])
        assert result.exit_code == 0
        assert "subject" in result.output.lower() or "SUBJECT" in result.output

    def test_history_empty_results(self, configured_repo: Path):
        mem_m = MagicMock()
        mem_m.search.return_value = SearchResult(results=[], total_count=0)
        with (
            _env_patch(),
            patch("avos_cli.config.manager.find_repo_root", return_value=configured_repo),
            patch("avos_cli.services.memory_client.AvosMemoryClient", return_value=mem_m),
            patch("avos_cli.services.llm_client.LLMClient"),
        ):
            result = runner.invoke(app, ["history", "payment system"])
        assert result.exit_code == 0

    def test_history_json_mode_empty_results(self, configured_repo: Path):
        mem_m = MagicMock()
        mem_m.search.return_value = SearchResult(results=[], total_count=0)
        with (
            _env_patch(),
            patch("avos_cli.config.manager.find_repo_root", return_value=configured_repo),
            patch("avos_cli.services.memory_client.AvosMemoryClient", return_value=mem_m),
            patch("avos_cli.services.llm_client.LLMClient"),
        ):
            result = runner.invoke(app, ["--json", "history", "payment system"])
        assert result.exit_code == 0
        assert '"success": true' in result.output or '"success":true' in result.output
        assert "avos.history.v1" in result.output


class TestSessionStartCLI:
    """Tests that exercise `avos session-start` through the CLI entrypoint."""

    def test_missing_api_key_exits_1(self, git_repo: Path):
        with (
            _env_patch({"AVOS_API_KEY": ""}),
            patch("avos_cli.config.manager.find_repo_root", return_value=git_repo),
        ):
            result = runner.invoke(app, ["session-start", "Test goal"])
        assert result.exit_code == 1

    def test_session_start_help_shows(self):
        result = runner.invoke(app, ["session-start", "--help"])
        assert result.exit_code == 0
        assert "goal" in result.output.lower() or "GOAL" in result.output

    def test_session_start_no_config_exits_1(self, git_repo: Path):
        git_m = MagicMock()
        mem_m = MagicMock()
        with (
            _env_patch(),
            patch("avos_cli.config.manager.find_repo_root", return_value=git_repo),
            patch("avos_cli.services.git_client.GitClient", return_value=git_m),
            patch("avos_cli.services.memory_client.AvosMemoryClient", return_value=mem_m),
        ):
            result = runner.invoke(app, ["session-start", "Test goal"])
        assert result.exit_code == 1

    def test_session_start_happy_path(self, configured_repo: Path):
        git_m = MagicMock()
        git_m.current_branch.return_value = "main"
        git_m.is_worktree.return_value = False
        mem_m = MagicMock()
        with (
            _env_patch(),
            patch("avos_cli.config.manager.find_repo_root", return_value=configured_repo),
            patch("avos_cli.services.git_client.GitClient", return_value=git_m),
            patch("avos_cli.services.memory_client.AvosMemoryClient", return_value=mem_m),
            patch("avos_cli.commands.session_start.subprocess") as mock_sub,
        ):
            mock_proc = MagicMock()
            mock_proc.pid = 12345
            mock_proc.poll.return_value = None
            mock_sub.Popen.return_value = mock_proc
            result = runner.invoke(app, ["session-start", "Implement feature"])
        assert result.exit_code == 0
        assert (configured_repo / ".avos" / "session.json").exists()


class TestSessionEndCLI:
    """Tests that exercise `avos session-end` through the CLI entrypoint."""

    def test_missing_api_key_exits_1(self, git_repo: Path):
        with (
            _env_patch({"AVOS_API_KEY": ""}),
            patch("avos_cli.config.manager.find_repo_root", return_value=git_repo),
        ):
            result = runner.invoke(app, ["session-end"])
        assert result.exit_code == 1

    def test_session_end_help_shows(self):
        result = runner.invoke(app, ["session-end", "--help"])
        assert result.exit_code == 0

    def test_session_end_no_session_exits_1(self, configured_repo: Path):
        mem_m = MagicMock()
        llm_m = MagicMock()
        with (
            _env_patch(),
            patch("avos_cli.config.manager.find_repo_root", return_value=configured_repo),
            patch("avos_cli.services.memory_client.AvosMemoryClient", return_value=mem_m),
            patch("avos_cli.services.llm_client.LLMClient", return_value=llm_m),
        ):
            result = runner.invoke(app, ["session-end"])
        assert result.exit_code == 1

    def test_session_end_happy_path(self, configured_repo: Path):
        avos_dir = configured_repo / ".avos"
        session = {
            "session_id": "sess_test123",
            "goal": "Test goal",
            "start_time": "2026-03-07T10:00:00+00:00",
            "branch": "main",
            "memory_id": "repo:testorg/testrepo-session",
        }
        (avos_dir / "session.json").write_text(json.dumps(session))
        pid_data = {"pid": 999999, "started_at": "2026-03-07T10:00:00+00:00", "session_id": "sess_test123"}
        (avos_dir / "watcher.pid").write_text(json.dumps(pid_data))

        mem_m = MagicMock()
        llm_m = MagicMock()
        with (
            _env_patch(),
            patch("avos_cli.config.manager.find_repo_root", return_value=configured_repo),
            patch("avos_cli.services.memory_client.AvosMemoryClient", return_value=mem_m),
            patch("avos_cli.services.llm_client.LLMClient", return_value=llm_m),
        ):
            result = runner.invoke(app, ["session-end"])
        assert result.exit_code == 0
        mem_m.add_memory.assert_called_once()


class TestParseSinceDays:
    """Unit tests for the _parse_since_days helper in cli/main.py."""

    def test_parse_with_d_suffix(self):
        from avos_cli.cli.main import _parse_since_days

        assert _parse_since_days("90d") == 90

    def test_parse_without_suffix(self):
        from avos_cli.cli.main import _parse_since_days

        assert _parse_since_days("30") == 30

    def test_parse_with_whitespace(self):
        from avos_cli.cli.main import _parse_since_days

        assert _parse_since_days("  45d  ") == 45

    def test_parse_zero_raises(self):
        import typer

        from avos_cli.cli.main import _parse_since_days

        with pytest.raises(typer.BadParameter):
            _parse_since_days("0d")

    def test_parse_negative_raises(self):
        import typer

        from avos_cli.cli.main import _parse_since_days

        with pytest.raises(typer.BadParameter):
            _parse_since_days("-10")

    def test_parse_non_numeric_raises(self):
        import typer

        from avos_cli.cli.main import _parse_since_days

        with pytest.raises(typer.BadParameter):
            _parse_since_days("abc")
