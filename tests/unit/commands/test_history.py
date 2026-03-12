"""Brutal tests for HistoryOrchestrator (avos_cli/commands/history.py).

Covers full pipeline: search -> chronology -> sanitize -> budget ->
synthesize -> ground -> render/fallback. Tests happy path, empty state,
LLM failure, grounding failure, and Memory API errors.
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


def _make_orchestrator(
    memory_client: MagicMock | None = None,
    llm_client: MagicMock | None = None,
    repo_root: Path | None = None,
) -> HistoryOrchestrator:
    mc = memory_client or MagicMock()
    lc = llm_client or MagicMock()
    rr = repo_root or Path("/tmp/test-repo")
    return HistoryOrchestrator(
        memory_client=mc,
        llm_client=lc,
        repo_root=rr,
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

    def test_sanitization_safety_block_fallback_branch(self):
        mc = MagicMock()
        mc.search.return_value = _make_search_result(2)
        orch = _make_orchestrator(memory_client=mc, llm_client=MagicMock())
        orch._sanitizer.sanitize = MagicMock(
            return_value=MagicMock(
                confidence_score=10,
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
