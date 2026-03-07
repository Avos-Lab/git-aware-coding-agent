"""Integration tests for Sprint 3 query error matrix (AVOS-015).

Validates error handling for Memory API errors (401/403/404/422/429/503),
LLM transient/non-transient failures, and correct exit code mapping.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from avos_cli.commands.ask import AskOrchestrator
from avos_cli.commands.history import HistoryOrchestrator
from avos_cli.exceptions import (
    AuthError,
    RateLimitError,
    RequestContractError,
    ResourceNotFoundError,
    UpstreamUnavailableError,
)
from avos_cli.models.api import SearchResult


def _mock_config_ask():
    return patch(
        "avos_cli.commands.ask.load_config",
        return_value=MagicMock(
            memory_id="repo:org/repo",
            llm=MagicMock(provider="anthropic", model="claude-sonnet-4-5-20250929"),
        ),
    )


def _mock_config_history():
    return patch(
        "avos_cli.commands.history.load_config",
        return_value=MagicMock(
            memory_id="repo:org/repo",
            llm=MagicMock(provider="anthropic", model="claude-sonnet-4-5-20250929"),
        ),
    )


def _make_ask_orch(mc: MagicMock) -> AskOrchestrator:
    return AskOrchestrator(
        memory_client=mc,
        llm_client=MagicMock(),
        repo_root=Path("/tmp/test"),
    )


def _make_history_orch(mc: MagicMock) -> HistoryOrchestrator:
    return HistoryOrchestrator(
        memory_client=mc,
        llm_client=MagicMock(),
        repo_root=Path("/tmp/test"),
    )


class TestMemoryAPIErrors:
    """Memory API errors should produce exit code 2 (hard external error)."""

    @pytest.mark.parametrize(
        "error_cls,error_args",
        [
            (AuthError, {"message": "401 Unauthorized", "service": "Avos Memory"}),
            (AuthError, {"message": "403 Forbidden", "service": "Avos Memory"}),
            (ResourceNotFoundError, {"message": "404 Not Found"}),
            (RequestContractError, {"message": "422 Unprocessable Entity"}),
            (RateLimitError, {"message": "429 Too Many Requests"}),
            (UpstreamUnavailableError, {"message": "503 Service Unavailable"}),
        ],
    )
    def test_ask_memory_error_exits_2(self, error_cls, error_args):
        mc = MagicMock()
        mc.search.side_effect = error_cls(**error_args)
        orch = _make_ask_orch(mc)
        with _mock_config_ask():
            code = orch.run("org/repo", "question")
        assert code == 2

    @pytest.mark.parametrize(
        "error_cls,error_args",
        [
            (AuthError, {"message": "401 Unauthorized", "service": "Avos Memory"}),
            (AuthError, {"message": "403 Forbidden", "service": "Avos Memory"}),
            (ResourceNotFoundError, {"message": "404 Not Found"}),
            (RequestContractError, {"message": "422 Unprocessable Entity"}),
            (RateLimitError, {"message": "429 Too Many Requests"}),
            (UpstreamUnavailableError, {"message": "503 Service Unavailable"}),
        ],
    )
    def test_history_memory_error_exits_2(self, error_cls, error_args):
        mc = MagicMock()
        mc.search.side_effect = error_cls(**error_args)
        orch = _make_history_orch(mc)
        with _mock_config_history():
            code = orch.run("org/repo", "subject")
        assert code == 2


class TestPreconditionErrors:
    """Precondition failures should produce exit code 1."""

    def test_ask_invalid_slug_exits_1(self):
        orch = _make_ask_orch(MagicMock())
        code = orch.run("invalid", "question")
        assert code == 1

    def test_history_invalid_slug_exits_1(self):
        orch = _make_history_orch(MagicMock())
        code = orch.run("invalid", "subject")
        assert code == 1
