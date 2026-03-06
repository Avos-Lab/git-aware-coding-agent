"""Tests for AVOS-010: IngestOrchestrator.

Covers all 4 stages (PRs, issues, commits, docs), idempotency,
partial failure, lock conflicts, exit codes, and edge cases.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from avos_cli.commands.ingest import IngestOrchestrator, IngestStageResult, resolve_exit_code
from avos_cli.config.hash_store import IngestHashStore
from avos_cli.config.lock import IngestLockManager
from avos_cli.exceptions import UpstreamUnavailableError
from avos_cli.models.api import NoteResponse


def _make_pr_data(number: int = 101) -> dict[str, Any]:
    """Create a mock PR detail dict matching GitHubClient.get_pr_details output."""
    return {
        "number": number,
        "title": f"PR #{number}",
        "user": {"login": "dev-alice"},
        "state": "closed",
        "merged_at": "2026-02-15T10:00:00Z",
        "body": "Description text",
        "comments": [{"body": "LGTM", "user": {"login": "dev-bob"}}],
        "reviews": [{"body": "Approved", "user": {"login": "dev-bob"}, "state": "APPROVED"}],
        "files": [{"filename": "src/main.py", "additions": 10, "deletions": 2}],
    }


def _make_issue_data(number: int = 50) -> dict[str, Any]:
    """Create a mock issue detail dict matching GitHubClient.get_issue_details output."""
    return {
        "number": number,
        "title": f"Issue #{number}",
        "user": {"login": "dev-alice"},
        "state": "open",
        "labels": [{"name": "bug"}],
        "body": "Bug description",
        "comments": [{"body": "Confirmed", "user": {"login": "dev-bob"}}],
    }


@pytest.fixture()
def git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    avos = repo / ".avos"
    avos.mkdir()
    config = {
        "repo": "myorg/myrepo",
        "memory_id": "repo:myorg/myrepo",
        "api_url": "https://api.avos.ai",
        "api_key": "sk_test",
        "schema_version": "1",
    }
    (avos / "config.json").write_text(json.dumps(config))
    return repo


@pytest.fixture()
def mock_memory_client() -> MagicMock:
    client = MagicMock()
    client.add_memory.return_value = NoteResponse(
        note_id="note-1", content="stored", created_at="2026-03-06T00:00:00Z"
    )
    return client


@pytest.fixture()
def mock_github_client() -> MagicMock:
    client = MagicMock()
    client.list_pull_requests.return_value = [
        {"number": 101, "updated_at": "2026-02-15T10:00:00Z"},
        {"number": 102, "updated_at": "2026-02-20T14:30:00Z"},
    ]
    client.get_pr_details.side_effect = lambda o, r, n: _make_pr_data(n)
    client.list_issues.return_value = [
        _make_issue_data(50),
        _make_issue_data(51),
    ]
    client.get_issue_details.side_effect = lambda o, r, n: _make_issue_data(n)
    return client


@pytest.fixture()
def mock_git_client() -> MagicMock:
    client = MagicMock()
    client.commit_log.return_value = [
        {"hash": "abc123", "message": "fix: retry logic", "author": "dev", "date": "2026-02-15"},
        {"hash": "def456", "message": "feat: add metrics", "author": "dev", "date": "2026-02-16"},
    ]
    return client


@pytest.fixture()
def hash_store(git_repo: Path) -> IngestHashStore:
    store = IngestHashStore(git_repo / ".avos")
    store.load()
    return store


@pytest.fixture()
def lock_mgr(git_repo: Path) -> IngestLockManager:
    return IngestLockManager(git_repo / ".avos")


@pytest.fixture()
def orchestrator(
    git_repo: Path,
    mock_memory_client: MagicMock,
    mock_github_client: MagicMock,
    mock_git_client: MagicMock,
    hash_store: IngestHashStore,
    lock_mgr: IngestLockManager,
) -> IngestOrchestrator:
    return IngestOrchestrator(
        memory_client=mock_memory_client,
        github_client=mock_github_client,
        git_client=mock_git_client,
        hash_store=hash_store,
        lock_manager=lock_mgr,
        repo_root=git_repo,
    )


class TestHappyPath:
    def test_ingest_returns_0(self, orchestrator: IngestOrchestrator):
        code = orchestrator.run("myorg/myrepo", since_days=90)
        assert code == 0

    def test_ingest_stores_pr_artifacts(
        self, orchestrator: IngestOrchestrator, mock_memory_client: MagicMock
    ):
        orchestrator.run("myorg/myrepo", since_days=90)
        add_calls = mock_memory_client.add_memory.call_args_list
        pr_calls = [c for c in add_calls if "raw_pr_thread" in str(c)]
        assert len(pr_calls) == 2

    def test_ingest_stores_issue_artifacts(
        self, orchestrator: IngestOrchestrator, mock_memory_client: MagicMock
    ):
        orchestrator.run("myorg/myrepo", since_days=90)
        add_calls = mock_memory_client.add_memory.call_args_list
        issue_calls = [c for c in add_calls if "[type: issue]" in str(c)]
        assert len(issue_calls) == 2

    def test_ingest_stores_commit_artifacts(
        self, orchestrator: IngestOrchestrator, mock_memory_client: MagicMock
    ):
        orchestrator.run("myorg/myrepo", since_days=90)
        add_calls = mock_memory_client.add_memory.call_args_list
        commit_calls = [c for c in add_calls if "[type: commit]" in str(c)]
        assert len(commit_calls) == 2

    def test_ingest_saves_hash_store(
        self, orchestrator: IngestOrchestrator, git_repo: Path
    ):
        orchestrator.run("myorg/myrepo", since_days=90)
        assert (git_repo / ".avos" / "ingest_hashes.json").exists()

    def test_ingest_releases_lock(
        self, orchestrator: IngestOrchestrator, git_repo: Path
    ):
        orchestrator.run("myorg/myrepo", since_days=90)
        assert not (git_repo / ".avos" / "ingest.lock").exists()


class TestIdempotency:
    def test_rerun_skips_already_stored(
        self,
        orchestrator: IngestOrchestrator,
        mock_memory_client: MagicMock,
        git_repo: Path,
    ):
        orchestrator.run("myorg/myrepo", since_days=90)

        mock_memory_client.add_memory.reset_mock()
        store2 = IngestHashStore(git_repo / ".avos")
        store2.load()
        orch2 = IngestOrchestrator(
            memory_client=mock_memory_client,
            github_client=orchestrator._github,
            git_client=orchestrator._git,
            hash_store=store2,
            lock_manager=IngestLockManager(git_repo / ".avos"),
            repo_root=git_repo,
        )
        code = orch2.run("myorg/myrepo", since_days=90)
        assert code == 0
        assert mock_memory_client.add_memory.call_count == 0

    def test_hash_store_grows_on_first_run(
        self, orchestrator: IngestOrchestrator, hash_store: IngestHashStore
    ):
        orchestrator.run("myorg/myrepo", since_days=90)
        assert hash_store.count() >= 4  # 2 PRs + 2 issues + 2 commits (docs may be 0)


class TestPartialFailure:
    def test_one_pr_fails_rest_continue(
        self,
        orchestrator: IngestOrchestrator,
        mock_memory_client: MagicMock,
    ):
        call_count = [0]

        def fail_second_call(**kwargs: Any) -> NoteResponse:
            call_count[0] += 1
            if call_count[0] == 2:
                raise UpstreamUnavailableError("Transient failure")
            return NoteResponse(
                note_id=f"note-{call_count[0]}",
                content="stored",
                created_at="2026-03-06T00:00:00Z",
            )

        mock_memory_client.add_memory.side_effect = fail_second_call
        code = orchestrator.run("myorg/myrepo", since_days=90)
        assert code == 3  # partial success

    def test_partial_failure_still_saves_hash_store(
        self,
        orchestrator: IngestOrchestrator,
        mock_memory_client: MagicMock,
        git_repo: Path,
    ):
        call_count = [0]

        def fail_once(**kwargs: Any) -> NoteResponse:
            call_count[0] += 1
            if call_count[0] == 1:
                raise UpstreamUnavailableError("Fail")
            return NoteResponse(
                note_id=f"note-{call_count[0]}",
                content="stored",
                created_at="2026-03-06T00:00:00Z",
            )

        mock_memory_client.add_memory.side_effect = fail_once
        orchestrator.run("myorg/myrepo", since_days=90)
        assert (git_repo / ".avos" / "ingest_hashes.json").exists()


class TestLockConflict:
    def test_lock_held_returns_1(
        self, git_repo: Path, mock_memory_client: MagicMock,
        mock_github_client: MagicMock, mock_git_client: MagicMock,
    ):
        lock_mgr = IngestLockManager(git_repo / ".avos")
        lock_mgr.acquire()

        store = IngestHashStore(git_repo / ".avos")
        store.load()
        orch = IngestOrchestrator(
            memory_client=mock_memory_client,
            github_client=mock_github_client,
            git_client=mock_git_client,
            hash_store=store,
            lock_manager=IngestLockManager(git_repo / ".avos"),
            repo_root=git_repo,
        )
        code = orch.run("myorg/myrepo", since_days=90)
        assert code == 1
        lock_mgr.release()


class TestConfigNotInitialized:
    def test_missing_config_returns_1(
        self, tmp_path: Path, mock_memory_client: MagicMock,
        mock_github_client: MagicMock, mock_git_client: MagicMock,
    ):
        repo = tmp_path / "no_config"
        repo.mkdir()
        (repo / ".git").mkdir()
        (repo / ".avos").mkdir()

        store = IngestHashStore(repo / ".avos")
        store.load()
        orch = IngestOrchestrator(
            memory_client=mock_memory_client,
            github_client=mock_github_client,
            git_client=mock_git_client,
            hash_store=store,
            lock_manager=IngestLockManager(repo / ".avos"),
            repo_root=repo,
        )
        code = orch.run("myorg/myrepo", since_days=90)
        assert code == 1


class TestEmptyRepo:
    def test_no_prs_no_issues_no_commits_returns_0(
        self,
        git_repo: Path,
        mock_memory_client: MagicMock,
        mock_github_client: MagicMock,
        mock_git_client: MagicMock,
    ):
        mock_github_client.list_pull_requests.return_value = []
        mock_github_client.list_issues.return_value = []
        mock_git_client.commit_log.return_value = []

        store = IngestHashStore(git_repo / ".avos")
        store.load()
        orch = IngestOrchestrator(
            memory_client=mock_memory_client,
            github_client=mock_github_client,
            git_client=mock_git_client,
            hash_store=store,
            lock_manager=IngestLockManager(git_repo / ".avos"),
            repo_root=git_repo,
        )
        code = orch.run("myorg/myrepo", since_days=90)
        assert code == 0
        mock_memory_client.add_memory.assert_not_called()


class TestSinceDateParsing:
    def test_since_days_calculates_correct_date(
        self, orchestrator: IngestOrchestrator, mock_github_client: MagicMock
    ):
        orchestrator.run("myorg/myrepo", since_days=30)
        call_args = mock_github_client.list_pull_requests.call_args
        since_date = call_args.kwargs.get("since_date") or call_args[1].get("since_date")
        assert since_date is not None
        assert "2026" in since_date


class TestIngestStageResult:
    def test_defaults(self):
        r = IngestStageResult()
        assert r.processed == 0
        assert r.stored == 0
        assert r.skipped == 0
        assert r.failed == 0

    def test_has_failures(self):
        r = IngestStageResult(failed=1)
        assert r.has_failures

    def test_no_failures(self):
        r = IngestStageResult(processed=5, stored=5)
        assert not r.has_failures


class TestExitCodePrecedence:
    """Verify deterministic exit-code precedence: 2 > 3 > 1 > 0."""

    def test_resolve_all_success(self):
        assert resolve_exit_code(0, 0, 0, 0) == 0

    def test_resolve_partial_wins_over_success(self):
        assert resolve_exit_code(0, 3, 0, 0) == 3

    def test_resolve_hard_wins_over_partial(self):
        assert resolve_exit_code(0, 3, 2, 0) == 2

    def test_resolve_hard_wins_over_all(self):
        assert resolve_exit_code(1, 3, 2, 0) == 2

    def test_resolve_precondition_wins_over_success(self):
        assert resolve_exit_code(0, 1, 0, 0) == 1

    def test_resolve_empty_returns_0(self):
        assert resolve_exit_code() == 0

    def test_stage_result_exit_code_hard_failure(self):
        r = IngestStageResult(failed=1, hard_failure=True)
        assert r.exit_code == 2

    def test_stage_result_exit_code_partial(self):
        r = IngestStageResult(failed=1, hard_failure=False)
        assert r.exit_code == 3

    def test_stage_result_exit_code_success(self):
        r = IngestStageResult(processed=5, stored=5)
        assert r.exit_code == 0

    def test_pipeline_returns_2_on_upstream_fetch_failure(
        self, orchestrator: IngestOrchestrator, mock_github_client: MagicMock
    ):
        """When a stage fetch fails with AvosError, pipeline returns 2."""
        mock_github_client.list_pull_requests.side_effect = UpstreamUnavailableError(
            "GitHub down"
        )
        code = orchestrator.run("myorg/myrepo", since_days=90)
        assert code == 2

    def test_pipeline_returns_2_when_mixed_hard_and_partial(
        self,
        orchestrator: IngestOrchestrator,
        mock_github_client: MagicMock,
        mock_memory_client: MagicMock,
    ):
        """Hard external (2) takes precedence over partial (3)."""
        mock_github_client.list_pull_requests.side_effect = UpstreamUnavailableError(
            "GitHub down"
        )
        mock_memory_client.add_memory.side_effect = [
            Exception("store fail"),
            NoteResponse(
                note_id="ok",
                memory_id="repo:myorg/myrepo",
                content="ok",
                created_at="2026-03-06T00:00:00Z",
            ),
        ]
        code = orchestrator.run("myorg/myrepo", since_days=90)
        assert code == 2


class TestSlugValidation:
    def test_invalid_slug_returns_1(self, orchestrator: IngestOrchestrator):
        code = orchestrator.run("invalid", since_days=90)
        assert code == 1

    def test_empty_slug_returns_1(self, orchestrator: IngestOrchestrator):
        code = orchestrator.run("", since_days=90)
        assert code == 1
