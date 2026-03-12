"""Tests for AVOS-001: Project scaffolding and package setup.

Validates that the package is importable, the version is correct,
the CLI entry point works, and the exception hierarchy is well-formed.
"""

from __future__ import annotations

import importlib
import re
import subprocess
import sys
from unittest.mock import patch

from typer.testing import CliRunner

from avos_cli import __version__
from avos_cli.cli.main import app
from avos_cli.exceptions import (
    ArtifactBuildError,
    AuthError,
    AvosError,
    ConfigurationNotInitializedError,
    ConfigurationValidationError,
    DependencyUnavailableError,
    ErrorCode,
    RateLimitError,
    RepositoryContextError,
    RequestContractError,
    ResourceNotFoundError,
    ServiceParseError,
    StateFileConflictError,
    UpstreamUnavailableError,
)

runner = CliRunner()
_ANSI_ESCAPE_RE = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")


def _strip_ansi(text: str) -> str:
    """Remove ANSI escape sequences from terminal output."""
    return _ANSI_ESCAPE_RE.sub("", text)


def _normalized(text: str) -> str:
    """Normalize CLI output for stable assertions across environments."""
    return _strip_ansi(text)


class TestPackageImport:
    """Verify the package is importable and version is set."""

    def test_version_is_string(self):
        assert isinstance(__version__, str)

    def test_version_is_semver_like(self):
        parts = __version__.split(".")
        assert len(parts) == 3
        assert all(p.isdigit() for p in parts)

    def test_version_value(self):
        assert __version__ == "1.0.0"

    def test_package_importable(self):
        import avos_cli

        assert hasattr(avos_cli, "__version__")

    def test_cli_module_importable(self):
        from avos_cli.cli import main

        assert hasattr(main, "app")

    def test_cli_module_loads_dotenv_on_import(self):
        """CLI module should load .env variables when imported (cwd, pkg root, ~/.avos)."""
        import avos_cli.cli.main as cli_main

        with patch("dotenv.load_dotenv") as load_dotenv_mock:
            importlib.reload(cli_main)
            assert load_dotenv_mock.call_count >= 1

        # Restore original module state after patched reload.
        importlib.reload(cli_main)

    def test_exceptions_module_importable(self):
        from avos_cli import exceptions

        assert hasattr(exceptions, "AvosError")

    def test_first_env_returns_first_non_empty(self):
        """_first_env returns the first non-empty value for any of the given keys."""
        from avos_cli.cli.main import _first_env

        with patch.dict("os.environ", {"_TEST_A": "a", "_TEST_B": "", "_TEST_C": "c"}):
            assert _first_env("_TEST_X", "_TEST_A", "_TEST_B", "_TEST_C") == "a"
            assert _first_env("_TEST_X", "_TEST_Y") == ""
            assert _first_env("_TEST_B", "_TEST_A") == "a"
            assert _first_env("_TEST_NONEXISTENT_1", "_TEST_NONEXISTENT_2") == ""

    def test_make_reply_service_accepts_mixed_case_env_vars(self):
        """_make_reply_service picks up reply_model, reply_model_URL, reply_model_API_KEY."""
        from avos_cli.cli.main import _make_reply_service

        env = {
            "reply_model": "Qwen/Qwen3-Coder-30B",
            "reply_model_URL": "https://api.example.com/v1/chat",
            "reply_model_API_KEY": "sk-test-key-123",
        }
        with patch.dict("os.environ", env, clear=False):
            svc = _make_reply_service()
        assert svc is not None
        assert hasattr(svc, "format_history")
        assert hasattr(svc, "format_ask")

    def test_make_reply_service_returns_none_when_vars_missing(self):
        """_make_reply_service returns None when any required var is missing."""
        from avos_cli.cli.main import _make_reply_service

        with patch.dict("os.environ", {}, clear=True):
            assert _make_reply_service() is None
        with patch.dict(
            "os.environ",
            {"REPLY_MODEL": "m", "REPLY_MODEL_URL": "u"},
            clear=True,
        ):
            assert _make_reply_service() is None


class TestCLIEntryPoint:
    """Verify the CLI entry point works correctly."""

    def test_version_flag(self):
        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0
        assert "1.0.0" in _normalized(result.stdout)

    def test_version_short_flag(self):
        result = runner.invoke(app, ["-v"])
        assert result.exit_code == 0
        assert "1.0.0" in _normalized(result.stdout)

    def test_no_args_shows_help(self):
        result = runner.invoke(app, [])
        assert result.exit_code == 0
        normalized = _normalized(result.stdout)
        assert "Developer memory CLI" in normalized or "Usage" in normalized

    def test_help_flag(self):
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "--version" in _strip_ansi(result.stdout)


class TestExceptionHierarchy:
    """Verify the exception hierarchy is well-formed."""

    def test_all_exceptions_inherit_from_avos_error(self):
        exception_classes = [
            ConfigurationNotInitializedError,
            ConfigurationValidationError,
            RepositoryContextError,
            AuthError,
            RateLimitError,
            UpstreamUnavailableError,
            RequestContractError,
            ResourceNotFoundError,
            DependencyUnavailableError,
            ServiceParseError,
            ArtifactBuildError,
            StateFileConflictError,
        ]
        for exc_class in exception_classes:
            assert issubclass(exc_class, AvosError), f"{exc_class.__name__} must inherit AvosError"

    def test_avos_error_inherits_from_exception(self):
        assert issubclass(AvosError, Exception)

    def test_error_code_enum_completeness(self):
        expected_codes = {
            "CONFIG_NOT_INITIALIZED",
            "CONFIG_VALIDATION_ERROR",
            "REPOSITORY_CONTEXT_ERROR",
            "AUTH_ERROR",
            "RATE_LIMIT_ERROR",
            "UPSTREAM_UNAVAILABLE",
            "REQUEST_CONTRACT_ERROR",
            "RESOURCE_NOT_FOUND",
            "DEPENDENCY_UNAVAILABLE",
            "SERVICE_PARSE_ERROR",
            "ARTIFACT_BUILD_ERROR",
            "STATE_FILE_CONFLICT",
            "INGEST_LOCK_CONFLICT",
            "SANITIZATION_FAILED",
            "GROUNDING_FAILED",
            "LLM_SYNTHESIS_ERROR",
            "CONTEXT_BUDGET_ERROR",
            "QUERY_EMPTY_RESULT",
            "SESSION_ACTIVE_CONFLICT",
            "SESSION_NOT_FOUND",
            "WATCHER_SPAWN_FAILED",
            "WATCHER_STOP_FAILED",
            "CHECKPOINT_PARSE_ERROR",
        }
        actual_codes = {e.value for e in ErrorCode}
        assert actual_codes == expected_codes

    def test_config_not_initialized_defaults(self):
        exc = ConfigurationNotInitializedError()
        assert "not connected" in str(exc).lower() or "config" in str(exc).lower()
        assert exc.code == ErrorCode.CONFIG_NOT_INITIALIZED
        assert exc.hint is not None
        assert "avos connect" in exc.hint

    def test_config_validation_error(self):
        exc = ConfigurationValidationError("bad json")
        assert str(exc) == "bad json"
        assert exc.code == ErrorCode.CONFIG_VALIDATION_ERROR

    def test_repository_context_error_defaults(self):
        exc = RepositoryContextError()
        assert exc.code == ErrorCode.REPOSITORY_CONTEXT_ERROR
        assert exc.hint is not None

    def test_auth_error(self):
        exc = AuthError("invalid token", service="GitHub")
        assert str(exc) == "invalid token"
        assert exc.code == ErrorCode.AUTH_ERROR
        assert "GitHub" in (exc.hint or "")

    def test_rate_limit_error_with_retry_after(self):
        exc = RateLimitError("too many requests", retry_after=30.0)
        assert exc.retryable is True
        assert exc.retry_after == 30.0
        assert "30" in (exc.hint or "")

    def test_rate_limit_error_without_retry_after(self):
        exc = RateLimitError("too many requests")
        assert exc.retryable is True
        assert exc.retry_after is None

    def test_upstream_unavailable_is_retryable(self):
        exc = UpstreamUnavailableError("service down")
        assert exc.retryable is True

    def test_request_contract_error(self):
        exc = RequestContractError("mixed payload modes")
        assert exc.code == ErrorCode.REQUEST_CONTRACT_ERROR
        assert exc.retryable is False

    def test_dependency_unavailable(self):
        exc = DependencyUnavailableError("git")
        assert "git" in str(exc)
        assert exc.code == ErrorCode.DEPENDENCY_UNAVAILABLE
        assert "git" in (exc.hint or "")

    def test_service_parse_error(self):
        exc = ServiceParseError("unexpected output format")
        assert exc.code == ErrorCode.SERVICE_PARSE_ERROR

    def test_artifact_build_error(self):
        exc = ArtifactBuildError("invalid model")
        assert exc.code == ErrorCode.ARTIFACT_BUILD_ERROR

    def test_state_file_conflict_is_retryable(self):
        exc = StateFileConflictError("lock held by another process")
        assert exc.retryable is True
        assert exc.code == ErrorCode.STATE_FILE_CONFLICT


class TestPipInstall:
    """Verify the package can be installed and the entry point is registered."""

    def test_avos_command_available(self):
        result = subprocess.run(
            [sys.executable, "-m", "avos_cli.cli.main", "--help"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        # Typer apps invoked via __main__ should show help
        normalized = _normalized(result.stdout)
        assert result.returncode == 0 or "Usage" in normalized or "avos" in normalized
