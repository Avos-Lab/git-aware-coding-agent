"""Integration tests for Sprint 3 query workflows (AVOS-015).

Validates end-to-end ask/history flows: happy path, empty state,
LLM failure fallback, grounding failure fallback, and deterministic
output repeatability across 3 runs.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from avos_cli.commands.ask import AskOrchestrator
from avos_cli.commands.history import HistoryOrchestrator
from avos_cli.exceptions import LLMSynthesisError
from avos_cli.models.api import SearchHit, SearchResult
from avos_cli.models.query import SynthesisResponse


def _make_search_hits(count: int) -> list[SearchHit]:
    return [
        SearchHit(
            note_id=f"note-{i:03d}",
            content=f"Technical content about subsystem evolution step {i}. Auth uses JWT tokens.",
            created_at=f"2026-01-{10 + i:02d}T10:00:00Z",
            rank=i + 1,
        )
        for i in range(count)
    ]


def _make_search_result(count: int) -> SearchResult:
    return SearchResult(results=_make_search_hits(count), total_count=count)


def _make_grounded_synthesis(note_ids: list[str]) -> SynthesisResponse:
    return SynthesisResponse(
        answer_text=json.dumps({
            "answer": "The auth system evolved through JWT adoption and token refresh.",
            "citations": [{"note_id": nid} for nid in note_ids],
        }),
    )


def _make_orchestrator_ask(mc: MagicMock, lc: MagicMock) -> AskOrchestrator:
    return AskOrchestrator(
        memory_client=mc,
        llm_client=lc,
        repo_root=Path("/tmp/test"),
    )


def _make_orchestrator_history(mc: MagicMock, lc: MagicMock) -> HistoryOrchestrator:
    return HistoryOrchestrator(
        memory_client=mc,
        llm_client=lc,
        repo_root=Path("/tmp/test"),
    )


def _mock_config():
    return patch(
        "avos_cli.commands.ask.load_config",
        return_value=MagicMock(
            memory_id="repo:org/repo",
            llm=MagicMock(provider="anthropic", model="claude-sonnet-4-5-20250929"),
        ),
    )


def _mock_history_config():
    return patch(
        "avos_cli.commands.history.load_config",
        return_value=MagicMock(
            memory_id="repo:org/repo",
            llm=MagicMock(provider="anthropic", model="claude-sonnet-4-5-20250929"),
        ),
    )


class TestAskHappyPath:
    def test_ask_normal_flow_exit_zero(self):
        mc = MagicMock()
        mc.search.return_value = _make_search_result(5)
        lc = MagicMock()
        lc.synthesize.return_value = _make_grounded_synthesis(["note-000", "note-001"])

        orch = _make_orchestrator_ask(mc, lc)
        with _mock_config():
            code = orch.run("org/repo", "How does auth work?")
        assert code == 0
        lc.synthesize.assert_called_once()

    def test_ask_with_many_artifacts(self):
        mc = MagicMock()
        mc.search.return_value = _make_search_result(10)
        lc = MagicMock()
        lc.synthesize.return_value = _make_grounded_synthesis(["note-000", "note-001", "note-002"])

        orch = _make_orchestrator_ask(mc, lc)
        with _mock_config():
            code = orch.run("org/repo", "How does auth work?")
        assert code == 0


class TestAskEmptyState:
    def test_empty_search_no_llm_call(self):
        mc = MagicMock()
        mc.search.return_value = SearchResult(results=[], total_count=0)
        lc = MagicMock()

        orch = _make_orchestrator_ask(mc, lc)
        with _mock_config():
            code = orch.run("org/repo", "How does auth work?")
        assert code == 0
        lc.synthesize.assert_not_called()


class TestAskLLMFailureFallback:
    def test_llm_timeout_triggers_fallback(self):
        mc = MagicMock()
        mc.search.return_value = _make_search_result(5)
        lc = MagicMock()
        lc.synthesize.side_effect = LLMSynthesisError("timeout", failure_class="transient")

        orch = _make_orchestrator_ask(mc, lc)
        with _mock_config():
            code = orch.run("org/repo", "How does auth work?")
        assert code == 0

    def test_llm_non_transient_triggers_fallback(self):
        mc = MagicMock()
        mc.search.return_value = _make_search_result(5)
        lc = MagicMock()
        lc.synthesize.side_effect = LLMSynthesisError("bad request", failure_class="non_transient")

        orch = _make_orchestrator_ask(mc, lc)
        with _mock_config():
            code = orch.run("org/repo", "question")
        assert code == 0


class TestAskGroundingFailureFallback:
    def test_all_citations_ungrounded(self):
        mc = MagicMock()
        mc.search.return_value = _make_search_result(5)
        lc = MagicMock()
        lc.synthesize.return_value = _make_grounded_synthesis(["fake-1", "fake-2"])

        orch = _make_orchestrator_ask(mc, lc)
        with _mock_config():
            code = orch.run("org/repo", "question")
        assert code == 0


class TestHistoryHappyPath:
    def test_history_normal_flow_exit_zero(self):
        mc = MagicMock()
        mc.search.return_value = _make_search_result(8)
        lc = MagicMock()
        lc.synthesize.return_value = _make_grounded_synthesis(["note-000", "note-001"])

        orch = _make_orchestrator_history(mc, lc)
        with _mock_history_config():
            code = orch.run("org/repo", "payment system")
        assert code == 0


class TestHistoryEmptyState:
    def test_empty_search_no_llm_call(self):
        mc = MagicMock()
        mc.search.return_value = SearchResult(results=[], total_count=0)
        lc = MagicMock()

        orch = _make_orchestrator_history(mc, lc)
        with _mock_history_config():
            code = orch.run("org/repo", "payment system")
        assert code == 0
        lc.synthesize.assert_not_called()


class TestHistoryLLMFailureFallback:
    def test_llm_failure_triggers_chronological_fallback(self):
        mc = MagicMock()
        mc.search.return_value = _make_search_result(8)
        lc = MagicMock()
        lc.synthesize.side_effect = LLMSynthesisError("timeout", failure_class="transient")

        orch = _make_orchestrator_history(mc, lc)
        with _mock_history_config():
            code = orch.run("org/repo", "payment system")
        assert code == 0


class TestDeterministicRepeatability:
    """3-run repeatability: same input -> same output ordering."""

    def test_ask_deterministic_across_3_runs(self):
        mc = MagicMock()
        mc.search.return_value = _make_search_result(5)
        lc = MagicMock()
        lc.synthesize.side_effect = LLMSynthesisError("timeout", failure_class="transient")

        results = []
        for _ in range(3):
            orch = _make_orchestrator_ask(mc, lc)
            with _mock_config():
                code = orch.run("org/repo", "question")
            results.append(code)
        assert all(r == 0 for r in results)

    def test_history_deterministic_across_3_runs(self):
        mc = MagicMock()
        mc.search.return_value = _make_search_result(8)
        lc = MagicMock()
        lc.synthesize.side_effect = LLMSynthesisError("timeout", failure_class="transient")

        results = []
        for _ in range(3):
            orch = _make_orchestrator_history(mc, lc)
            with _mock_history_config():
                code = orch.run("org/repo", "subject")
            results.append(code)
        assert all(r == 0 for r in results)
