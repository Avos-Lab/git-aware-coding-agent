"""Tests for HookSyncOrchestrator.

Covers commit range extraction, artifact building, hash deduplication,
memory insertion, and error handling during git push sync.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from avos_cli.commands.hook_sync import HookSyncOrchestrator, HookSyncResult
from avos_cli.config.hash_store import IngestHashStore
from avos_cli.exceptions import RepositoryContextError
from avos_cli.models.api import NoteResponse


def _make_config_json(
    avos_dir: Path,
    repo: str = "myorg/myrepo",
    memory_id: str = "repo:myorg/myrepo",
) -> None:
    """Write a minimal valid config.json for tests."""
    avos_dir.mkdir(parents=True, exist_ok=True)
    config = {
        "repo": repo,
        "memory_id": memory_id,
        "memory_id_session": f"{memory_id}-session",
        "api_url": "https://api.avos.ai",
        "api_key": "sk_test",
        "schema_version": "2",
    }
    (avos_dir / "config.json").write_text(json.dumps(config))


@pytest.fixture()
def git_repo(tmp_path: Path) -> Path:
    """Create a minimal git repo structure with avos config."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    avos = repo / ".avos"
    _make_config_json(avos)
    return repo


@pytest.fixture()
def mock_memory_client() -> MagicMock:
    """Mock memory client that returns success."""
    client = MagicMock()
    client.add_memory.return_value = NoteResponse(
        note_id="note-1", content="stored", created_at="2026-03-06T00:00:00Z"
    )
    return client


@pytest.fixture()
def mock_git_client() -> MagicMock:
    """Mock git client with commit_log_range."""
    client = MagicMock()
    client.commit_log_range.return_value = [
        {"hash": "abc123def456", "message": "feat: add login", "author": "dev", "date": "2026-03-01T10:00:00Z"},
        {"hash": "def456abc789", "message": "fix: typo", "author": "dev", "date": "2026-03-01T11:00:00Z"},
    ]
    return client


@pytest.fixture()
def hash_store(git_repo: Path) -> IngestHashStore:
    """Fresh hash store for deduplication tests."""
    store = IngestHashStore(git_repo / ".avos")
    store.load()
    return store


@pytest.fixture()
def orchestrator(
    git_repo: Path,
    mock_memory_client: MagicMock,
    mock_git_client: MagicMock,
    hash_store: IngestHashStore,
) -> HookSyncOrchestrator:
    """Create orchestrator with mocked dependencies."""
    return HookSyncOrchestrator(
        memory_client=mock_memory_client,
        git_client=mock_git_client,
        hash_store=hash_store,
        repo_root=git_repo,
    )


class TestHappyPath:
    """Hook sync succeeds under normal conditions."""

    def test_syncs_commits_returns_0(self, orchestrator: HookSyncOrchestrator):
        code = orchestrator.run("old_sha_123", "new_sha_456")
        assert code == 0

    def test_stores_commit_artifacts(
        self, orchestrator: HookSyncOrchestrator, mock_memory_client: MagicMock
    ):
        orchestrator.run("old_sha", "new_sha")
        assert mock_memory_client.add_memory.call_count == 2

    def test_artifact_format_matches_ingest(
        self, orchestrator: HookSyncOrchestrator, mock_memory_client: MagicMock
    ):
        """Verify artifact text matches avos ingest commit format."""
        orchestrator.run("old_sha", "new_sha")
        call_args = mock_memory_client.add_memory.call_args_list[0]
        content = call_args.kwargs.get("content") or call_args[1].get("content")

        assert "[type: commit]" in content
        assert "[repo: myorg/myrepo]" in content
        assert "[hash: abc123def456]" in content
        assert "[author: dev]" in content
        assert "Message: feat: add login" in content

    def test_saves_hash_store_after_sync(
        self, orchestrator: HookSyncOrchestrator, git_repo: Path
    ):
        orchestrator.run("old_sha", "new_sha")
        assert (git_repo / ".avos" / "ingest_hashes.json").exists()

    def test_hash_store_contains_synced_commits(
        self, orchestrator: HookSyncOrchestrator, hash_store: IngestHashStore
    ):
        orchestrator.run("old_sha", "new_sha")
        assert hash_store.count() == 2


class TestDeduplication:
    """Hash store prevents duplicate insertions."""

    def test_skips_already_synced_commits(
        self,
        git_repo: Path,
        mock_memory_client: MagicMock,
        mock_git_client: MagicMock,
    ):
        """Second run should skip all commits."""
        hash_store1 = IngestHashStore(git_repo / ".avos")
        hash_store1.load()

        orch1 = HookSyncOrchestrator(
            memory_client=mock_memory_client,
            git_client=mock_git_client,
            hash_store=hash_store1,
            repo_root=git_repo,
        )
        orch1.run("old", "new")

        mock_memory_client.reset_mock()
        hash_store2 = IngestHashStore(git_repo / ".avos")
        hash_store2.load()

        orch2 = HookSyncOrchestrator(
            memory_client=mock_memory_client,
            git_client=mock_git_client,
            hash_store=hash_store2,
            repo_root=git_repo,
        )
        orch2.run("old", "new")

        assert mock_memory_client.add_memory.call_count == 0

    def test_partial_dedup_new_commits_only(
        self,
        git_repo: Path,
        mock_memory_client: MagicMock,
        mock_git_client: MagicMock,
    ):
        """Only new commits are synced when some already exist."""
        hash_store = IngestHashStore(git_repo / ".avos")
        hash_store.load()

        orch = HookSyncOrchestrator(
            memory_client=mock_memory_client,
            git_client=mock_git_client,
            hash_store=hash_store,
            repo_root=git_repo,
        )
        orch.run("old", "new")

        mock_memory_client.reset_mock()
        mock_git_client.commit_log_range.return_value = [
            {"hash": "abc123def456", "message": "feat: add login", "author": "dev", "date": "2026-03-01T10:00:00Z"},
            {"hash": "new_commit_xyz", "message": "new: feature", "author": "dev", "date": "2026-03-02T10:00:00Z"},
        ]

        hash_store2 = IngestHashStore(git_repo / ".avos")
        hash_store2.load()
        orch2 = HookSyncOrchestrator(
            memory_client=mock_memory_client,
            git_client=mock_git_client,
            hash_store=hash_store2,
            repo_root=git_repo,
        )
        orch2.run("old", "new")

        assert mock_memory_client.add_memory.call_count == 1


class TestNullShaHandling:
    """Handles null SHAs for new branches and deletions."""

    def test_null_old_sha_treated_as_empty(
        self, orchestrator: HookSyncOrchestrator, mock_git_client: MagicMock
    ):
        """Null SHA (40 zeros) should be treated as empty string."""
        null_sha = "0" * 40
        orchestrator.run(null_sha, "new_sha_456")

        call_args = mock_git_client.commit_log_range.call_args
        old_sha_arg = call_args[0][1] if len(call_args[0]) > 1 else call_args.kwargs.get("old_sha")
        assert old_sha_arg == ""

    def test_null_new_sha_skips_sync(
        self, orchestrator: HookSyncOrchestrator, mock_git_client: MagicMock
    ):
        """Null new SHA (branch delete) should skip sync."""
        null_sha = "0" * 40
        code = orchestrator.run("old_sha", null_sha)

        assert code == 0
        mock_git_client.commit_log_range.assert_not_called()

    def test_empty_new_sha_skips_sync(
        self, orchestrator: HookSyncOrchestrator, mock_git_client: MagicMock
    ):
        code = orchestrator.run("old_sha", "")
        assert code == 0
        mock_git_client.commit_log_range.assert_not_called()


class TestNoConfig:
    """Gracefully handles missing avos config."""

    def test_no_config_returns_0(self, tmp_path: Path, mock_memory_client: MagicMock, mock_git_client: MagicMock):
        """Should silently succeed when no avos config exists."""
        repo = tmp_path / "no_config_repo"
        repo.mkdir()
        (repo / ".git").mkdir()
        (repo / ".avos").mkdir()

        hash_store = IngestHashStore(repo / ".avos")
        hash_store.load()

        orch = HookSyncOrchestrator(
            memory_client=mock_memory_client,
            git_client=mock_git_client,
            hash_store=hash_store,
            repo_root=repo,
        )
        code = orch.run("old", "new")

        assert code == 0
        mock_memory_client.add_memory.assert_not_called()


class TestEmptyCommitRange:
    """Handles empty commit ranges gracefully."""

    def test_no_commits_in_range_returns_0(
        self, orchestrator: HookSyncOrchestrator, mock_git_client: MagicMock, mock_memory_client: MagicMock
    ):
        mock_git_client.commit_log_range.return_value = []
        code = orchestrator.run("old", "new")

        assert code == 0
        mock_memory_client.add_memory.assert_not_called()


class TestErrorHandling:
    """Handles errors without blocking git push."""

    def test_git_error_returns_0(
        self, orchestrator: HookSyncOrchestrator, mock_git_client: MagicMock
    ):
        """Git errors should not block push."""
        mock_git_client.commit_log_range.side_effect = RepositoryContextError("Not a repo")
        code = orchestrator.run("old", "new")
        assert code == 0

    def test_memory_error_continues_other_commits(
        self, orchestrator: HookSyncOrchestrator, mock_memory_client: MagicMock
    ):
        """Memory errors on one commit should not stop others."""
        call_count = [0]

        def fail_first(**kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise Exception("Network error")
            return NoteResponse(note_id="ok", content="ok", created_at="2026-03-06T00:00:00Z")

        mock_memory_client.add_memory.side_effect = fail_first
        code = orchestrator.run("old", "new")

        assert code == 0
        assert mock_memory_client.add_memory.call_count == 2

    def test_all_commits_fail_still_returns_0(
        self, orchestrator: HookSyncOrchestrator, mock_memory_client: MagicMock
    ):
        """Even if all commits fail, push should not be blocked."""
        mock_memory_client.add_memory.side_effect = Exception("All fail")
        code = orchestrator.run("old", "new")
        assert code == 0


class TestHookSyncResult:
    """HookSyncResult dataclass behavior."""

    def test_defaults(self):
        r = HookSyncResult()
        assert r.processed == 0
        assert r.stored == 0
        assert r.skipped == 0
        assert r.failed == 0

    def test_counts_accumulate(self):
        r = HookSyncResult(processed=5, stored=3, skipped=1, failed=1)
        assert r.processed == 5
        assert r.stored == 3
        assert r.skipped == 1
        assert r.failed == 1


class TestMemoryIdUsage:
    """Verifies correct memory_id is used."""

    def test_uses_config_memory_id(
        self, orchestrator: HookSyncOrchestrator, mock_memory_client: MagicMock
    ):
        orchestrator.run("old", "new")
        call_args = mock_memory_client.add_memory.call_args_list[0]
        memory_id = call_args.kwargs.get("memory_id") or call_args[1].get("memory_id")
        assert memory_id == "repo:myorg/myrepo"


class TestCommitLogRangeCall:
    """Verifies correct parameters passed to git client."""

    def test_passes_sha_range_to_git_client(
        self, orchestrator: HookSyncOrchestrator, mock_git_client: MagicMock, git_repo: Path
    ):
        orchestrator.run("old_sha_abc", "new_sha_xyz")
        mock_git_client.commit_log_range.assert_called_once_with(
            git_repo, "old_sha_abc", "new_sha_xyz"
        )
