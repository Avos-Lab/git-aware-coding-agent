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
    """

    model_config = ConfigDict(frozen=True)

    repo: str
    memory_id: str
    api_url: str
    api_key: SecretStr
    github_token: SecretStr | None = None
    developer: str | None = None
    llm: LLMConfig = LLMConfig()


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
