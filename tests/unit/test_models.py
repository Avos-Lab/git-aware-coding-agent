"""Tests for AVOS-002: Pydantic data models.

Covers valid instantiation, invalid rejection, serialization round-trip,
SecretStr behavior, and constraint enforcement for all model families.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import SecretStr, ValidationError

from avos_cli.models.api import NoteResponse, SearchHit, SearchRequest, SearchResult
from avos_cli.models.artifacts import (
    CommitArtifact,
    DocArtifact,
    IssueArtifact,
    PRArtifact,
    SessionArtifact,
    WIPArtifact,
)
from avos_cli.models.config import LLMConfig, RepoConfig, SessionState, WatchState


class TestRepoConfig:
    def test_valid_creation(self):
        cfg = RepoConfig(
            repo="org/repo",
            memory_id="repo:org/repo",
            api_url="https://api.example.com",
            api_key=SecretStr("sk_test_key"),
        )
        assert cfg.repo == "org/repo"
        assert cfg.memory_id == "repo:org/repo"
        assert cfg.api_key.get_secret_value() == "sk_test_key"

    def test_optional_fields_default_none(self):
        cfg = RepoConfig(
            repo="org/repo",
            memory_id="repo:org/repo",
            api_url="https://api.example.com",
            api_key=SecretStr("sk_test"),
        )
        assert cfg.github_token is None
        assert cfg.developer is None

    def test_llm_config_defaults(self):
        cfg = RepoConfig(
            repo="org/repo",
            memory_id="repo:org/repo",
            api_url="https://api.example.com",
            api_key=SecretStr("sk_test"),
        )
        assert cfg.llm.provider == "anthropic"
        assert cfg.llm.model == "claude-sonnet-4-5-20250929"

    def test_llm_config_override(self):
        cfg = RepoConfig(
            repo="org/repo",
            memory_id="repo:org/repo",
            api_url="https://api.example.com",
            api_key=SecretStr("sk_test"),
            llm=LLMConfig(provider="openai", model="gpt-4"),
        )
        assert cfg.llm.provider == "openai"

    def test_secret_str_not_exposed_in_repr(self):
        cfg = RepoConfig(
            repo="org/repo",
            memory_id="repo:org/repo",
            api_url="https://api.example.com",
            api_key=SecretStr("sk_super_secret"),
        )
        repr_str = repr(cfg)
        assert "sk_super_secret" not in repr_str

    def test_secret_str_not_exposed_in_model_dump(self):
        cfg = RepoConfig(
            repo="org/repo",
            memory_id="repo:org/repo",
            api_url="https://api.example.com",
            api_key=SecretStr("sk_super_secret"),
        )
        dumped = cfg.model_dump()
        assert dumped["api_key"] != "sk_super_secret"

    def test_missing_required_fields_rejected(self):
        with pytest.raises(ValidationError):
            RepoConfig()  # type: ignore[call-arg]

    def test_github_token_is_secret(self):
        cfg = RepoConfig(
            repo="org/repo",
            memory_id="repo:org/repo",
            api_url="https://api.example.com",
            api_key=SecretStr("sk_test"),
            github_token=SecretStr("ghp_secret_token"),
        )
        assert cfg.github_token is not None
        assert cfg.github_token.get_secret_value() == "ghp_secret_token"
        assert "ghp_secret_token" not in repr(cfg)


class TestSessionState:
    def test_valid_creation(self):
        now = datetime.now(tz=timezone.utc)
        state = SessionState(
            session_id="sess-123",
            goal="Fix payment bug",
            start_time=now,
            branch="feature/fix-payment",
            memory_id="repo:org/repo",
        )
        assert state.session_id == "sess-123"
        assert state.goal == "Fix payment bug"
        assert state.start_time == now
        assert state.branch == "feature/fix-payment"

    def test_missing_required_fields(self):
        with pytest.raises(ValidationError):
            SessionState()  # type: ignore[call-arg]


class TestWatchState:
    def test_valid_creation(self):
        now = datetime.now(tz=timezone.utc)
        state = WatchState(
            developer="sanzeeda",
            branch="feature/retry",
            last_publish_time=now,
            files_tracked=["billing/retry.py"],
        )
        assert state.developer == "sanzeeda"
        assert state.files_tracked == ["billing/retry.py"]

    def test_empty_files_tracked(self):
        now = datetime.now(tz=timezone.utc)
        state = WatchState(
            developer="dev",
            branch="main",
            last_publish_time=now,
            files_tracked=[],
        )
        assert state.files_tracked == []


class TestPRArtifact:
    def test_valid_creation(self):
        pr = PRArtifact(
            repo="org/repo",
            pr_number=312,
            title="Add retry scheduler",
            author="sanzeeda",
            merged_date="2026-01-15",
            files=["billing/retry_scheduler.py"],
            description="Implements exponential backoff",
            discussion="Team discussed queue deadlock",
        )
        assert pr.pr_number == 312
        assert pr.author == "sanzeeda"

    def test_optional_fields(self):
        pr = PRArtifact(
            repo="org/repo",
            pr_number=1,
            title="Test PR",
            author="dev",
        )
        assert pr.merged_date is None
        assert pr.files == []
        assert pr.description is None
        assert pr.discussion is None


class TestIssueArtifact:
    def test_valid_creation(self):
        issue = IssueArtifact(
            repo="org/repo",
            issue_number=42,
            title="Bug in payment flow",
            labels=["bug", "critical"],
            body="Payment fails on retry",
            comments=["Confirmed on prod"],
        )
        assert issue.issue_number == 42
        assert issue.labels == ["bug", "critical"]

    def test_defaults(self):
        issue = IssueArtifact(
            repo="org/repo",
            issue_number=1,
            title="Test",
        )
        assert issue.labels == []
        assert issue.body is None
        assert issue.comments == []


class TestCommitArtifact:
    def test_valid_creation(self):
        commit = CommitArtifact(
            repo="org/repo",
            hash="abc123",
            message="fix: retry logic",
            author="dev",
            date="2026-01-15",
            files_changed=["billing/retry.py"],
            diff_stats="+50 -10",
        )
        assert commit.hash == "abc123"

    def test_defaults(self):
        commit = CommitArtifact(
            repo="org/repo",
            hash="abc",
            message="msg",
            author="dev",
            date="2026-01-15",
        )
        assert commit.files_changed == []
        assert commit.diff_stats is None


class TestSessionArtifact:
    def test_valid_creation(self):
        sa = SessionArtifact(
            session_id="sess-1",
            goal="Fix bug",
            files_modified=["a.py"],
            decisions=["Used retry pattern"],
            errors=["TypeError on line 10"],
            resolution="Fixed type mismatch",
            timeline=["10:00 started", "10:30 found bug"],
        )
        assert sa.session_id == "sess-1"

    def test_defaults(self):
        sa = SessionArtifact(session_id="s1", goal="test")
        assert sa.files_modified == []
        assert sa.decisions == []
        assert sa.errors == []
        assert sa.resolution is None
        assert sa.timeline == []


class TestWIPArtifact:
    def test_valid_creation(self):
        wip = WIPArtifact(
            developer="sanzeeda",
            branch="feature/retry",
            intent="implementing retry scheduler",
            files_touched=["billing/retry.py"],
            diff_stats="+180 -25",
            symbols_touched=["RetryScheduler.run"],
            modules_touched=["billing"],
            subsystems_touched=["payments"],
            timestamp="2026-01-15T10:00:00Z",
        )
        assert wip.developer == "sanzeeda"

    def test_defaults(self):
        wip = WIPArtifact(
            developer="dev",
            branch="main",
            timestamp="2026-01-15T10:00:00Z",
        )
        assert wip.intent is None
        assert wip.files_touched == []
        assert wip.symbols_touched == []


class TestDocArtifact:
    def test_valid_creation(self):
        doc = DocArtifact(
            repo="org/repo",
            path="README.md",
            content_type="readme",
            content="# Project\nDescription here",
        )
        assert doc.path == "README.md"
        assert doc.content_type == "readme"


class TestSearchRequest:
    def test_valid_creation(self):
        req = SearchRequest(query="how does auth work?", k=10, mode="semantic")
        assert req.query == "how does auth work?"
        assert req.k == 10
        assert req.mode == "semantic"

    def test_defaults(self):
        req = SearchRequest(query="test")
        assert req.k == 5
        assert req.mode == "semantic"

    def test_k_lower_bound(self):
        with pytest.raises(ValidationError):
            SearchRequest(query="test", k=0)

    def test_k_upper_bound(self):
        with pytest.raises(ValidationError):
            SearchRequest(query="test", k=51)

    def test_invalid_mode(self):
        with pytest.raises(ValidationError):
            SearchRequest(query="test", mode="invalid")  # type: ignore[arg-type]

    def test_valid_modes(self):
        for mode in ("semantic", "keyword", "hybrid"):
            req = SearchRequest(query="test", mode=mode)  # type: ignore[arg-type]
            assert req.mode == mode

    def test_empty_query_rejected(self):
        with pytest.raises(ValidationError):
            SearchRequest(query="")


class TestSearchHit:
    def test_valid_creation(self):
        hit = SearchHit(
            note_id="abc-123",
            content="Some content",
            created_at="2026-01-15T10:00:00Z",
            rank=1,
        )
        assert hit.rank == 1


class TestSearchResult:
    def test_valid_creation(self):
        result = SearchResult(
            results=[
                SearchHit(
                    note_id="abc",
                    content="content",
                    created_at="2026-01-15T10:00:00Z",
                    rank=1,
                )
            ],
            total_count=87,
        )
        assert len(result.results) == 1
        assert result.total_count == 87

    def test_empty_results(self):
        result = SearchResult(results=[], total_count=0)
        assert result.results == []


class TestNoteResponse:
    def test_valid_creation(self):
        resp = NoteResponse(
            note_id="5b04d9c7-5a6d-476f-ad00-162a9ae10460",
            content="Stored content",
            created_at="2026-02-19T00:31:00",
        )
        assert resp.note_id == "5b04d9c7-5a6d-476f-ad00-162a9ae10460"


class TestModelReExports:
    """Verify models are importable from avos_cli.models."""

    def test_config_models_importable(self):
        from avos_cli.models import LLMConfig, RepoConfig, SessionState, WatchState

        assert RepoConfig is not None
        assert SessionState is not None
        assert WatchState is not None
        assert LLMConfig is not None

    def test_artifact_models_importable(self):
        from avos_cli.models import (
            CommitArtifact,
            DocArtifact,
            IssueArtifact,
            PRArtifact,
            SessionArtifact,
            WIPArtifact,
        )

        assert PRArtifact is not None
        assert IssueArtifact is not None
        assert CommitArtifact is not None
        assert SessionArtifact is not None
        assert WIPArtifact is not None
        assert DocArtifact is not None

    def test_api_models_importable(self):
        from avos_cli.models import NoteResponse, SearchHit, SearchRequest, SearchResult

        assert SearchRequest is not None
        assert SearchResult is not None
        assert SearchHit is not None
        assert NoteResponse is not None
