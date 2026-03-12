"""Tests for SessionAskOrchestrator (avos_cli/commands/session_ask.py).

Covers search over Memory B (session), hybrid mode, empty state,
and precondition failures.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from avos_cli.commands.session_ask import SessionAskOrchestrator
from avos_cli.exceptions import ConfigurationNotInitializedError
from avos_cli.models.api import SearchHit, SearchResult
from avos_cli.models.query import SynthesisResponse


def _make_search_result(count: int = 3) -> SearchResult:
    hits = [
        SearchHit(
            note_id=f"note-{i}",
            content=f"[type: wip_activity] Session content {i}.",
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
) -> SessionAskOrchestrator:
    mc = memory_client or MagicMock()
    lc = llm_client or MagicMock()
    rr = repo_root or Path("/tmp/test-repo")
    return SessionAskOrchestrator(
        memory_client=mc,
        llm_client=lc,
        repo_root=rr,
    )


class TestHappyPath:
    """Session-ask searches Memory B with hybrid mode."""

    def test_successful_session_ask_returns_zero(self):
        mc = MagicMock()
        mc.search.return_value = _make_search_result(3)

        lc = MagicMock()
        lc.synthesize.return_value = SynthesisResponse(
            answer_text=json.dumps({
                "answer": "Session work uses WIP artifacts.",
                "citations": [{"note_id": "note-0"}, {"note_id": "note-1"}],
            }),
        )

        orch = _make_orchestrator(memory_client=mc, llm_client=lc)
        with patch("avos_cli.commands.session_ask.load_config") as mock_cfg:
            mock_cfg.return_value = MagicMock(
                memory_id="repo:org/repo",
                memory_id_session="repo:org/repo-session",
                llm=MagicMock(provider="anthropic", model="claude-sonnet-4-5-20250929"),
            )
            code = orch.run("org/repo", "What is the team working on?")
        assert code == 0

    def test_search_uses_memory_id_session_and_hybrid_mode(self):
        mc = MagicMock()
        mc.search.return_value = _make_search_result(3)

        lc = MagicMock()
        lc.synthesize.return_value = SynthesisResponse(
            answer_text=json.dumps({
                "answer": "Session work.",
                "citations": [{"note_id": "note-0"}, {"note_id": "note-1"}],
            }),
        )

        orch = _make_orchestrator(memory_client=mc, llm_client=lc)
        with patch("avos_cli.commands.session_ask.load_config") as mock_cfg:
            mock_cfg.return_value = MagicMock(
                memory_id="repo:org/repo",
                memory_id_session="repo:org/repo-session",
                llm=MagicMock(provider="anthropic", model="claude-sonnet-4-5-20250929"),
            )
            orch.run("org/repo", "What is the team working on?")
        mc.search.assert_called_once()
        call_kwargs = mc.search.call_args.kwargs
        assert call_kwargs["memory_id"] == "repo:org/repo-session"
        assert call_kwargs["mode"] == "hybrid"


class TestEmptyState:
    """Empty search results -> helpful message."""

    def test_empty_results_returns_zero(self):
        mc = MagicMock()
        mc.search.return_value = SearchResult(results=[], total_count=0)
        lc = MagicMock()

        orch = _make_orchestrator(memory_client=mc, llm_client=lc)
        with patch("avos_cli.commands.session_ask.load_config") as mock_cfg:
            mock_cfg.return_value = MagicMock(
                memory_id="repo:org/repo",
                memory_id_session="repo:org/repo-session",
                llm=MagicMock(provider="anthropic", model="claude-sonnet-4-5-20250929"),
            )
            code = orch.run("org/repo", "What is happening?")
        assert code == 0
        lc.synthesize.assert_not_called()


class TestPreconditionFailures:
    """Config/slug errors -> exit 1."""

    def test_invalid_repo_slug_returns_one(self):
        orch = _make_orchestrator()
        code = orch.run("invalid_slug", "question")
        assert code == 1

    def test_config_not_initialized_returns_one(self):
        mc = MagicMock()
        orch = _make_orchestrator(memory_client=mc)
        with patch("avos_cli.commands.session_ask.load_config") as mock_cfg:
            mock_cfg.side_effect = ConfigurationNotInitializedError()
            code = orch.run("org/repo", "question")
        assert code == 1
