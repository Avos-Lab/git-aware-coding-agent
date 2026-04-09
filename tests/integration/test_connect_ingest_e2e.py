"""End-to-end test for AVOS-011: Connect then Ingest flow.

Verifies the complete workflow with mocked external services:
1. Connect creates config
2. Ingest fetches and stores artifacts
3. Re-ingest is idempotent (no duplicate storage)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from avos_cli.commands.connect import ConnectOrchestrator
from avos_cli.commands.ingest import IngestOrchestrator
from avos_cli.config.hash_store import IngestHashStore
from avos_cli.config.lock import IngestLockManager
from avos_cli.models.api import NoteResponse, SearchResult


def _make_pr_detail(number: int) -> dict[str, Any]:
    return {
        "number": number,
        "title": f"PR #{number}: Feature",
        "user": {"login": "alice"},
        "state": "closed",
        "merged_at": "2026-02-10T12:00:00Z",
        "body": f"Description for PR #{number}",
        "comments": [{"body": "LGTM", "user": {"login": "bob"}}],
        "reviews": [{"body": "Approved", "user": {"login": "bob"}, "state": "APPROVED"}],
        "files": [{"filename": f"src/module_{number}.py", "additions": 20, "deletions": 5}],
    }


def _make_issue_detail(number: int) -> dict[str, Any]:
    return {
        "number": number,
        "title": f"Issue #{number}: Bug",
        "user": {"login": "charlie"},
        "state": "open",
        "labels": [{"name": "bug"}],
        "body": f"Bug description for #{number}",
        "comments": [{"body": "Confirmed", "user": {"login": "alice"}}],
    }


@pytest.fixture()
def e2e_repo(tmp_path: Path) -> Path:
    """Create a git repo with a README for doc ingestion."""
    repo = tmp_path / "e2e_repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    (repo / "README.md").write_text("# Test Project\nEnd-to-end test repo.")
    return repo


@pytest.fixture()
def mock_git_client() -> MagicMock:
    client = MagicMock()
    client.remote_origin.return_value = "testorg/testrepo"
    client.commit_log.return_value = [
        {"hash": "aaa111", "message": "feat: initial commit", "author": "alice", "date": "2026-02-01"},
        {"hash": "bbb222", "message": "fix: null check", "author": "bob", "date": "2026-02-05"},
    ]
    return client


@pytest.fixture()
def mock_github_client() -> MagicMock:
    client = MagicMock()
    client.validate_repo.return_value = True
    client.list_pull_requests.return_value = [
        {"number": 1, "updated_at": "2026-02-10T12:00:00Z"},
        {"number": 2, "updated_at": "2026-02-12T12:00:00Z"},
    ]
    client.get_pr_details.side_effect = lambda o, r, n: _make_pr_detail(n)
    client.list_issues.return_value = [
        _make_issue_detail(10),
    ]
    client.get_issue_details.side_effect = lambda o, r, n: _make_issue_detail(n)
    return client


@pytest.fixture()
def mock_memory_client() -> MagicMock:
    client = MagicMock()
    client.search.return_value = SearchResult(results=[], total_count=0)
    call_counter = [0]

    def _add_memory(**kwargs: Any) -> NoteResponse:
        call_counter[0] += 1
        return NoteResponse(
            note_id=f"note-{call_counter[0]}",
            content=kwargs.get("content", ""),
            created_at="2026-03-06T00:00:00Z",
        )

    client.add_memory.side_effect = _add_memory
    return client


class TestConnectThenIngestE2E:
    """Full connect -> ingest -> re-ingest flow."""

    def test_connect_creates_config(
        self,
        e2e_repo: Path,
        mock_git_client: MagicMock,
        mock_github_client: MagicMock,
        mock_memory_client: MagicMock,
    ):
        orch = ConnectOrchestrator(
            git_client=mock_git_client,
            github_client=mock_github_client,
            memory_client=mock_memory_client,
            repo_root=e2e_repo,
        )
        code = orch.run("testorg/testrepo")
        assert code == 0

        config_path = e2e_repo / ".avos" / "config.json"
        assert config_path.exists()
        config = json.loads(config_path.read_text())
        assert config["memory_id"] == "repo:testorg/testrepo"
        assert config["repo"] == "testorg/testrepo"
        assert config["schema_version"] == "2"
        assert "connected_at" in config

    def test_connect_sends_bootstrap_note(
        self,
        e2e_repo: Path,
        mock_git_client: MagicMock,
        mock_github_client: MagicMock,
        mock_memory_client: MagicMock,
    ):
        orch = ConnectOrchestrator(
            git_client=mock_git_client,
            github_client=mock_github_client,
            memory_client=mock_memory_client,
            repo_root=e2e_repo,
        )
        orch.run("testorg/testrepo")
        assert mock_memory_client.add_memory.call_count == 1
        call_kwargs = mock_memory_client.add_memory.call_args_list[0]
        assert "repo_connected" in str(call_kwargs)

    def test_ingest_stores_artifacts(
        self,
        e2e_repo: Path,
        mock_git_client: MagicMock,
        mock_github_client: MagicMock,
        mock_memory_client: MagicMock,
    ):
        connect_orch = ConnectOrchestrator(
            git_client=mock_git_client,
            github_client=mock_github_client,
            memory_client=mock_memory_client,
            repo_root=e2e_repo,
        )
        connect_orch.run("testorg/testrepo")
        mock_memory_client.add_memory.reset_mock()

        hash_store = IngestHashStore(e2e_repo / ".avos")
        hash_store.load()
        ingest_orch = IngestOrchestrator(
            memory_client=mock_memory_client,
            github_client=mock_github_client,
            git_client=mock_git_client,
            hash_store=hash_store,
            lock_manager=IngestLockManager(e2e_repo / ".avos"),
            repo_root=e2e_repo,
        )
        code = ingest_orch.run("testorg/testrepo", since_days=90)
        assert code == 0

        # 2 PRs + 1 issue + 2 commits + 1 doc (README.md) = 6
        assert mock_memory_client.add_memory.call_count == 6

    def test_ingest_artifact_content_structure(
        self,
        e2e_repo: Path,
        mock_git_client: MagicMock,
        mock_github_client: MagicMock,
        mock_memory_client: MagicMock,
    ):
        connect_orch = ConnectOrchestrator(
            git_client=mock_git_client,
            github_client=mock_github_client,
            memory_client=mock_memory_client,
            repo_root=e2e_repo,
        )
        connect_orch.run("testorg/testrepo")
        mock_memory_client.add_memory.reset_mock()

        hash_store = IngestHashStore(e2e_repo / ".avos")
        hash_store.load()
        ingest_orch = IngestOrchestrator(
            memory_client=mock_memory_client,
            github_client=mock_github_client,
            git_client=mock_git_client,
            hash_store=hash_store,
            lock_manager=IngestLockManager(e2e_repo / ".avos"),
            repo_root=e2e_repo,
        )
        ingest_orch.run("testorg/testrepo", since_days=90)

        all_contents = [
            str(c.kwargs.get("content", c.args[0] if c.args else ""))
            for c in mock_memory_client.add_memory.call_args_list
        ]
        type_headers = {"raw_pr_thread", "issue", "commit", "document"}
        for header in type_headers:
            assert any(f"[type: {header}]" in content for content in all_contents), (
                f"Missing artifact type: {header}"
            )

    def test_reingest_is_idempotent(
        self,
        e2e_repo: Path,
        mock_git_client: MagicMock,
        mock_github_client: MagicMock,
        mock_memory_client: MagicMock,
    ):
        connect_orch = ConnectOrchestrator(
            git_client=mock_git_client,
            github_client=mock_github_client,
            memory_client=mock_memory_client,
            repo_root=e2e_repo,
        )
        connect_orch.run("testorg/testrepo")
        mock_memory_client.add_memory.reset_mock()

        # First ingest
        hash_store = IngestHashStore(e2e_repo / ".avos")
        hash_store.load()
        ingest_orch = IngestOrchestrator(
            memory_client=mock_memory_client,
            github_client=mock_github_client,
            git_client=mock_git_client,
            hash_store=hash_store,
            lock_manager=IngestLockManager(e2e_repo / ".avos"),
            repo_root=e2e_repo,
        )
        code1 = ingest_orch.run("testorg/testrepo", since_days=90)
        assert code1 == 0
        first_run_count = mock_memory_client.add_memory.call_count
        assert first_run_count > 0

        # Second ingest (should be fully idempotent)
        mock_memory_client.add_memory.reset_mock()
        hash_store2 = IngestHashStore(e2e_repo / ".avos")
        hash_store2.load()
        ingest_orch2 = IngestOrchestrator(
            memory_client=mock_memory_client,
            github_client=mock_github_client,
            git_client=mock_git_client,
            hash_store=hash_store2,
            lock_manager=IngestLockManager(e2e_repo / ".avos"),
            repo_root=e2e_repo,
        )
        code2 = ingest_orch2.run("testorg/testrepo", since_days=90)
        assert code2 == 0
        assert mock_memory_client.add_memory.call_count == 0

    def test_hash_store_persisted_between_runs(
        self,
        e2e_repo: Path,
        mock_git_client: MagicMock,
        mock_github_client: MagicMock,
        mock_memory_client: MagicMock,
    ):
        connect_orch = ConnectOrchestrator(
            git_client=mock_git_client,
            github_client=mock_github_client,
            memory_client=mock_memory_client,
            repo_root=e2e_repo,
        )
        connect_orch.run("testorg/testrepo")

        hash_store = IngestHashStore(e2e_repo / ".avos")
        hash_store.load()
        ingest_orch = IngestOrchestrator(
            memory_client=mock_memory_client,
            github_client=mock_github_client,
            git_client=mock_git_client,
            hash_store=hash_store,
            lock_manager=IngestLockManager(e2e_repo / ".avos"),
            repo_root=e2e_repo,
        )
        ingest_orch.run("testorg/testrepo", since_days=90)

        hash_file = e2e_repo / ".avos" / "ingest_hashes.json"
        assert hash_file.exists()
        hashes = json.loads(hash_file.read_text())
        assert len(hashes) == 6  # 2 PRs + 1 issue + 2 commits + 1 doc

    def test_lock_released_after_ingest(
        self,
        e2e_repo: Path,
        mock_git_client: MagicMock,
        mock_github_client: MagicMock,
        mock_memory_client: MagicMock,
    ):
        connect_orch = ConnectOrchestrator(
            git_client=mock_git_client,
            github_client=mock_github_client,
            memory_client=mock_memory_client,
            repo_root=e2e_repo,
        )
        connect_orch.run("testorg/testrepo")

        hash_store = IngestHashStore(e2e_repo / ".avos")
        hash_store.load()
        ingest_orch = IngestOrchestrator(
            memory_client=mock_memory_client,
            github_client=mock_github_client,
            git_client=mock_git_client,
            hash_store=hash_store,
            lock_manager=IngestLockManager(e2e_repo / ".avos"),
            repo_root=e2e_repo,
        )
        ingest_orch.run("testorg/testrepo", since_days=90)
        assert not (e2e_repo / ".avos" / "ingest.lock").exists()
