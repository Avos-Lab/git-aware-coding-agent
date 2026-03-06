"""Tests for AVOS-003: Configuration manager.

Covers repo root detection, config load/save, env var overlay,
missing config errors, malformed JSON, and atomic file I/O.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from avos_cli.config.manager import find_repo_root, load_config, save_config
from avos_cli.config.state import atomic_write, read_json_safe
from avos_cli.exceptions import (
    ConfigurationNotInitializedError,
    ConfigurationValidationError,
    RepositoryContextError,
)


@pytest.fixture()
def git_repo(tmp_path: Path) -> Path:
    """Create a minimal git repo structure."""
    (tmp_path / ".git").mkdir()
    return tmp_path


@pytest.fixture()
def avos_dir(git_repo: Path) -> Path:
    """Create .avos directory in a git repo."""
    avos = git_repo / ".avos"
    avos.mkdir()
    return avos


@pytest.fixture()
def valid_config_data() -> dict:
    return {
        "repo": "org/repo",
        "memory_id": "repo:org/repo",
        "api_url": "https://api.example.com",
        "api_key": "sk_test_key_12345",
    }


class TestFindRepoRoot:
    def test_finds_root_from_repo_dir(self, git_repo: Path):
        root = find_repo_root(git_repo)
        assert root == git_repo

    def test_finds_root_from_subdirectory(self, git_repo: Path):
        sub = git_repo / "src" / "deep"
        sub.mkdir(parents=True)
        root = find_repo_root(sub)
        assert root == git_repo

    def test_raises_when_no_git_dir(self, tmp_path: Path):
        no_git = tmp_path / "not_a_repo"
        no_git.mkdir()
        with pytest.raises(RepositoryContextError):
            find_repo_root(no_git)

    def test_finds_root_with_worktree(self, tmp_path: Path):
        # Worktrees have a .git file (not directory) pointing to the real .git
        (tmp_path / ".git").write_text("gitdir: /some/path/.git/worktrees/branch")
        root = find_repo_root(tmp_path)
        assert root == tmp_path


class TestLoadConfig:
    def test_loads_valid_config(self, avos_dir: Path, valid_config_data: dict):
        config_path = avos_dir / "config.json"
        config_path.write_text(json.dumps(valid_config_data))

        cfg = load_config(avos_dir.parent)
        assert cfg.repo == "org/repo"
        assert cfg.memory_id == "repo:org/repo"
        assert cfg.api_key.get_secret_value() == "sk_test_key_12345"

    def test_raises_when_config_missing(self, git_repo: Path):
        with pytest.raises(ConfigurationNotInitializedError) as exc_info:
            load_config(git_repo)
        assert "avos connect" in (exc_info.value.hint or "")

    def test_raises_on_malformed_json(self, avos_dir: Path):
        config_path = avos_dir / "config.json"
        config_path.write_text("{invalid json")
        with pytest.raises(ConfigurationValidationError):
            load_config(avos_dir.parent)

    def test_raises_on_invalid_schema(self, avos_dir: Path):
        config_path = avos_dir / "config.json"
        config_path.write_text(json.dumps({"repo": "org/repo"}))
        with pytest.raises(ConfigurationValidationError):
            load_config(avos_dir.parent)

    def test_env_var_overrides_api_key(
        self, avos_dir: Path, valid_config_data: dict, monkeypatch: pytest.MonkeyPatch
    ):
        config_path = avos_dir / "config.json"
        config_path.write_text(json.dumps(valid_config_data))
        monkeypatch.setenv("AVOS_API_KEY", "sk_env_override")

        cfg = load_config(avos_dir.parent)
        assert cfg.api_key.get_secret_value() == "sk_env_override"

    def test_env_var_overrides_api_url(
        self, avos_dir: Path, valid_config_data: dict, monkeypatch: pytest.MonkeyPatch
    ):
        config_path = avos_dir / "config.json"
        config_path.write_text(json.dumps(valid_config_data))
        monkeypatch.setenv("AVOS_API_URL", "https://override.example.com")

        cfg = load_config(avos_dir.parent)
        assert cfg.api_url == "https://override.example.com"

    def test_env_var_overrides_github_token(
        self, avos_dir: Path, valid_config_data: dict, monkeypatch: pytest.MonkeyPatch
    ):
        config_path = avos_dir / "config.json"
        config_path.write_text(json.dumps(valid_config_data))
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_env_token")

        cfg = load_config(avos_dir.parent)
        assert cfg.github_token is not None
        assert cfg.github_token.get_secret_value() == "ghp_env_token"

    def test_env_var_overrides_developer(
        self, avos_dir: Path, valid_config_data: dict, monkeypatch: pytest.MonkeyPatch
    ):
        config_path = avos_dir / "config.json"
        config_path.write_text(json.dumps(valid_config_data))
        monkeypatch.setenv("AVOS_DEVELOPER", "env_dev")

        cfg = load_config(avos_dir.parent)
        assert cfg.developer == "env_dev"

    def test_env_var_overrides_llm_settings(
        self, avos_dir: Path, valid_config_data: dict, monkeypatch: pytest.MonkeyPatch
    ):
        config_path = avos_dir / "config.json"
        config_path.write_text(json.dumps(valid_config_data))
        monkeypatch.setenv("AVOS_LLM_PROVIDER", "openai")
        monkeypatch.setenv("AVOS_LLM_MODEL", "gpt-4")

        cfg = load_config(avos_dir.parent)
        assert cfg.llm.provider == "openai"
        assert cfg.llm.model == "gpt-4"

    def test_config_with_github_token(self, avos_dir: Path, valid_config_data: dict):
        valid_config_data["github_token"] = "ghp_file_token"
        config_path = avos_dir / "config.json"
        config_path.write_text(json.dumps(valid_config_data))

        cfg = load_config(avos_dir.parent)
        assert cfg.github_token is not None
        assert cfg.github_token.get_secret_value() == "ghp_file_token"

    def test_config_with_llm_settings(self, avos_dir: Path, valid_config_data: dict):
        valid_config_data["llm"] = {"provider": "openai", "model": "gpt-4"}
        config_path = avos_dir / "config.json"
        config_path.write_text(json.dumps(valid_config_data))

        cfg = load_config(avos_dir.parent)
        assert cfg.llm.provider == "openai"


class TestSaveConfig:
    def test_save_creates_avos_dir(self, git_repo: Path, valid_config_data: dict):
        save_config(git_repo, valid_config_data)
        assert (git_repo / ".avos" / "config.json").exists()

    def test_save_writes_valid_json(self, git_repo: Path, valid_config_data: dict):
        save_config(git_repo, valid_config_data)
        content = (git_repo / ".avos" / "config.json").read_text()
        data = json.loads(content)
        assert data["repo"] == "org/repo"

    def test_save_overwrites_existing(self, avos_dir: Path, valid_config_data: dict):
        save_config(avos_dir.parent, valid_config_data)
        valid_config_data["developer"] = "new_dev"
        save_config(avos_dir.parent, valid_config_data)

        content = (avos_dir / "config.json").read_text()
        data = json.loads(content)
        assert data["developer"] == "new_dev"

    def test_save_restrictive_permissions(self, git_repo: Path, valid_config_data: dict):
        save_config(git_repo, valid_config_data)
        config_path = git_repo / ".avos" / "config.json"
        mode = oct(config_path.stat().st_mode & 0o777)
        assert mode == "0o600"


class TestAtomicWrite:
    def test_writes_content(self, tmp_path: Path):
        target = tmp_path / "test.json"
        atomic_write(target, '{"key": "value"}')
        assert target.read_text() == '{"key": "value"}'

    def test_overwrites_existing(self, tmp_path: Path):
        target = tmp_path / "test.json"
        target.write_text("old")
        atomic_write(target, "new")
        assert target.read_text() == "new"


class TestReadJsonSafe:
    def test_reads_valid_json(self, tmp_path: Path):
        target = tmp_path / "test.json"
        target.write_text('{"key": "value"}')
        data = read_json_safe(target)
        assert data == {"key": "value"}

    def test_returns_none_for_missing_file(self, tmp_path: Path):
        target = tmp_path / "missing.json"
        data = read_json_safe(target)
        assert data is None

    def test_quarantines_corrupt_file(self, tmp_path: Path):
        target = tmp_path / "corrupt.json"
        target.write_text("{bad json")
        data = read_json_safe(target)
        assert data is None
        # Original file should be quarantined
        corrupt_files = list(tmp_path.glob("corrupt.json.corrupt.*"))
        assert len(corrupt_files) == 1
