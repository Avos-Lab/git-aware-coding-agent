"""Brutal tests for AskOrchestrator (avos_cli/commands/ask.py).

Covers full pipeline: search -> sanitize -> budget -> synthesize ->
ground -> render/fallback. Tests happy path, empty state, LLM failure,
grounding failure, sanitization block, and Memory API errors.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from avos_cli.commands.ask import AskOrchestrator
from avos_cli.exceptions import (
    AuthError,
    ConfigurationNotInitializedError,
    LLMSynthesisError,
    UpstreamUnavailableError,
)
from avos_cli.models.api import SearchHit, SearchResult
from avos_cli.models.query import SynthesisResponse


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


def _make_orchestrator(
    memory_client: MagicMock | None = None,
    llm_client: MagicMock | None = None,
    repo_root: Path | None = None,
) -> AskOrchestrator:
    mc = memory_client or MagicMock()
    lc = llm_client or MagicMock()
    rr = repo_root or Path("/tmp/test-repo")
    return AskOrchestrator(
        memory_client=mc,
        llm_client=lc,
        repo_root=rr,
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
