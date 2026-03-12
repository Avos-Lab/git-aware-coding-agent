"""Unit tests for ReplyOutputService.

Covers parse functions, dumb formatters, truncation, and ReplyOutputService
with mocked HTTP.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from avos_cli.services.reply_output_service import (
    ReplyOutputService,
    dumb_format_ask,
    dumb_format_history,
    parse_ask_response,
    parse_history_response,
)


class TestParseAskResponse:
    def test_parses_answer_and_evidence(self):
        response = "ANSWER:\nAuth uses JWT tokens.\n\nEVIDENCE:\nPR #123 Title @alice\nCommit abc Title"
        answer, evidence = parse_ask_response(response)
        assert "Auth uses JWT" in answer
        assert evidence == ["PR #123 Title @alice", "Commit abc Title"]

    def test_handles_none_evidence(self):
        response = "ANSWER:\nNo relevant data.\n\nEVIDENCE:\n(none)"
        answer, evidence = parse_ask_response(response)
        assert "No relevant" in answer
        assert evidence == []

    def test_handles_missing_evidence_section(self):
        response = "ANSWER:\nJust an answer."
        answer, evidence = parse_ask_response(response)
        assert "Just an answer" in answer
        assert evidence == []


class TestParseHistoryResponse:
    def test_parses_timeline_and_summary(self):
        response = "TIMELINE:\nMar 2026 — BUG FIX\nPR #1 x\n\nSUMMARY:\nEvolution summary here."
        timeline, summary = parse_history_response(response)
        assert "Mar 2026" in timeline
        assert "Evolution summary" in summary

    def test_handles_missing_summary(self):
        response = "TIMELINE:\nNo history."
        timeline, summary = parse_history_response(response)
        assert "No history" in timeline
        assert summary == ""


class TestDumbFormatAsk:
    def test_extracts_pr_evidence(self):
        raw = "[note-1] (2026-01-01)\n[type: raw_pr_thread]\n[pr: #42]\n[author: bob]\nTitle: Add feature\n---"
        out = dumb_format_ask(raw)
        assert "ANSWER:" in out
        assert "EVIDENCE:" in out
        assert "PR #42" in out or "42" in out

    def test_extracts_issue_evidence(self):
        raw = "[note-1] (2026-01-01)\n[type: raw_issue]\n[issue: #99]\nTitle: Bug report\n---"
        out = dumb_format_ask(raw)
        assert "ANSWER:" in out
        assert "Issue #99" in out

    def test_extracts_commit_evidence(self):
        raw = "[note-1] (2026-01-01)\n[type: commit]\n[hash: abc123]\n[author: carol]\nMessage: fix bug\n---"
        out = dumb_format_ask(raw)
        assert "ANSWER:" in out
        assert "Commit" in out

    def test_empty_raw_returns_valid_format(self):
        out = dumb_format_ask("")
        assert "ANSWER:" in out
        assert "EVIDENCE:" in out
        assert "(none)" in out


class TestDumbFormatHistory:
    def test_extracts_events(self):
        raw = "[note-1] (2026-01-01)\n[pr: #10]\nTitle: Feature\n---"
        out = dumb_format_history(raw)
        assert "TIMELINE:" in out
        assert "SUMMARY:" in out

    def test_empty_raw_returns_valid_format(self):
        out = dumb_format_history("")
        assert "TIMELINE:" in out
        assert "SUMMARY:" in out


class TestReplyOutputService:
    def test_format_ask_returns_none_on_http_error(self):
        svc = ReplyOutputService(api_key="key", api_url="https://test.com/v1/chat/completions", model="test")
        with patch.object(svc._client, "post", side_effect=Exception("network error")):
            result = svc.format_ask("question", "raw artifacts")
        assert result is None

    def test_format_history_returns_none_on_http_error(self):
        svc = ReplyOutputService(api_key="key", api_url="https://test.com/v1/chat/completions", model="test")
        with patch.object(svc._client, "post", side_effect=Exception("timeout")):
            result = svc.format_history("subject", "raw artifacts")
        assert result is None

    def test_format_ask_returns_content_on_success(self):
        svc = ReplyOutputService(api_key="key", api_url="https://test.com/v1/chat/completions", model="test")
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "ANSWER:\nx\n\nEVIDENCE:\na\nb"}}]
        }
        with patch.object(svc._client, "post", return_value=mock_response):
            result = svc.format_ask("q", "raw")
        assert result is not None
        assert "ANSWER:" in result
        assert "EVIDENCE:" in result


class TestFormatAskJson:
    """Tests for format_ask_json converter method."""

    def test_returns_none_on_http_error(self):
        svc = ReplyOutputService(api_key="key", api_url="https://test.com/v1/chat/completions", model="test")
        with patch.object(svc._client, "post", side_effect=Exception("network error")):
            result = svc.format_ask_json("ANSWER:\nTest\n\nEVIDENCE:\n(none)")
        assert result is None

    def test_returns_json_string_on_success(self):
        svc = ReplyOutputService(api_key="key", api_url="https://test.com/v1/chat/completions", model="test")
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": '{"format": "avos.ask.v1", "answer": {"text": "Test"}}'}}]
        }
        with patch.object(svc._client, "post", return_value=mock_response):
            result = svc.format_ask_json("ANSWER:\nTest\n\nEVIDENCE:\n(none)")
        assert result is not None
        assert "avos.ask.v1" in result

    def test_returns_none_on_empty_choices(self):
        svc = ReplyOutputService(api_key="key", api_url="https://test.com/v1/chat/completions", model="test")
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {"choices": []}
        with patch.object(svc._client, "post", return_value=mock_response):
            result = svc.format_ask_json("ANSWER:\nTest\n\nEVIDENCE:\n(none)")
        assert result is None


class TestFormatHistoryJson:
    """Tests for format_history_json converter method."""

    def test_returns_none_on_http_error(self):
        svc = ReplyOutputService(api_key="key", api_url="https://test.com/v1/chat/completions", model="test")
        with patch.object(svc._client, "post", side_effect=Exception("timeout")):
            result = svc.format_history_json("TIMELINE:\nMar 2026\n\nSUMMARY:\nTest")
        assert result is None

    def test_returns_json_string_on_success(self):
        svc = ReplyOutputService(api_key="key", api_url="https://test.com/v1/chat/completions", model="test")
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": '{"format": "avos.history.v1", "timeline": {"is_empty_history": false}}'}}]
        }
        with patch.object(svc._client, "post", return_value=mock_response):
            result = svc.format_history_json("TIMELINE:\nMar 2026\n\nSUMMARY:\nTest")
        assert result is not None
        assert "avos.history.v1" in result

    def test_returns_none_on_empty_choices(self):
        svc = ReplyOutputService(api_key="key", api_url="https://test.com/v1/chat/completions", model="test")
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {"choices": []}
        with patch.object(svc._client, "post", return_value=mock_response):
            result = svc.format_history_json("TIMELINE:\nMar 2026\n\nSUMMARY:\nTest")
        assert result is None
