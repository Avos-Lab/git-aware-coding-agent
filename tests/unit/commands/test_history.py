"""Brutal tests for HistoryOrchestrator (avos_cli/commands/history.py).

Covers full pipeline: search -> chronology -> sanitize -> budget ->
synthesize -> ground -> render/fallback. Tests happy path, empty state,
LLM failure, grounding failure, and Memory API errors.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from avos_cli.commands.history import HistoryOrchestrator
from avos_cli.exceptions import (
    AuthError,
    ConfigurationNotInitializedError,
    LLMSynthesisError,
    UpstreamUnavailableError,
)
from avos_cli.models.api import SearchHit, SearchResult
from avos_cli.models.query import SynthesisResponse


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
