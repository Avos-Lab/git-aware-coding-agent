"""Tests for AVOS-001: Project scaffolding and package setup.

Validates that the package is importable, the version is correct,
the CLI entry point works, and the exception hierarchy is well-formed.
"""

from __future__ import annotations

import subprocess
import sys

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


class TestPackageImport:
    """Verify the package is importable and version is set."""

    def test_version_is_string(self):
        assert isinstance(__version__, str)

    def test_version_is_semver_like(self):
        parts = __version__.split(".")
        assert len(parts) == 3
        assert all(p.isdigit() for p in parts)

    def test_version_value(self):
        assert __version__ == "0.1.0"

    def test_package_importable(self):
        import avos_cli

        assert hasattr(avos_cli, "__version__")

    def test_cli_module_importable(self):
        from avos_cli.cli import main

        assert hasattr(main, "app")

    def test_exceptions_module_importable(self):
        from avos_cli import exceptions

        assert hasattr(exceptions, "AvosError")


class TestCLIEntryPoint:
    """Verify the CLI entry point works correctly."""

    def test_version_flag(self):
        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0
        assert "0.1.0" in result.stdout

    def test_version_short_flag(self):
        result = runner.invoke(app, ["-v"])
        assert result.exit_code == 0
        assert "0.1.0" in result.stdout

    def test_no_args_shows_help(self):
        result = runner.invoke(app, [])
        assert result.exit_code == 0
        assert "Developer memory CLI" in result.stdout or "Usage" in result.stdout

    def test_help_flag(self):
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "--version" in result.stdout


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
        assert result.returncode == 0 or "Usage" in result.stdout or "avos" in result.stdout
