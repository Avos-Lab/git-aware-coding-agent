"""Brutal tests for HistoryOrchestrator (avos_cli/commands/history.py).

Covers full pipeline: search -> diff enrichment -> chronology -> sanitize -> budget ->
synthesize -> ground -> render/fallback. Tests happy path, empty state,
LLM failure, grounding failure, Memory API errors, and diff enrichment.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from avos_cli.commands.history import HistoryOrchestrator
from avos_cli.exceptions import (
    AuthError,
    ConfigurationNotInitializedError,
    LLMSynthesisError,
    RepositoryContextError,
    UpstreamUnavailableError,
)
from avos_cli.models.api import SearchHit, SearchResult
from avos_cli.models.query import SanitizedArtifact, SynthesisResponse


def _make_search_result(count: int = 5) -> SearchResult:
    hits = [
        SearchHit(
            note_id=f"note-{i}",
            content=f"Content about payment system evolution step {i}.",
            created_at=f"2026-01-{10+i:02d}T10:00:00Z",
            rank=i + 1,
        )
        for i in range(count)
    ]
    return SearchResult(results=hits, total_count=count)


def _make_search_result_with_refs(count: int = 2) -> SearchResult:
    """Create search result with PR/commit references in content."""
    hits = [
        SearchHit(
            note_id=f"note-{i}",
            content=f"[pr: #{100 + i}] [hash: abc{i}def] Content about payment step {i}.",
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
) -> HistoryOrchestrator:
    mc = memory_client or MagicMock()
    lc = llm_client or MagicMock()
    rr = repo_root or Path("/tmp/test-repo")
    return HistoryOrchestrator(
        memory_client=mc,
        llm_client=lc,
        repo_root=rr,
        github_client=github_client,
        diff_summary_service=diff_summary_service,
    )


class TestHappyPath:
    def test_successful_history_returns_zero(self):
        mc = MagicMock()
        mc.search.return_value = _make_search_result(5)
        lc = MagicMock()
        lc.synthesize.return_value = SynthesisResponse(
            answer_text=json.dumps({
                "answer": "Payment system evolved through 3 phases.",
                "citations": [{"note_id": "note-0"}, {"note_id": "note-1"}],
            }),
        )

        orch = _make_orchestrator(memory_client=mc, llm_client=lc)
        with patch("avos_cli.commands.history.load_config") as mock_cfg:
            mock_cfg.return_value = MagicMock(memory_id="repo:org/repo", llm=MagicMock(provider="anthropic", model="claude-sonnet-4-5-20250929"))
            code = orch.run("org/repo", "payment system")
        assert code == 0

    def test_search_uses_hybrid_mode_k20(self):
        mc = MagicMock()
        mc.search.return_value = _make_search_result(5)
        lc = MagicMock()
        lc.synthesize.return_value = SynthesisResponse(
            answer_text=json.dumps({
                "answer": "Timeline.",
                "citations": [{"note_id": "note-0"}, {"note_id": "note-1"}],
            }),
        )

        orch = _make_orchestrator(memory_client=mc, llm_client=lc)
        with patch("avos_cli.commands.history.load_config") as mock_cfg:
            mock_cfg.return_value = MagicMock(memory_id="repo:org/repo", llm=MagicMock(provider="anthropic", model="claude-sonnet-4-5-20250929"))
            orch.run("org/repo", "payment system")
        mc.search.assert_called_once()
        call_kwargs = mc.search.call_args
        assert call_kwargs[1].get("k") == 20
        assert call_kwargs[1].get("mode") == "hybrid"


class TestEmptyState:
    def test_empty_results_returns_zero(self):
        mc = MagicMock()
        mc.search.return_value = SearchResult(results=[], total_count=0)
        lc = MagicMock()

        orch = _make_orchestrator(memory_client=mc, llm_client=lc)
        with patch("avos_cli.commands.history.load_config") as mock_cfg:
            mock_cfg.return_value = MagicMock(memory_id="repo:org/repo", llm=MagicMock(provider="anthropic", model="claude-sonnet-4-5-20250929"))
            code = orch.run("org/repo", "payment system")
        assert code == 0
        lc.synthesize.assert_not_called()


class TestLLMFailure:
    def test_llm_failure_triggers_fallback(self):
        mc = MagicMock()
        mc.search.return_value = _make_search_result(5)
        lc = MagicMock()
        lc.synthesize.side_effect = LLMSynthesisError("timeout", failure_class="transient")

        orch = _make_orchestrator(memory_client=mc, llm_client=lc)
        with patch("avos_cli.commands.history.load_config") as mock_cfg:
            mock_cfg.return_value = MagicMock(memory_id="repo:org/repo", llm=MagicMock(provider="anthropic", model="claude-sonnet-4-5-20250929"))
            code = orch.run("org/repo", "payment system")
        assert code == 0


class TestPreconditionFailures:
    def test_invalid_slug_returns_one(self):
        orch = _make_orchestrator()
        code = orch.run("invalid-slug", "subject")
        assert code == 1

    def test_config_not_initialized_returns_one(self):
        orch = _make_orchestrator()
        with patch("avos_cli.commands.history.load_config", side_effect=ConfigurationNotInitializedError()):
            code = orch.run("org/repo", "subject")
        assert code == 1


class TestMemoryAPIErrors:
    def test_auth_error_returns_two(self):
        mc = MagicMock()
        mc.search.side_effect = AuthError("unauthorized", service="Avos Memory")
        orch = _make_orchestrator(memory_client=mc)
        with patch("avos_cli.commands.history.load_config") as mock_cfg:
            mock_cfg.return_value = MagicMock(memory_id="repo:org/repo", llm=MagicMock(provider="anthropic", model="claude-sonnet-4-5-20250929"))
            code = orch.run("org/repo", "subject")
        assert code == 2

    def test_upstream_unavailable_returns_two(self):
        mc = MagicMock()
        mc.search.side_effect = UpstreamUnavailableError("API down")
        orch = _make_orchestrator(memory_client=mc)
        with patch("avos_cli.commands.history.load_config") as mock_cfg:
            mock_cfg.return_value = MagicMock(memory_id="repo:org/repo", llm=MagicMock(provider="anthropic", model="claude-sonnet-4-5-20250929"))
            code = orch.run("org/repo", "subject")
        assert code == 2


class TestGroundingFailure:
    def test_ungrounded_response_triggers_fallback(self):
        mc = MagicMock()
        mc.search.return_value = _make_search_result(5)
        lc = MagicMock()
        lc.synthesize.return_value = SynthesisResponse(
            answer_text=json.dumps({
                "answer": "Hallucinated timeline.",
                "citations": [{"note_id": "fake-1"}, {"note_id": "fake-2"}],
            }),
        )

        orch = _make_orchestrator(memory_client=mc, llm_client=lc)
        with patch("avos_cli.commands.history.load_config") as mock_cfg:
            mock_cfg.return_value = MagicMock(memory_id="repo:org/repo", llm=MagicMock(provider="anthropic", model="claude-sonnet-4-5-20250929"))
            code = orch.run("org/repo", "subject")
        assert code == 0


class TestJsonOutputMode:
    """Tests for --json mode output."""

    def test_json_mode_invalid_slug_emits_json_error(self, capsys):
        orch = _make_orchestrator()
        code = orch.run("invalid-slug", "subject", json_output=True)
        assert code == 1
        captured = capsys.readouterr()
        out = captured.out
        assert '"success": false' in out or '"success":false' in out
        assert "REPOSITORY_CONTEXT_ERROR" in out

    def test_json_mode_config_not_initialized_emits_json_error(self, capsys):
        orch = _make_orchestrator()
        with patch("avos_cli.commands.history.load_config", side_effect=ConfigurationNotInitializedError()):
            code = orch.run("org/repo", "subject", json_output=True)
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
        with patch("avos_cli.commands.history.load_config") as mock_cfg:
            mock_cfg.return_value = MagicMock(memory_id="repo:org/repo", llm=MagicMock(provider="anthropic", model="claude-sonnet-4-5-20250929"))
            code = orch.run("org/repo", "payment system", json_output=True)
        assert code == 0
        captured = capsys.readouterr()
        out = captured.out
        assert '"success": true' in out or '"success":true' in out
        assert "avos.history.v1" in out

    def test_json_mode_no_reply_service_emits_error(self, capsys):
        mc = MagicMock()
        mc.search.return_value = _make_search_result(5)
        lc = MagicMock()
        lc.synthesize.return_value = SynthesisResponse(
            answer_text=json.dumps({
                "answer": "Payment system evolved.",
                "citations": [{"note_id": "note-0"}, {"note_id": "note-1"}],
            }),
        )

        orch = _make_orchestrator(memory_client=mc, llm_client=lc)
        with patch("avos_cli.commands.history.load_config") as mock_cfg:
            mock_cfg.return_value = MagicMock(memory_id="repo:org/repo", llm=MagicMock(provider="anthropic", model="claude-sonnet-4-5-20250929"))
            code = orch.run("org/repo", "payment system", json_output=True)
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
            "avos_cli.commands.history.load_config",
            side_effect=RepositoryContextError("repo context failed"),
        ):
            code = orch.run("org/repo", "subject", json_output=True)
        assert code == 1
        out = capsys.readouterr().out
        assert "REPOSITORY_CONTEXT_ERROR" in out

    def test_config_avos_error_human_mode_returns_one(self, capsys):
        orch = _make_orchestrator()
        with patch(
            "avos_cli.commands.history.load_config",
            side_effect=RepositoryContextError("repo context failed"),
        ):
            code = orch.run("org/repo", "subject", json_output=False)
        assert code == 1

    def test_memory_search_error_json_mode_returns_two(self, capsys):
        mc = MagicMock()
        mc.search.side_effect = AuthError("unauthorized", service="Avos Memory")
        orch = _make_orchestrator(memory_client=mc)
        with patch("avos_cli.commands.history.load_config") as mock_cfg:
            mock_cfg.return_value = MagicMock(
                memory_id="repo:org/repo",
                llm=MagicMock(provider="anthropic", model="claude-sonnet-4-5-20250929"),
            )
            code = orch.run("org/repo", "subject", json_output=True)
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
                redaction_types=["api_key"],
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
        with patch("avos_cli.commands.history.load_config") as mock_cfg:
            mock_cfg.return_value = MagicMock(
                memory_id="repo:org/repo",
                llm=MagicMock(provider="anthropic", model="claude-sonnet-4-5-20250929"),
            )
            code = orch.run("org/repo", "subject")
        assert code == 0
        captured = capsys.readouterr()
        combined = captured.out + captured.err
        assert "10/100" in combined
        assert "API key" in combined

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
        with patch("avos_cli.commands.history.load_config") as mock_cfg:
            mock_cfg.return_value = MagicMock(
                memory_id="repo:org/repo",
                llm=MagicMock(provider="anthropic", model="claude-sonnet-4-5-20250929"),
            )
            code = orch.run("org/repo", "subject")
        assert code == 0


class TestDiffEnrichment:
    """Tests for diff enrichment stage in history command."""

    def test_skips_enrichment_when_no_github_client(self):
        """Should skip enrichment gracefully when github_client is None."""
        mc = MagicMock()
        mc.search.return_value = _make_search_result_with_refs(2)
        lc = MagicMock()
        lc.synthesize.return_value = SynthesisResponse(
            answer_text=json.dumps({
                "answer": "Timeline",
                "citations": [{"note_id": "note-0"}, {"note_id": "note-1"}],
            }),
        )

        orch = _make_orchestrator(
            memory_client=mc,
            llm_client=lc,
            github_client=None,
            diff_summary_service=MagicMock(),
        )
        with patch("avos_cli.commands.history.load_config") as mock_cfg:
            mock_cfg.return_value = MagicMock(
                memory_id="repo:org/repo",
                llm=MagicMock(provider="anthropic", model="claude-sonnet-4-5-20250929"),
            )
            code = orch.run("org/repo", "subject")
        assert code == 0

    def test_skips_enrichment_when_no_diff_summary_service(self):
        """Should skip enrichment gracefully when diff_summary_service is None."""
        mc = MagicMock()
        mc.search.return_value = _make_search_result_with_refs(2)
        lc = MagicMock()
        lc.synthesize.return_value = SynthesisResponse(
            answer_text=json.dumps({
                "answer": "Timeline",
                "citations": [{"note_id": "note-0"}, {"note_id": "note-1"}],
            }),
        )

        orch = _make_orchestrator(
            memory_client=mc,
            llm_client=lc,
            github_client=MagicMock(),
            diff_summary_service=None,
        )
        with patch("avos_cli.commands.history.load_config") as mock_cfg:
            mock_cfg.return_value = MagicMock(
                memory_id="repo:org/repo",
                llm=MagicMock(provider="anthropic", model="claude-sonnet-4-5-20250929"),
            )
            code = orch.run("org/repo", "subject")
        assert code == 0

    def test_enrichment_injects_diff_summary_into_artifacts(self):
        """Should inject diff summaries into artifact content."""
        mc = MagicMock()
        mc.search.return_value = _make_search_result_with_refs(1)

        lc = MagicMock()
        lc.synthesize.return_value = SynthesisResponse(
            answer_text=json.dumps({
                "answer": "Timeline with diff context",
                "citations": [{"note_id": "note-0"}],
            }),
        )

        gh_client = MagicMock()
        gh_client.get_pr_diff.return_value = "diff --git a/foo.py b/foo.py\n+new line"
        gh_client.list_pr_commits.return_value = ["abc0def1234567890123456789012345678901234"]

        diff_service = MagicMock()
        diff_service.summarize_diffs.return_value = {
            "PR #100": "## Summary\nThis PR adds payment feature."
        }

        orch = _make_orchestrator(
            memory_client=mc,
            llm_client=lc,
            github_client=gh_client,
            diff_summary_service=diff_service,
        )

        with patch("avos_cli.commands.history.load_config") as mock_cfg:
            mock_cfg.return_value = MagicMock(
                memory_id="repo:org/repo",
                llm=MagicMock(provider="anthropic", model="claude-sonnet-4-5-20250929"),
            )
            with patch.object(orch, "_chronology") as mock_chrono:
                mock_chrono.sort.side_effect = lambda x: x
                with patch.object(orch, "_sanitizer") as mock_sanitizer:
                    mock_sanitizer.sanitize.return_value = MagicMock(
                        confidence_score=100,
                        artifacts=[
                            SanitizedArtifact(
                                note_id="note-0",
                                content="[pr: #100] Content\n\n--- Diff Summary ---\n## Summary\nThis PR adds payment feature.",
                                created_at="2026-01-10T10:00:00Z",
                                rank=1,
                            )
                        ],
                    )
                    code = orch.run("org/repo", "subject")

        assert code == 0
        mock_chrono.sort.assert_called_once()
        artifacts_passed = mock_chrono.sort.call_args[0][0]
        assert len(artifacts_passed) == 1
        assert "--- Diff Summary ---" in artifacts_passed[0].content

    def test_enrichment_handles_exception_gracefully(self):
        """Should skip enrichment and continue when exception occurs."""
        mc = MagicMock()
        mc.search.return_value = _make_search_result_with_refs(2)
        lc = MagicMock()
        lc.synthesize.return_value = SynthesisResponse(
            answer_text=json.dumps({
                "answer": "Timeline",
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
        with patch("avos_cli.commands.history.load_config") as mock_cfg:
            mock_cfg.return_value = MagicMock(
                memory_id="repo:org/repo",
                llm=MagicMock(provider="anthropic", model="claude-sonnet-4-5-20250929"),
            )
            code = orch.run("org/repo", "subject")
        assert code == 0

    def test_enrichment_skips_when_no_refs_found(self):
        """Should skip enrichment when no PR/commit refs in artifacts."""
        mc = MagicMock()
        mc.search.return_value = _make_search_result(2)  # No refs in content
        lc = MagicMock()
        lc.synthesize.return_value = SynthesisResponse(
            answer_text=json.dumps({
                "answer": "Timeline",
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
        with patch("avos_cli.commands.history.load_config") as mock_cfg:
            mock_cfg.return_value = MagicMock(
                memory_id="repo:org/repo",
                llm=MagicMock(provider="anthropic", model="claude-sonnet-4-5-20250929"),
            )
            code = orch.run("org/repo", "subject")

        assert code == 0
        gh_client.get_pr_diff.assert_not_called()
        diff_service.summarize_diffs.assert_not_called()
