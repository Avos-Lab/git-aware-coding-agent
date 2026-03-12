"""Tests for IngestPROrchestrator.

Covers: successful PR ingest, duplicate skip, GitHub API errors,
Memory API errors, JSON output mode, and config errors.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from avos_cli.commands.ingest_pr import IngestPROrchestrator
from avos_cli.exceptions import ResourceNotFoundError, UpstreamUnavailableError
from avos_cli.models.api import NoteResponse


def _make_config_json(
    avos_dir: Path,
    memory_id: str = "repo:org/test",
) -> None:
    """Write a minimal valid config.json for tests."""
    avos_dir.mkdir(parents=True, exist_ok=True)
    config = {
        "repo": "org/test",
        "memory_id": memory_id,
        "memory_id_session": f"{memory_id}-session",
        "api_url": "https://api.avos.ai",
        "api_key": "test-key",
        "schema_version": "2",
    }
    (avos_dir / "config.json").write_text(json.dumps(config))


def _make_pr_detail(pr_number: int = 123, title: str = "Test PR") -> dict:
    """Create a mock PR detail response."""
    return {
        "number": pr_number,
        "title": title,
        "user": {"login": "testuser"},
        "body": "PR description",
        "merged_at": "2026-03-07T10:00:00Z",
        "files": [
            {"filename": "src/main.py"},
            {"filename": "tests/test_main.py"},
        ],
        "comments": [
            {"user": {"login": "reviewer"}, "body": "LGTM"},
        ],
        "reviews": [
            {"user": {"login": "reviewer"}, "state": "APPROVED", "body": ""},
        ],
    }


class TestSuccessfulIngest:
    """PR is fetched, built, and stored successfully."""

    def test_stores_new_pr(self, tmp_path):
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        (repo_root / ".git").mkdir()
        avos_dir = repo_root / ".avos"
        _make_config_json(avos_dir)

        github_client = MagicMock()
        github_client.get_pr_details.return_value = _make_pr_detail(123, "Add feature X")

        memory_client = MagicMock()
        memory_client.add_memory.return_value = NoteResponse(
            note_id="note-abc-123",
            content="PR content",
            created_at="2026-03-07T10:00:00Z",
        )

        hash_store = MagicMock()
        hash_store.contains.return_value = False

        orchestrator = IngestPROrchestrator(
            memory_client=memory_client,
            github_client=github_client,
            hash_store=hash_store,
            repo_root=repo_root,
        )

        code = orchestrator.run("org/test", 123, json_output=False)

        assert code == 0
        github_client.get_pr_details.assert_called_once_with("org", "test", 123)
        memory_client.add_memory.assert_called_once()
        hash_store.add.assert_called_once()
        hash_store.save.assert_called_once()

    def test_json_output_stored(self, tmp_path, capsys):
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        (repo_root / ".git").mkdir()
        avos_dir = repo_root / ".avos"
        _make_config_json(avos_dir)

        github_client = MagicMock()
        github_client.get_pr_details.return_value = _make_pr_detail(456)

        memory_client = MagicMock()
        memory_client.add_memory.return_value = NoteResponse(
            note_id="note-xyz-789",
            content="PR content",
            created_at="2026-03-07T10:00:00Z",
        )

        hash_store = MagicMock()
        hash_store.contains.return_value = False

        orchestrator = IngestPROrchestrator(
            memory_client=memory_client,
            github_client=github_client,
            hash_store=hash_store,
            repo_root=repo_root,
        )

        code = orchestrator.run("org/test", 456, json_output=True)

        assert code == 0
        captured = capsys.readouterr()
        result = json.loads(captured.out)
        assert result["success"] is True
        assert result["data"]["pr_number"] == 456
        assert result["data"]["action"] == "stored"
        assert result["data"]["note_id"] == "note-xyz-789"


class TestDuplicateSkip:
    """PR is skipped if already ingested (hash exists)."""

    def test_skips_duplicate_pr(self, tmp_path):
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        (repo_root / ".git").mkdir()
        avos_dir = repo_root / ".avos"
        _make_config_json(avos_dir)

        github_client = MagicMock()
        github_client.get_pr_details.return_value = _make_pr_detail(123)

        memory_client = MagicMock()
        hash_store = MagicMock()
        hash_store.contains.return_value = True

        orchestrator = IngestPROrchestrator(
            memory_client=memory_client,
            github_client=github_client,
            hash_store=hash_store,
            repo_root=repo_root,
        )

        code = orchestrator.run("org/test", 123, json_output=False)

        assert code == 0
        memory_client.add_memory.assert_not_called()
        hash_store.add.assert_not_called()

    def test_json_output_skipped(self, tmp_path, capsys):
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        (repo_root / ".git").mkdir()
        avos_dir = repo_root / ".avos"
        _make_config_json(avos_dir)

        github_client = MagicMock()
        github_client.get_pr_details.return_value = _make_pr_detail(123)

        hash_store = MagicMock()
        hash_store.contains.return_value = True

        orchestrator = IngestPROrchestrator(
            memory_client=MagicMock(),
            github_client=github_client,
            hash_store=hash_store,
            repo_root=repo_root,
        )

        code = orchestrator.run("org/test", 123, json_output=True)

        assert code == 0
        captured = capsys.readouterr()
        result = json.loads(captured.out)
        assert result["success"] is True
        assert result["data"]["action"] == "skipped"
        assert result["data"]["reason"] == "already_ingested"


class TestGitHubAPIErrors:
    """Handles GitHub API failures gracefully."""

    def test_github_error_returns_2(self, tmp_path):
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        (repo_root / ".git").mkdir()
        avos_dir = repo_root / ".avos"
        _make_config_json(avos_dir)

        github_client = MagicMock()
        github_client.get_pr_details.side_effect = ResourceNotFoundError("PR not found")

        orchestrator = IngestPROrchestrator(
            memory_client=MagicMock(),
            github_client=github_client,
            hash_store=MagicMock(),
            repo_root=repo_root,
        )

        code = orchestrator.run("org/test", 999, json_output=False)
        assert code == 2

    def test_github_error_json_output(self, tmp_path, capsys):
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        (repo_root / ".git").mkdir()
        avos_dir = repo_root / ".avos"
        _make_config_json(avos_dir)

        github_client = MagicMock()
        github_client.get_pr_details.side_effect = ResourceNotFoundError("PR not found")

        orchestrator = IngestPROrchestrator(
            memory_client=MagicMock(),
            github_client=github_client,
            hash_store=MagicMock(),
            repo_root=repo_root,
        )

        code = orchestrator.run("org/test", 999, json_output=True)

        assert code == 2
        captured = capsys.readouterr()
        result = json.loads(captured.out)
        assert result["success"] is False
        assert result["error"]["code"] == "RESOURCE_NOT_FOUND"


class TestMemoryAPIErrors:
    """Handles Memory API failures gracefully."""

    def test_memory_error_returns_2(self, tmp_path):
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        (repo_root / ".git").mkdir()
        avos_dir = repo_root / ".avos"
        _make_config_json(avos_dir)

        github_client = MagicMock()
        github_client.get_pr_details.return_value = _make_pr_detail(123)

        memory_client = MagicMock()
        memory_client.add_memory.side_effect = UpstreamUnavailableError("API down")

        hash_store = MagicMock()
        hash_store.contains.return_value = False

        orchestrator = IngestPROrchestrator(
            memory_client=memory_client,
            github_client=github_client,
            hash_store=hash_store,
            repo_root=repo_root,
        )

        code = orchestrator.run("org/test", 123, json_output=False)
        assert code == 2


class TestConfigErrors:
    """Handles missing config gracefully."""

    def test_missing_config_returns_1(self, tmp_path):
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        (repo_root / ".git").mkdir()

        orchestrator = IngestPROrchestrator(
            memory_client=MagicMock(),
            github_client=MagicMock(),
            hash_store=MagicMock(),
            repo_root=repo_root,
        )

        code = orchestrator.run("org/test", 123, json_output=False)
        assert code == 1

    def test_invalid_slug_returns_1(self, tmp_path):
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        (repo_root / ".git").mkdir()
        avos_dir = repo_root / ".avos"
        _make_config_json(avos_dir)

        orchestrator = IngestPROrchestrator(
            memory_client=MagicMock(),
            github_client=MagicMock(),
            hash_store=MagicMock(),
            repo_root=repo_root,
        )

        code = orchestrator.run("invalid-slug", 123, json_output=False)
        assert code == 1
