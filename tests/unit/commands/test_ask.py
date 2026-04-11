"""Brutal tests for AskOrchestrator (avos_cli/commands/ask.py).

Covers full pipeline: search -> diff enrichment -> sanitize -> budget -> synthesize ->
ground -> render/fallback. Tests happy path, empty state, LLM failure,
grounding failure, sanitization block, Memory API errors, and diff enrichment.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from avos_cli.commands.ask import AskOrchestrator
from avos_cli.exceptions import (
    AuthError,
    ConfigurationNotInitializedError,
    LLMSynthesisError,
    RepositoryContextError,
    UpstreamUnavailableError,
)
from avos_cli.models.api import SearchHit, SearchResult
from avos_cli.models.query import SanitizedArtifact, SynthesisResponse


def _make_search_result(count: int = 3) -> SearchResult:
    hits = [
        SearchHit(
            note_id=f"note-{i}",
            content=f"Content for artifact {i} about auth and JWT tokens.",
            created_at=f"2026-01-{10+i:02d}T10:00:00Z",
            rank=i + 1,
        )
        for i in range(count)
    ]
    return SearchResult(results=hits, total_count=count)


def _make_synthesis_response() -> SynthesisResponse:
    return SynthesisResponse(
        answer_text=json.dumps({
            "answer": "Auth uses JWT tokens for session management.",
            "citations": [{"note_id": "note-0"}, {"note_id": "note-1"}],
        }),
    )


def _make_search_result_with_refs(count: int = 2) -> SearchResult:
    """Create search result with PR/commit references in content."""
    hits = [
        SearchHit(
            note_id=f"note-{i}",
            content=f"[pr: #{100 + i}] [hash: abc{i}def] Content for artifact {i}.",
            created_at=f"2026-01-{10+i:02d}T10:00:00Z",
            rank=i + 1,
        )
        for i in range(count)
    ]
    return SearchResult(results=hits, total_count=count)


def _make_orchestrator(
    memory_client: MagicMock | None = None,
    llm_client: MagicMock | None = None,
    repo_root: Path | None = None,
    github_client: MagicMock | None = None,
    diff_summary_service: MagicMock | None = None,
) -> AskOrchestrator:
    mc = memory_client or MagicMock()
    lc = llm_client or MagicMock()
    rr = repo_root or Path("/tmp/test-repo")
    return AskOrchestrator(
        memory_client=mc,
        llm_client=lc,
        repo_root=rr,
        github_client=github_client,
        diff_summary_service=diff_summary_service,
    )


class TestHappyPath:
    """Normal ask flow: search -> synthesize -> grounded answer."""

    def test_successful_ask_returns_zero(self):
        mc = MagicMock()
        mc.search.return_value = _make_search_result(3)

        lc = MagicMock()
        lc.synthesize.return_value = SynthesisResponse(
            answer_text=json.dumps({
                "answer": "Auth uses JWT.",
                "citations": [{"note_id": "note-0"}, {"note_id": "note-1"}],
            }),
        )

        orch = _make_orchestrator(memory_client=mc, llm_client=lc)
        with patch("avos_cli.commands.ask.load_config") as mock_cfg:
            mock_cfg.return_value = MagicMock(memory_id="repo:org/repo", llm=MagicMock(provider="anthropic", model="claude-sonnet-4-5-20250929"))
            code = orch.run("org/repo", "How does auth work?")
        assert code == 0

    def test_search_called_with_correct_params(self):
        mc = MagicMock()
        mc.search.return_value = _make_search_result(3)

        lc = MagicMock()
        lc.synthesize.return_value = SynthesisResponse(
            answer_text=json.dumps({
                "answer": "answer",
                "citations": [{"note_id": "note-0"}, {"note_id": "note-1"}],
            }),
        )

        orch = _make_orchestrator(memory_client=mc, llm_client=lc)
        with patch("avos_cli.commands.ask.load_config") as mock_cfg:
            mock_cfg.return_value = MagicMock(memory_id="repo:org/repo", llm=MagicMock(provider="anthropic", model="claude-sonnet-4-5-20250929"))
            orch.run("org/repo", "How does auth work?")
        mc.search.assert_called_once()
        call_kwargs = mc.search.call_args
        assert call_kwargs[1].get("k", call_kwargs[0][2] if len(call_kwargs[0]) > 2 else None) == 10 or mc.search.call_args[1].get("k") == 10


class TestEmptyState:
    """Empty search results -> helpful message, no LLM call."""

    def test_empty_results_returns_zero(self):
        mc = MagicMock()
        mc.search.return_value = SearchResult(results=[], total_count=0)
        lc = MagicMock()

        orch = _make_orchestrator(memory_client=mc, llm_client=lc)
        with patch("avos_cli.commands.ask.load_config") as mock_cfg:
            mock_cfg.return_value = MagicMock(memory_id="repo:org/repo", llm=MagicMock(provider="anthropic", model="claude-sonnet-4-5-20250929"))
            code = orch.run("org/repo", "How does auth work?")
        assert code == 0
        lc.synthesize.assert_not_called()


class TestLLMFailure:
    """LLM failure -> fallback to raw results."""

    def test_llm_failure_triggers_fallback(self):
        mc = MagicMock()
        mc.search.return_value = _make_search_result(3)
        lc = MagicMock()
        lc.synthesize.side_effect = LLMSynthesisError("timeout", failure_class="transient")

        orch = _make_orchestrator(memory_client=mc, llm_client=lc)
        with patch("avos_cli.commands.ask.load_config") as mock_cfg:
            mock_cfg.return_value = MagicMock(memory_id="repo:org/repo", llm=MagicMock(provider="anthropic", model="claude-sonnet-4-5-20250929"))
            code = orch.run("org/repo", "How does auth work?")
        assert code == 0  # Fallback is still success


class TestPreconditionFailures:
    """Config/slug errors -> exit 1."""

    def test_invalid_slug_returns_one(self):
        orch = _make_orchestrator()
        code = orch.run("invalid-slug", "question")
        assert code == 1

    def test_config_not_initialized_returns_one(self):
        orch = _make_orchestrator()
        with patch("avos_cli.commands.ask.load_config", side_effect=ConfigurationNotInitializedError()):
            code = orch.run("org/repo", "question")
        assert code == 1


class TestMemoryAPIErrors:
    """Memory API failures -> exit 2."""

    def test_auth_error_returns_two(self):
        mc = MagicMock()
        mc.search.side_effect = AuthError("unauthorized", service="Avos Memory")
        orch = _make_orchestrator(memory_client=mc)
        with patch("avos_cli.commands.ask.load_config") as mock_cfg:
            mock_cfg.return_value = MagicMock(memory_id="repo:org/repo", llm=MagicMock(provider="anthropic", model="claude-sonnet-4-5-20250929"))
            code = orch.run("org/repo", "question")
        assert code == 2

    def test_upstream_unavailable_returns_two(self):
        mc = MagicMock()
        mc.search.side_effect = UpstreamUnavailableError("API down")
        orch = _make_orchestrator(memory_client=mc)
        with patch("avos_cli.commands.ask.load_config") as mock_cfg:
            mock_cfg.return_value = MagicMock(memory_id="repo:org/repo", llm=MagicMock(provider="anthropic", model="claude-sonnet-4-5-20250929"))
            code = orch.run("org/repo", "question")
        assert code == 2


class TestGroundingFailure:
    """Ungrounded synthesis -> fallback."""

    def test_ungrounded_response_triggers_fallback(self):
        mc = MagicMock()
        mc.search.return_value = _make_search_result(3)
        lc = MagicMock()
        # Response with citations that don't match any artifacts
        lc.synthesize.return_value = SynthesisResponse(
            answer_text=json.dumps({
                "answer": "Hallucinated answer.",
                "citations": [{"note_id": "fake-1"}, {"note_id": "fake-2"}],
            }),
        )

        orch = _make_orchestrator(memory_client=mc, llm_client=lc)
        with patch("avos_cli.commands.ask.load_config") as mock_cfg:
            mock_cfg.return_value = MagicMock(memory_id="repo:org/repo", llm=MagicMock(provider="anthropic", model="claude-sonnet-4-5-20250929"))
            code = orch.run("org/repo", "question")
        assert code == 0  # Fallback is still success


class TestJsonOutputMode:
    """Tests for --json mode output."""

    def test_json_mode_invalid_slug_emits_json_error(self, capsys):
        orch = _make_orchestrator()
        code = orch.run("invalid-slug", "question", json_output=True)
        assert code == 1
        captured = capsys.readouterr()
        out = captured.out
        assert '"success": false' in out or '"success":false' in out
        assert "REPOSITORY_CONTEXT_ERROR" in out

    def test_json_mode_config_not_initialized_emits_json_error(self, capsys):
        orch = _make_orchestrator()
        with patch("avos_cli.commands.ask.load_config", side_effect=ConfigurationNotInitializedError()):
            code = orch.run("org/repo", "question", json_output=True)
        assert code == 1
        captured = capsys.readouterr()
        out = captured.out
        assert '"success": false' in out or '"success":false' in out
        assert "CONFIG_NOT_INITIALIZED" in out

    def test_json_mode_empty_results_emits_json_success(self, capsys):
        mc = MagicMock()
        mc.search.return_value = SearchResult(results=[], total_count=0)
        lc = MagicMock()

        orch = _make_orchestrator(memory_client=mc, llm_client=lc)
        with patch("avos_cli.commands.ask.load_config") as mock_cfg:
            mock_cfg.return_value = MagicMock(memory_id="repo:org/repo", llm=MagicMock(provider="anthropic", model="claude-sonnet-4-5-20250929"))
            code = orch.run("org/repo", "How does auth work?", json_output=True)
        assert code == 0
        captured = capsys.readouterr()
        out = captured.out
        assert '"success": true' in out or '"success":true' in out
        assert "avos.ask.v1" in out

    def test_json_mode_no_reply_service_emits_error(self, capsys):
        mc = MagicMock()
        mc.search.return_value = _make_search_result(3)
        lc = MagicMock()
        lc.synthesize.return_value = SynthesisResponse(
            answer_text=json.dumps({
                "answer": "Auth uses JWT.",
                "citations": [{"note_id": "note-0"}, {"note_id": "note-1"}],
            }),
        )

        orch = _make_orchestrator(memory_client=mc, llm_client=lc)
        with patch("avos_cli.commands.ask.load_config") as mock_cfg:
            mock_cfg.return_value = MagicMock(memory_id="repo:org/repo", llm=MagicMock(provider="anthropic", model="claude-sonnet-4-5-20250929"))
            code = orch.run("org/repo", "How does auth work?", json_output=True)
        assert code == 0
        captured = capsys.readouterr()
        out = captured.out
        assert '"success": false' in out or '"success":false' in out
        assert "REPLY_SERVICE_UNAVAILABLE" in out


class TestAdditionalCoverageBranches:
    """Targeted branch tests for CI coverage gate."""

    def test_config_avos_error_json_mode_returns_one(self, capsys):
        orch = _make_orchestrator()
        with patch(
            "avos_cli.commands.ask.load_config",
            side_effect=RepositoryContextError("repo context failed"),
        ):
            code = orch.run("org/repo", "question", json_output=True)
        assert code == 1
        out = capsys.readouterr().out
        assert "REPOSITORY_CONTEXT_ERROR" in out

    def test_config_avos_error_human_mode_returns_one(self, capsys):
        orch = _make_orchestrator()
        with patch(
            "avos_cli.commands.ask.load_config",
            side_effect=RepositoryContextError("repo context failed"),
        ):
            code = orch.run("org/repo", "question", json_output=False)
        assert code == 1

    def test_memory_search_error_json_mode_returns_two(self, capsys):
        mc = MagicMock()
        mc.search.side_effect = AuthError("unauthorized", service="Avos Memory")
        orch = _make_orchestrator(memory_client=mc)
        with patch("avos_cli.commands.ask.load_config") as mock_cfg:
            mock_cfg.return_value = MagicMock(
                memory_id="repo:org/repo",
                llm=MagicMock(provider="anthropic", model="claude-sonnet-4-5-20250929"),
            )
            code = orch.run("org/repo", "question", json_output=True)
        assert code == 2
        out = capsys.readouterr().out
        assert "AUTH_ERROR" in out

    def test_sanitization_safety_block_fallback_branch(self, capsys):
        mc = MagicMock()
        mc.search.return_value = _make_search_result(2)
        orch = _make_orchestrator(memory_client=mc, llm_client=MagicMock())
        orch._sanitizer.sanitize = MagicMock(
            return_value=MagicMock(
                confidence_score=10,
                redaction_applied=True,
                redaction_types=["token"],
                artifacts=[
                    SanitizedArtifact(
                        note_id="n1",
                        content="safe",
                        created_at="2026-01-01T00:00:00Z",
                        rank=1,
                    )
                ],
            )
        )
        with patch("avos_cli.commands.ask.load_config") as mock_cfg:
            mock_cfg.return_value = MagicMock(
                memory_id="repo:org/repo",
                llm=MagicMock(provider="anthropic", model="claude-sonnet-4-5-20250929"),
            )
            code = orch.run("org/repo", "question")
        assert code == 0
        captured = capsys.readouterr()
        combined = captured.out + captured.err
        assert "10/100" in combined
        assert "70" in combined
        assert "GitHub PAT" in combined or "token" in combined.lower()

    def test_budget_exhausted_fallback_branch(self):
        mc = MagicMock()
        mc.search.return_value = _make_search_result(2)
        orch = _make_orchestrator(memory_client=mc, llm_client=MagicMock())
        orch._sanitizer.sanitize = MagicMock(
            return_value=MagicMock(
                confidence_score=100,
                artifacts=[
                    SanitizedArtifact(
                        note_id="n1",
                        content="safe",
                        created_at="2026-01-01T00:00:00Z",
                        rank=1,
                    )
                ],
            )
        )
        orch._budget.pack = MagicMock(return_value=MagicMock(included_count=1, included=[]))
        with patch("avos_cli.commands.ask.load_config") as mock_cfg:
            mock_cfg.return_value = MagicMock(
                memory_id="repo:org/repo",
                llm=MagicMock(provider="anthropic", model="claude-sonnet-4-5-20250929"),
            )
            code = orch.run("org/repo", "question")
        assert code == 0


class TestDiffEnrichment:
    """Tests for diff enrichment stage."""

    def test_skips_enrichment_when_no_github_client(self):
        """Should skip enrichment gracefully when github_client is None."""
        mc = MagicMock()
        mc.search.return_value = _make_search_result_with_refs(2)
        lc = MagicMock()
        lc.synthesize.return_value = SynthesisResponse(
            answer_text=json.dumps({
                "answer": "Answer",
                "citations": [{"note_id": "note-0"}, {"note_id": "note-1"}],
            }),
        )

        orch = _make_orchestrator(
            memory_client=mc,
            llm_client=lc,
            github_client=None,
            diff_summary_service=MagicMock(),
        )
        with patch("avos_cli.commands.ask.load_config") as mock_cfg:
            mock_cfg.return_value = MagicMock(
                memory_id="repo:org/repo",
                llm=MagicMock(provider="anthropic", model="claude-sonnet-4-5-20250929"),
            )
            code = orch.run("org/repo", "question")
        assert code == 0

    def test_skips_enrichment_when_no_diff_summary_service(self):
        """Should skip enrichment gracefully when diff_summary_service is None."""
        mc = MagicMock()
        mc.search.return_value = _make_search_result_with_refs(2)
        lc = MagicMock()
        lc.synthesize.return_value = SynthesisResponse(
            answer_text=json.dumps({
                "answer": "Answer",
                "citations": [{"note_id": "note-0"}, {"note_id": "note-1"}],
            }),
        )

        orch = _make_orchestrator(
            memory_client=mc,
            llm_client=lc,
            github_client=MagicMock(),
            diff_summary_service=None,
        )
        with patch("avos_cli.commands.ask.load_config") as mock_cfg:
            mock_cfg.return_value = MagicMock(
                memory_id="repo:org/repo",
                llm=MagicMock(provider="anthropic", model="claude-sonnet-4-5-20250929"),
            )
            code = orch.run("org/repo", "question")
        assert code == 0

    def test_enrichment_injects_diff_summary_into_artifacts(self):
        """Should inject diff summaries into artifact content."""
        mc = MagicMock()
        mc.search.return_value = _make_search_result_with_refs(1)

        lc = MagicMock()
        lc.synthesize.return_value = SynthesisResponse(
            answer_text=json.dumps({
                "answer": "Answer with diff context",
                "citations": [{"note_id": "note-0"}],
            }),
        )

        gh_client = MagicMock()
        gh_client.get_pr_diff.return_value = "diff --git a/foo.py b/foo.py\n+new line"
        gh_client.list_pr_commits.return_value = ["abc0def1234567890123456789012345678901234"]

        diff_service = MagicMock()
        diff_service.summarize_diffs.return_value = {
            "PR #100": "## Summary\nThis PR adds a new feature."
        }

        orch = _make_orchestrator(
            memory_client=mc,
            llm_client=lc,
            github_client=gh_client,
            diff_summary_service=diff_service,
        )

        with patch("avos_cli.commands.ask.load_config") as mock_cfg:
            mock_cfg.return_value = MagicMock(
                memory_id="repo:org/repo",
                llm=MagicMock(provider="anthropic", model="claude-sonnet-4-5-20250929"),
            )
            with patch.object(orch, "_sanitizer") as mock_sanitizer:
                mock_sanitizer.sanitize.return_value = MagicMock(
                    confidence_score=100,
                    artifacts=[
                        SanitizedArtifact(
                            note_id="note-0",
                            content="[pr: #100] Content\n\n--- Diff Summary ---\n## Summary\nThis PR adds a new feature.",
                            created_at="2026-01-10T10:00:00Z",
                            rank=1,
                        )
                    ],
                )
                code = orch.run("org/repo", "question")

        assert code == 0
        mock_sanitizer.sanitize.assert_called_once()
        artifacts_passed = mock_sanitizer.sanitize.call_args[0][0]
        assert len(artifacts_passed) == 1
        assert "--- Diff Summary ---" in artifacts_passed[0].content

    def test_enrichment_handles_exception_gracefully(self):
        """Should skip enrichment and continue when exception occurs."""
        mc = MagicMock()
        mc.search.return_value = _make_search_result_with_refs(2)
        lc = MagicMock()
        lc.synthesize.return_value = SynthesisResponse(
            answer_text=json.dumps({
                "answer": "Answer",
                "citations": [{"note_id": "note-0"}, {"note_id": "note-1"}],
            }),
        )

        gh_client = MagicMock()
        gh_client.get_pr_diff.side_effect = Exception("API error")

        diff_service = MagicMock()

        orch = _make_orchestrator(
            memory_client=mc,
            llm_client=lc,
            github_client=gh_client,
            diff_summary_service=diff_service,
        )
        with patch("avos_cli.commands.ask.load_config") as mock_cfg:
            mock_cfg.return_value = MagicMock(
                memory_id="repo:org/repo",
                llm=MagicMock(provider="anthropic", model="claude-sonnet-4-5-20250929"),
            )
            code = orch.run("org/repo", "question")
        assert code == 0

    def test_enrichment_skips_when_no_refs_found(self):
        """Should skip enrichment when no PR/commit refs in artifacts."""
        mc = MagicMock()
        mc.search.return_value = _make_search_result(2)  # No refs in content
        lc = MagicMock()
        lc.synthesize.return_value = SynthesisResponse(
            answer_text=json.dumps({
                "answer": "Answer",
                "citations": [{"note_id": "note-0"}, {"note_id": "note-1"}],
            }),
        )

        gh_client = MagicMock()
        diff_service = MagicMock()

        orch = _make_orchestrator(
            memory_client=mc,
            llm_client=lc,
            github_client=gh_client,
            diff_summary_service=diff_service,
        )
        with patch("avos_cli.commands.ask.load_config") as mock_cfg:
            mock_cfg.return_value = MagicMock(
                memory_id="repo:org/repo",
                llm=MagicMock(provider="anthropic", model="claude-sonnet-4-5-20250929"),
            )
            code = orch.run("org/repo", "question")

        assert code == 0
        gh_client.get_pr_diff.assert_not_called()
        diff_service.summarize_diffs.assert_not_called()

    def test_enrichment_skips_when_no_summaries_generated(self):
        """Should skip enrichment when diff summary service returns empty."""
        mc = MagicMock()
        mc.search.return_value = _make_search_result_with_refs(1)
        lc = MagicMock()
        lc.synthesize.return_value = SynthesisResponse(
            answer_text=json.dumps({
                "answer": "Answer",
                "citations": [{"note_id": "note-0"}],
            }),
        )

        gh_client = MagicMock()
        gh_client.get_pr_diff.return_value = "diff text"
        gh_client.list_pr_commits.return_value = []

        diff_service = MagicMock()
        diff_service.summarize_diffs.return_value = {}

        orch = _make_orchestrator(
            memory_client=mc,
            llm_client=lc,
            github_client=gh_client,
            diff_summary_service=diff_service,
        )
        with patch("avos_cli.commands.ask.load_config") as mock_cfg:
            mock_cfg.return_value = MagicMock(
                memory_id="repo:org/repo",
                llm=MagicMock(provider="anthropic", model="claude-sonnet-4-5-20250929"),
            )
            code = orch.run("org/repo", "question")

        assert code == 0
