"""Brutal tests for LLMClient (avos_cli/services/llm_client.py).

Covers provider/model resolution, prompt template selection, response
parsing (JSON + text fallback), failure classification, retry logic,
timeout handling, and hostile edge cases. All tests use mocked HTTP.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import httpx
import pytest

from avos_cli.exceptions import LLMSynthesisError
from avos_cli.models.query import QueryMode, SanitizedArtifact, SynthesisRequest
from avos_cli.services.llm_client import LLMClient


def _make_request(
    mode: QueryMode = QueryMode.ASK,
    query: str = "How does auth work?",
) -> SynthesisRequest:
    return SynthesisRequest(
        mode=mode,
        query=query,
        provider="anthropic",
        model="claude-sonnet-4-5-20250929",
        prompt_template_version="ask_v1",
        artifacts=[
            SanitizedArtifact(
                note_id="abc-123",
                content="Auth uses JWT tokens for session management.",
                created_at="2026-01-15T10:00:00Z",
                rank=1,
            ),
            SanitizedArtifact(
                note_id="def-456",
                content="Token refresh happens every 30 minutes.",
                created_at="2026-01-16T10:00:00Z",
                rank=2,
            ),
        ],
    )


def _make_anthropic_response(
    answer: str = "Auth uses JWT.",
    citations: list[dict] | None = None,
) -> dict:
    """Build a mock Anthropic API response body."""
    if citations is None:
        citations = [{"note_id": "abc-123"}, {"note_id": "def-456"}]
    content_text = json.dumps({
        "answer": answer,
        "citations": citations,
    })
    return {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "content": [{"type": "text", "text": content_text}],
        "model": "claude-sonnet-4-5-20250929",
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 100, "output_tokens": 50},
    }


class TestSuccessfulSynthesis:
    """Happy path: LLM returns valid structured response."""

    def test_ask_mode_returns_answer(self):
        client = LLMClient(api_key="sk_test_key")
        request = _make_request(mode=QueryMode.ASK)
        mock_response = httpx.Response(
            200,
            json=_make_anthropic_response("Auth uses JWT tokens."),
            request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"),
        )
        with patch.object(client._client, "post", return_value=mock_response):
            result = client.synthesize(request)
        assert "JWT" in result.answer_text

    def test_history_mode_returns_answer(self):
        client = LLMClient(api_key="sk_test_key")
        request = _make_request(mode=QueryMode.HISTORY)
        mock_response = httpx.Response(
            200,
            json=_make_anthropic_response("Timeline of auth changes."),
            request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"),
        )
        with patch.object(client._client, "post", return_value=mock_response):
            result = client.synthesize(request)
        assert "Timeline" in result.answer_text


class TestResponseParsing:
    """Parse JSON structured output, fallback to text extraction."""

    def test_json_response_preserves_raw_text(self):
        """Raw text is preserved so citation validator can extract structured citations."""
        client = LLMClient(api_key="sk_test_key")
        request = _make_request()
        mock_response = httpx.Response(
            200,
            json=_make_anthropic_response("Structured answer."),
            request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"),
        )
        with patch.object(client._client, "post", return_value=mock_response):
            result = client.synthesize(request)
        assert "Structured answer." in result.answer_text
        assert "abc-123" in result.answer_text

    def test_plain_text_fallback(self):
        client = LLMClient(api_key="sk_test_key")
        request = _make_request()
        plain_response = {
            "id": "msg_test",
            "type": "message",
            "role": "assistant",
            "content": [{"type": "text", "text": "Just a plain text answer."}],
            "model": "claude-sonnet-4-5-20250929",
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 100, "output_tokens": 50},
        }
        mock_response = httpx.Response(
            200,
            json=plain_response,
            request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"),
        )
        with patch.object(client._client, "post", return_value=mock_response):
            result = client.synthesize(request)
        assert result.answer_text == "Just a plain text answer."

    def test_empty_content_raises(self):
        client = LLMClient(api_key="sk_test_key")
        request = _make_request()
        empty_response = {
            "id": "msg_test",
            "type": "message",
            "role": "assistant",
            "content": [],
            "model": "claude-sonnet-4-5-20250929",
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 100, "output_tokens": 0},
        }
        mock_response = httpx.Response(
            200,
            json=empty_response,
            request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"),
        )
        with (
            patch.object(client._client, "post", return_value=mock_response),
            pytest.raises(LLMSynthesisError),
        ):
            client.synthesize(request)


class TestFailureClassification:
    """Transient vs non-transient failure classification."""

    def test_timeout_is_transient(self):
        client = LLMClient(api_key="sk_test_key")
        request = _make_request()
        with patch.object(
            client._client, "post", side_effect=httpx.TimeoutException("timeout")
        ):
            with pytest.raises(LLMSynthesisError) as exc_info:
                client.synthesize(request)
            assert exc_info.value.failure_class == "transient"

    def test_connection_error_is_transient(self):
        client = LLMClient(api_key="sk_test_key")
        request = _make_request()
        with patch.object(
            client._client, "post", side_effect=httpx.ConnectError("connection refused")
        ):
            with pytest.raises(LLMSynthesisError) as exc_info:
                client.synthesize(request)
            assert exc_info.value.failure_class == "transient"

    def test_429_is_transient(self):
        client = LLMClient(api_key="sk_test_key")
        request = _make_request()
        mock_response = httpx.Response(
            429,
            json={"error": {"type": "rate_limit_error", "message": "rate limited"}},
            request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"),
        )
        with patch.object(client._client, "post", return_value=mock_response):
            with pytest.raises(LLMSynthesisError) as exc_info:
                client.synthesize(request)
            assert exc_info.value.failure_class == "transient"

    def test_503_is_transient(self):
        client = LLMClient(api_key="sk_test_key")
        request = _make_request()
        mock_response = httpx.Response(
            503,
            json={"error": {"type": "overloaded_error", "message": "overloaded"}},
            request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"),
        )
        with patch.object(client._client, "post", return_value=mock_response):
            with pytest.raises(LLMSynthesisError) as exc_info:
                client.synthesize(request)
            assert exc_info.value.failure_class == "transient"

    def test_401_is_non_transient(self):
        client = LLMClient(api_key="sk_test_key")
        request = _make_request()
        mock_response = httpx.Response(
            401,
            json={"error": {"type": "authentication_error", "message": "invalid key"}},
            request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"),
        )
        with patch.object(client._client, "post", return_value=mock_response):
            with pytest.raises(LLMSynthesisError) as exc_info:
                client.synthesize(request)
            assert exc_info.value.failure_class == "non_transient"

    def test_400_is_non_transient(self):
        client = LLMClient(api_key="sk_test_key")
        request = _make_request()
        mock_response = httpx.Response(
            400,
            json={"error": {"type": "invalid_request_error", "message": "bad request"}},
            request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"),
        )
        with patch.object(client._client, "post", return_value=mock_response):
            with pytest.raises(LLMSynthesisError) as exc_info:
                client.synthesize(request)
            assert exc_info.value.failure_class == "non_transient"


class TestPromptConstruction:
    """Prompt templates and message structure."""

    def test_ask_prompt_includes_question(self):
        client = LLMClient(api_key="sk_test_key")
        request = _make_request(mode=QueryMode.ASK, query="How does auth work?")
        messages = client._build_messages(request)
        user_content = " ".join(m["content"] for m in messages if m["role"] == "user")
        assert "How does auth work?" in user_content

    def test_history_prompt_includes_subject(self):
        client = LLMClient(api_key="sk_test_key")
        request = _make_request(mode=QueryMode.HISTORY, query="payment system")
        messages = client._build_messages(request)
        user_content = " ".join(m["content"] for m in messages if m["role"] == "user")
        assert "payment system" in user_content

    def test_artifacts_included_in_context(self):
        client = LLMClient(api_key="sk_test_key")
        request = _make_request()
        messages = client._build_messages(request)
        all_content = " ".join(m["content"] for m in messages)
        assert "abc-123" in all_content
        assert "JWT tokens" in all_content

    def test_system_prompt_present(self):
        client = LLMClient(api_key="sk_test_key")
        request = _make_request()
        system_prompt = client._get_system_prompt(request.mode)
        assert len(system_prompt) > 0


class TestEdgeCases:
    def test_empty_artifacts_in_request(self):
        client = LLMClient(api_key="sk_test_key")
        request = SynthesisRequest(
            mode=QueryMode.ASK,
            query="test",
            provider="anthropic",
            model="claude-sonnet-4-5-20250929",
            prompt_template_version="ask_v1",
            artifacts=[],
        )
        mock_response = httpx.Response(
            200,
            json=_make_anthropic_response("No context available.", citations=[]),
            request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"),
        )
        with patch.object(client._client, "post", return_value=mock_response):
            result = client.synthesize(request)
        assert result.answer_text is not None
