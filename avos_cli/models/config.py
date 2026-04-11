"""Configuration and state models for AVOS CLI.

Defines RepoConfig (repository-scoped runtime configuration)
and LLMConfig (LLM provider settings).
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, SecretStr


class LLMConfig(BaseModel):
    """LLM provider configuration.

    Args:
        provider: LLM provider name (e.g. 'openai', 'anthropic').
        model: Model identifier string.
    """

    model_config = ConfigDict(frozen=True)

    provider: str = "openai"
    model: str = "gpt-4o"


class RepoConfig(BaseModel):
    """Repository-scoped runtime configuration.

    Loaded from .avos/config.json with env var overlay.
    Sensitive fields use SecretStr to prevent accidental exposure.

    Args:
        repo: Repository slug in 'org/repo' format.
        memory_id: Memory identifier - 'repo:org/repo' for PR history, commits, issues, docs.
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
