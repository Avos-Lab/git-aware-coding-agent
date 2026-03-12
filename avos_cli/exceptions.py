"""Exception hierarchy and error codes for the AVOS CLI.

All exceptions inherit from AvosError. Each exception carries a machine-readable
error code, a human-readable message, and an optional action hint for the user.
"""

from __future__ import annotations

from enum import Enum


class ErrorCode(str, Enum):
    """Machine-readable error codes for structured error handling."""

    CONFIG_NOT_INITIALIZED = "CONFIG_NOT_INITIALIZED"
    CONFIG_VALIDATION_ERROR = "CONFIG_VALIDATION_ERROR"
    REPOSITORY_CONTEXT_ERROR = "REPOSITORY_CONTEXT_ERROR"
    AUTH_ERROR = "AUTH_ERROR"
    RATE_LIMIT_ERROR = "RATE_LIMIT_ERROR"
    UPSTREAM_UNAVAILABLE = "UPSTREAM_UNAVAILABLE"
    REQUEST_CONTRACT_ERROR = "REQUEST_CONTRACT_ERROR"
    DEPENDENCY_UNAVAILABLE = "DEPENDENCY_UNAVAILABLE"
    SERVICE_PARSE_ERROR = "SERVICE_PARSE_ERROR"
    ARTIFACT_BUILD_ERROR = "ARTIFACT_BUILD_ERROR"
    RESOURCE_NOT_FOUND = "RESOURCE_NOT_FOUND"
    STATE_FILE_CONFLICT = "STATE_FILE_CONFLICT"
    INGEST_LOCK_CONFLICT = "INGEST_LOCK_CONFLICT"
    SANITIZATION_FAILED = "SANITIZATION_FAILED"
    GROUNDING_FAILED = "GROUNDING_FAILED"
    LLM_SYNTHESIS_ERROR = "LLM_SYNTHESIS_ERROR"
    CONTEXT_BUDGET_ERROR = "CONTEXT_BUDGET_ERROR"
    QUERY_EMPTY_RESULT = "QUERY_EMPTY_RESULT"
    SESSION_ACTIVE_CONFLICT = "SESSION_ACTIVE_CONFLICT"
    SESSION_NOT_FOUND = "SESSION_NOT_FOUND"
    WATCHER_SPAWN_FAILED = "WATCHER_SPAWN_FAILED"
    WATCHER_STOP_FAILED = "WATCHER_STOP_FAILED"
    CHECKPOINT_PARSE_ERROR = "CHECKPOINT_PARSE_ERROR"


class AvosError(Exception):
    """Base exception for all AVOS CLI errors.

    Args:
        message: Human-readable error description.
        code: Machine-readable error code from ErrorCode enum.
        hint: Optional action hint for the user.
        retryable: Whether the operation can be retried.
    """

    def __init__(
        self,
        message: str,
        code: ErrorCode,
        hint: str | None = None,
        retryable: bool = False,
    ) -> None:
        self.code = code
        self.hint = hint
        self.retryable = retryable
        super().__init__(message)


class ConfigurationNotInitializedError(AvosError):
    """Raised when .avos/config.json is missing or memory_id is not set."""

    def __init__(self, message: str | None = None) -> None:
        super().__init__(
            message=message or "Repository not connected. No .avos/config.json found.",
            code=ErrorCode.CONFIG_NOT_INITIALIZED,
            hint="Run 'avos connect <org/repo>' to initialize this repository.",
        )


class ConfigurationValidationError(AvosError):
    """Raised when config file exists but contains invalid data."""

    def __init__(self, message: str) -> None:
        super().__init__(
            message=message,
            code=ErrorCode.CONFIG_VALIDATION_ERROR,
            hint="Inspect and fix .avos/config.json, or re-run 'avos connect'.",
        )


class RepositoryContextError(AvosError):
    """Raised when the current directory is not inside a valid Git repository."""

    def __init__(self, message: str | None = None) -> None:
        super().__init__(
            message=message or "Not inside a Git repository.",
            code=ErrorCode.REPOSITORY_CONTEXT_ERROR,
            hint="Run this command from within a Git repository.",
        )


class AuthError(AvosError):
    """Raised when API authentication fails."""

    def __init__(self, message: str, service: str = "API") -> None:
        super().__init__(
            message=message,
            code=ErrorCode.AUTH_ERROR,
            hint=f"Verify your {service} credentials are correct and have required permissions.",
        )


class RateLimitError(AvosError):
    """Raised when API rate limit is exhausted."""

    def __init__(self, message: str, retry_after: float | None = None) -> None:
        hint = "Rate limit exceeded."
        if retry_after is not None:
            hint = f"Rate limit exceeded. Retry after {retry_after:.0f} seconds."
        super().__init__(
            message=message,
            code=ErrorCode.RATE_LIMIT_ERROR,
            hint=hint,
            retryable=True,
        )
        self.retry_after = retry_after


class UpstreamUnavailableError(AvosError):
    """Raised when an external service is unreachable after retries."""

    def __init__(self, message: str) -> None:
        super().__init__(
            message=message,
            code=ErrorCode.UPSTREAM_UNAVAILABLE,
            hint="The service may be temporarily unavailable. Try again later.",
            retryable=True,
        )


class RequestContractError(AvosError):
    """Raised when a request violates the API contract."""

    def __init__(self, message: str) -> None:
        super().__init__(
            message=message,
            code=ErrorCode.REQUEST_CONTRACT_ERROR,
        )


class ResourceNotFoundError(AvosError):
    """Raised when a requested resource does not exist (404)."""

    def __init__(self, message: str) -> None:
        super().__init__(
            message=message,
            code=ErrorCode.RESOURCE_NOT_FOUND,
        )


class DependencyUnavailableError(AvosError):
    """Raised when a required local dependency is missing."""

    def __init__(self, dependency: str) -> None:
        super().__init__(
            message=f"Required dependency not found: {dependency}",
            code=ErrorCode.DEPENDENCY_UNAVAILABLE,
            hint=f"Install or configure '{dependency}' and ensure it is on your PATH.",
        )


class ServiceParseError(AvosError):
    """Raised when service output cannot be parsed."""

    def __init__(self, message: str) -> None:
        super().__init__(
            message=message,
            code=ErrorCode.SERVICE_PARSE_ERROR,
            hint="This may indicate an upstream format change or a parser defect.",
        )


class ArtifactBuildError(AvosError):
    """Raised when an artifact cannot be built from its input model."""

    def __init__(self, message: str) -> None:
        super().__init__(
            message=message,
            code=ErrorCode.ARTIFACT_BUILD_ERROR,
        )


class StateFileConflictError(AvosError):
    """Raised when a local state file has a concurrent ownership conflict."""

    def __init__(self, message: str) -> None:
        super().__init__(
            message=message,
            code=ErrorCode.STATE_FILE_CONFLICT,
            hint="Another process may be writing to this file. Wait and retry.",
            retryable=True,
        )


class IngestLockError(AvosError):
    """Raised when the ingest lock cannot be acquired."""

    def __init__(self, message: str | None = None, holder_pid: int | None = None) -> None:
        self.holder_pid = holder_pid
        super().__init__(
            message=message or "Another ingest process is running.",
            code=ErrorCode.INGEST_LOCK_CONFLICT,
            hint="Wait for the other ingest to finish, or remove .avos/ingest.lock if stale.",
        )


class SanitizationError(AvosError):
    """Raised when sanitization confidence is below threshold.

    Args:
        message: Description of the sanitization failure.
        confidence_score: The computed confidence score that triggered the failure.
    """

    def __init__(self, message: str, confidence_score: int | None = None) -> None:
        self.confidence_score = confidence_score
        super().__init__(
            message=message,
            code=ErrorCode.SANITIZATION_FAILED,
            hint="Sanitization confidence too low for safe synthesis. Falling back to raw results.",
        )


class GroundingError(AvosError):
    """Raised when citation grounding fails minimum threshold.

    Args:
        message: Description of the grounding failure.
        grounded_count: Number of successfully grounded citations.
        total_count: Total number of citations attempted.
    """

    def __init__(
        self, message: str, grounded_count: int = 0, total_count: int = 0
    ) -> None:
        self.grounded_count = grounded_count
        self.total_count = total_count
        super().__init__(
            message=message,
            code=ErrorCode.GROUNDING_FAILED,
            hint="Synthesis citations could not be verified against retrieved artifacts.",
        )


class LLMSynthesisError(AvosError):
    """Raised when LLM synthesis fails.

    Args:
        message: Description of the synthesis failure.
        failure_class: 'transient' (retryable) or 'non_transient' or 'unknown'.
    """

    def __init__(self, message: str, failure_class: str = "unknown") -> None:
        self.failure_class = failure_class
        retryable = failure_class == "transient"
        super().__init__(
            message=message,
            code=ErrorCode.LLM_SYNTHESIS_ERROR,
            hint="LLM synthesis failed. Falling back to raw search results.",
            retryable=retryable,
        )


class ContextBudgetError(AvosError):
    """Raised when context budget cannot meet minimum evidence floor."""

    def __init__(self, message: str) -> None:
        super().__init__(
            message=message,
            code=ErrorCode.CONTEXT_BUDGET_ERROR,
            hint="Insufficient evidence artifacts for synthesis. Using fallback output.",
        )


class SessionActiveError(AvosError):
    """Raised when a session is already active and blocks a new start.

    Args:
        message: Description of the conflict.
    """

    def __init__(self, message: str | None = None) -> None:
        super().__init__(
            message=message or "A session is already active.",
            code=ErrorCode.SESSION_ACTIVE_CONFLICT,
            hint="Run 'avos session-end' to finish the current session first.",
        )


class SessionNotFoundError(AvosError):
    """Raised when no active session exists for an end operation.

    Args:
        message: Description of the missing session.
    """

    def __init__(self, message: str | None = None) -> None:
        super().__init__(
            message=message or "No active session found.",
            code=ErrorCode.SESSION_NOT_FOUND,
            hint="Run 'avos session-start' to begin a new session.",
        )


class WatcherLifecycleError(AvosError):
    """Raised when the watcher process fails to spawn or stop.

    Args:
        message: Description of the lifecycle failure.
        failure_type: 'spawn' or 'stop' to select the appropriate error code.
    """

    def __init__(self, message: str, failure_type: str = "spawn") -> None:
        self.failure_type = failure_type
        code = (
            ErrorCode.WATCHER_STOP_FAILED
            if failure_type == "stop"
            else ErrorCode.WATCHER_SPAWN_FAILED
        )
        super().__init__(
            message=message,
            code=code,
            hint="Check process permissions and system resources.",
        )


class CheckpointParseError(AvosError):
    """Raised when checkpoint JSONL lines cannot be parsed.

    Args:
        message: Description of the parse failure.
    """

    def __init__(self, message: str) -> None:
        super().__init__(
            message=message,
            code=ErrorCode.CHECKPOINT_PARSE_ERROR,
            hint="Checkpoint file may be corrupted. Session will use available data.",
        )


