"""Configuration and state models for AVOS CLI.

Defines RepoConfig (repository-scoped runtime configuration),
SessionState (active session lifecycle), WatchState (watch loop state),
and LLMConfig (LLM provider settings).
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, SecretStr


class LLMConfig(BaseModel):
    """LLM provider configuration.

    Args:
        provider: LLM provider name (e.g. 'anthropic', 'openai').
        model: Model identifier string.
    """

    model_config = ConfigDict(frozen=True)

    provider: str = "anthropic"
    model: str = "claude-sonnet-4-5-20250929"


class RepoConfig(BaseModel):
    """Repository-scoped runtime configuration.

    Loaded from .avos/config.json with env var overlay.
    Sensitive fields use SecretStr to prevent accidental exposure.

    Args:
        repo: Repository slug in 'org/repo' format.
        memory_id: Deterministic memory identifier, format 'repo:org/repo'.
        api_url: Base URL for the Avos Memory API.
        api_key: API key for Avos Memory (secret).
        github_token: GitHub personal access token (secret, optional).
        developer: Developer display name (defaults to git user.name).
        llm: LLM provider configuration.
        connected_at: UTC timestamp when the repo was first connected.
        schema_version: Config schema version for forward compatibility.
    """

    model_config = ConfigDict(frozen=True)

    repo: str
    memory_id: str
    api_url: str
    api_key: SecretStr
    github_token: SecretStr | None = None
    developer: str | None = None
    llm: LLMConfig = LLMConfig()
    connected_at: datetime | None = None
    schema_version: str = "1"


class SessionState(BaseModel):
    """Active session lifecycle state.

    Written to .avos/session.json by session start,
    read by session end. Forward-compatible contract frozen in Sprint 1.

    Args:
        session_id: Unique session identifier.
        goal: Developer-provided session goal description.
        start_time: UTC timestamp when session started.
        branch: Git branch active at session start.
        memory_id: Associated memory identifier.
    """

    model_config = ConfigDict(frozen=True)

    session_id: str
    goal: str
    start_time: datetime
    branch: str
    memory_id: str


class WatchState(BaseModel):
    """Watch loop state for publish watermarking.

    Written to .avos/watch_state.json by the watch process.
    Forward-compatible contract frozen in Sprint 1.

    Args:
        developer: Developer identity string.
        branch: Current Git branch.
        last_publish_time: UTC timestamp of last WIP artifact publish.
        files_tracked: List of file paths currently being tracked.
    """

    model_config = ConfigDict(frozen=True)

    developer: str
    branch: str
    last_publish_time: datetime
    files_tracked: list[str]


class WatcherPidState(BaseModel):
    """PID file state for the session watcher process.

    Written to .avos/watcher.pid by session start.
    Read by session end for ownership verification before SIGTERM.

    Args:
        pid: OS process ID of the watcher.
        started_at: UTC timestamp when the watcher was spawned.
        session_id: Session identifier for ownership verification.
    """

    model_config = ConfigDict(frozen=True)

    pid: int
    started_at: datetime
    session_id: str


class SessionCheckpoint(BaseModel):
    """Single checkpoint record from the watcher process.

    Appended as one JSON line per interval to .avos/session_checkpoints.jsonl.
    Captures metadata-only activity snapshot -- never raw source code.

    Args:
        timestamp: UTC timestamp of the checkpoint.
        session_id: Owning session identifier.
        branch: Git branch at checkpoint time.
        files_modified: Repository-relative paths modified since last checkpoint.
        diff_stats: Aggregate line counts, e.g. {"added": 10, "removed": 3}.
        test_commands_detected: Command names (no arguments) observed running.
        errors_detected: Coarse error signatures observed.
    """

    model_config = ConfigDict(frozen=True)

    timestamp: datetime
    session_id: str
    branch: str
    files_modified: list[str] = []
    diff_stats: dict[str, int] = {}
    test_commands_detected: list[str] = []
    errors_detected: list[str] = []
