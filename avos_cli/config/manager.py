"""Configuration manager for AVOS CLI.

Handles repo root detection, config load/save with environment variable
overlay, and .avos directory management. Config resolution priority:
env vars > config file > defaults.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from avos_cli.config.state import atomic_write, read_json_safe
from avos_cli.exceptions import (
    ConfigurationNotInitializedError,
    ConfigurationValidationError,
    RepositoryContextError,
)
from avos_cli.models.config import RepoConfig

_CONFIG_FILENAME = "config.json"
_AVOS_DIR = ".avos"


def find_repo_root(start: Path) -> Path:
    """Walk up from start directory to find the Git repository root.

    Detects both standard repos (.git directory) and worktrees (.git file).

    Args:
        start: Directory to start searching from.

    Returns:
        Path to the repository root.

    Raises:
        RepositoryContextError: If no .git is found.
    """
    current = start.resolve()
    while True:
        git_path = current / ".git"
        if git_path.exists():
            return current
        parent = current.parent
        if parent == current:
            break
        current = parent
    raise RepositoryContextError(f"No Git repository found at or above: {start}")


def load_config(repo_root: Path) -> RepoConfig:
    """Load repository configuration from .avos/config.json with env overlay.

    Resolution priority: env vars > config file values > defaults.

    Args:
        repo_root: Path to the repository root (must contain .avos/).

    Returns:
        Validated RepoConfig instance.

    Raises:
        ConfigurationNotInitializedError: If .avos/config.json doesn't exist.
        ConfigurationValidationError: If config is malformed or invalid.
    """
    config_path = repo_root / _AVOS_DIR / _CONFIG_FILENAME

    if not config_path.exists():
        raise ConfigurationNotInitializedError()

    raw_data = read_json_safe(config_path)
    if raw_data is None:
        raise ConfigurationValidationError(
            f"Config file is corrupt or unreadable: {config_path}"
        )

    data: dict[str, Any] = dict(raw_data)
    _apply_env_overlay(data)

    try:
        return RepoConfig(**data)
    except ValidationError as e:
        raise ConfigurationValidationError(
            f"Invalid configuration in {config_path}: {e}"
        ) from e


def connected_repo_slug(repo_root: Path) -> str | None:
    """Return the repository slug persisted by ``avos connect`` (authoritative context).

    After a successful connect, ``repo`` in ``.avos/config.json`` is the
    canonical ``org/repo`` for this working copy. Pass it as ``default_repo``
    to :class:`~avos_cli.parsers.reference_parser.ReferenceParser` when the
    user omits owner/repo (e.g. ``PR #1245``, ``Commit 8c3a1b2``).

    Args:
        repo_root: Git repository root containing ``.avos/config.json``.

    Returns:
        Connected slug, or ``None`` if the project was never connected.

    Raises:
        ConfigurationValidationError: If the config file exists but is invalid.
    """
    try:
        return load_config(repo_root).repo
    except ConfigurationNotInitializedError:
        return None


def _apply_env_overlay(data: dict[str, Any]) -> None:
    """Apply environment variable overrides to config data dict.

    Env vars take precedence over file values. Supports:
    AVOS_API_KEY, AVOS_API_URL, GITHUB_TOKEN, AVOS_DEVELOPER,
    AVOS_LLM_PROVIDER, AVOS_LLM_MODEL.
    """
    env_map = {
        "AVOS_API_KEY": "api_key",
        "AVOS_API_URL": "api_url",
        "GITHUB_TOKEN": "github_token",
        "AVOS_DEVELOPER": "developer",
    }
    for env_var, config_key in env_map.items():
        value = os.environ.get(env_var)
        if value is not None:
            data[config_key] = value

    llm_data = data.get("llm", {})
    if not isinstance(llm_data, dict):
        llm_data = {}
    llm_provider_env = os.environ.get("AVOS_LLM_PROVIDER")
    llm_model_env = os.environ.get("AVOS_LLM_MODEL")
    if llm_provider_env:
        llm_data["provider"] = llm_provider_env
    if llm_model_env:
        llm_data["model"] = llm_model_env
    # When provider is openai (from file or env) and model is Anthropic default,
    # use gpt-4o to avoid passing claude-* to OpenAI
    provider = llm_data.get("provider", "anthropic")
    if provider.lower() == "openai" and not llm_model_env:
        model = llm_data.get("model", "claude-sonnet-4-5-20250929")
        if model.startswith("claude-"):
            llm_data["model"] = "gpt-4o"
    data["llm"] = llm_data


def save_config(repo_root: Path, config_data: dict[str, Any]) -> None:
    """Save configuration data to .avos/config.json atomically.

    Creates the .avos directory if it doesn't exist. Uses atomic
    write with restrictive permissions (0o600).

    Args:
        repo_root: Path to the repository root.
        config_data: Configuration dictionary to persist.
    """
    avos_dir = repo_root / _AVOS_DIR
    avos_dir.mkdir(parents=True, exist_ok=True)
    config_path = avos_dir / _CONFIG_FILENAME
    content = json.dumps(config_data, indent=2, sort_keys=True)
    atomic_write(config_path, content, permissions=0o600)
