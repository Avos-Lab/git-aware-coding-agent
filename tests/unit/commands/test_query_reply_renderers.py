"""Unit tests for ask/history/session-ask reply rendering helpers.

These tests focus on ANSI/JSON rendering helper branches that are hard to
exercise through orchestrator-only tests.
"""

from __future__ import annotations

from unittest.mock import patch

from avos_cli.commands.ask import _build_raw_output as ask_build_raw_output
from avos_cli.commands.ask import _render_reply_output as ask_render_reply_output
from avos_cli.commands.history import _build_raw_output as history_build_raw_output
from avos_cli.commands.history import _render_reply_output as history_render_reply_output
from avos_cli.commands.session_ask import _build_raw_output as session_build_raw_output
from avos_cli.commands.session_ask import _render_reply_output as session_render_reply_output
from avos_cli.models.query import SanitizedArtifact


def _art(note_id: str, content: str = "content") -> SanitizedArtifact:
    return SanitizedArtifact(
        note_id=note_id,
        content=content,
        created_at="2026-01-01T00:00:00Z",
        rank=1,
    )


class _ReplyServiceStub:
    def __init__(
        self,
        *,
        ask_text: str = "ANSWER: a\n\nEVIDENCE:\n- [n1] x",
        history_text: str = "TIMELINE:\n- 2026 Jan\n\nSUMMARY:\nok",
        ask_json: str | None = None,
        history_json: str | None = None,
    ) -> None:
        self._ask_text = ask_text
        self._history_text = history_text
        self._ask_json = ask_json
        self._history_json = history_json

    def format_ask(self, question: str, raw_output: str) -> str:
        return self._ask_text

    def format_ask_json(self, ask_reply_text: str) -> str | None:
        return self._ask_json

    def format_history(self, subject: str, raw_output: str) -> str:
        return self._history_text

    def format_history_json(self, history_reply_text: str) -> str | None:
        return self._history_json


class TestRawBuilders:
    def test_builders_emit_note_and_separator(self) -> None:
        arts = [_art("n1"), _art("n2")]
        ask_raw = ask_build_raw_output(arts)
        history_raw = history_build_raw_output(arts)
        session_raw = session_build_raw_output(arts)

        for raw in (ask_raw, history_raw, session_raw):
            assert "[n1]" in raw
            assert "---" in raw


class TestAskRenderHelper:
    def test_json_success_path_prints_wrapped_json(self) -> None:
        reply = _ReplyServiceStub(ask_json='{"format":"avos.ask.v1","answer":{"text":"ok"}}')
        with patch("avos_cli.commands.ask.print_json") as print_json_mock:
            ask_render_reply_output("q", "raw", reply, json_output=True)
        print_json_mock.assert_called_once()
        kwargs = print_json_mock.call_args.kwargs
        assert kwargs["success"] is True
        assert kwargs["data"]["format"] == "avos.ask.v1"

    def test_json_invalid_converter_payload_prints_error(self) -> None:
        reply = _ReplyServiceStub(ask_json="not-json")
        with patch("avos_cli.commands.ask.print_json") as print_json_mock:
            ask_render_reply_output("q", "raw", reply, json_output=True)
        kwargs = print_json_mock.call_args.kwargs
        assert kwargs["success"] is False
        assert kwargs["error"]["code"] == "JSON_CONVERSION_FAILED"

    def test_json_missing_converter_payload_prints_error(self) -> None:
        reply = _ReplyServiceStub(ask_json=None)
        with patch("avos_cli.commands.ask.print_json") as print_json_mock:
            ask_render_reply_output("q", "raw", reply, json_output=True)
        kwargs = print_json_mock.call_args.kwargs
        assert kwargs["success"] is False
        assert kwargs["error"]["code"] == "JSON_CONVERSION_FAILED"

    def test_non_json_path_renders_panel_and_evidence_table(self) -> None:
        reply = _ReplyServiceStub(
            ask_text="ANSWER: Uses retries.\n\nEVIDENCE:\n- [n1] PR #1\n- [n2] PR #2"
        )
        with (
            patch("avos_cli.commands.ask.render_panel") as panel_mock,
            patch("avos_cli.commands.ask.render_table") as table_mock,
        ):
            ask_render_reply_output("q", "raw", reply, json_output=False)
        panel_mock.assert_called_once()
        table_mock.assert_called_once()

    def test_non_json_path_without_evidence_skips_table(self) -> None:
        reply = _ReplyServiceStub(ask_text="ANSWER: Uses retries.\n\nEVIDENCE:\n")
        with (
            patch("avos_cli.commands.ask.render_panel") as panel_mock,
            patch("avos_cli.commands.ask.render_table") as table_mock,
        ):
            ask_render_reply_output("q", "raw", reply, json_output=False)
        panel_mock.assert_called_once()
        table_mock.assert_not_called()

    def test_no_reply_service_json_path_reports_unavailable(self) -> None:
        with patch("avos_cli.commands.ask.print_json") as print_json_mock:
            ask_render_reply_output("q", "raw", None, json_output=True)
        kwargs = print_json_mock.call_args.kwargs
        assert kwargs["success"] is False
        assert kwargs["error"]["code"] == "REPLY_SERVICE_UNAVAILABLE"


class TestHistoryRenderHelper:
    def test_json_success_path_prints_wrapped_json(self) -> None:
        reply = _ReplyServiceStub(history_json='{"format":"avos.history.v1","summary":{"text":"ok"}}')
        with patch("avos_cli.commands.history.print_json") as print_json_mock:
            history_render_reply_output("subject", "raw", reply, json_output=True)
        kwargs = print_json_mock.call_args.kwargs
        assert kwargs["success"] is True
        assert kwargs["data"]["format"] == "avos.history.v1"

    def test_json_invalid_converter_payload_prints_error(self) -> None:
        reply = _ReplyServiceStub(history_json="broken-json")
        with patch("avos_cli.commands.history.print_json") as print_json_mock:
            history_render_reply_output("subject", "raw", reply, json_output=True)
        kwargs = print_json_mock.call_args.kwargs
        assert kwargs["success"] is False
        assert kwargs["error"]["code"] == "JSON_CONVERSION_FAILED"

    def test_json_missing_converter_payload_prints_error(self) -> None:
        reply = _ReplyServiceStub(history_json=None)
        with patch("avos_cli.commands.history.print_json") as print_json_mock:
            history_render_reply_output("subject", "raw", reply, json_output=True)
        kwargs = print_json_mock.call_args.kwargs
        assert kwargs["success"] is False
        assert kwargs["error"]["code"] == "JSON_CONVERSION_FAILED"

    def test_non_json_path_renders_timeline_and_summary(self) -> None:
        reply = _ReplyServiceStub(history_text="TIMELINE:\n- Jan\n\nSUMMARY:\nDone")
        with patch("avos_cli.commands.history.render_panel") as panel_mock:
            history_render_reply_output("subject", "raw", reply, json_output=False)
        # Timeline panel + Summary panel
        assert panel_mock.call_count == 2

    def test_non_json_path_without_summary_renders_timeline_only(self) -> None:
        reply = _ReplyServiceStub(history_text="TIMELINE:\n- Jan\n\nSUMMARY:\n")
        with patch("avos_cli.commands.history.render_panel") as panel_mock:
            history_render_reply_output("subject", "raw", reply, json_output=False)
        assert panel_mock.call_count == 1

    def test_no_reply_service_json_path_reports_unavailable(self) -> None:
        with patch("avos_cli.commands.history.print_json") as print_json_mock:
            history_render_reply_output("subject", "raw", None, json_output=True)
        kwargs = print_json_mock.call_args.kwargs
        assert kwargs["success"] is False
        assert kwargs["error"]["code"] == "REPLY_SERVICE_UNAVAILABLE"


class TestSessionAskRenderHelper:
    def test_json_path_prints_converter_output_directly(self, capsys) -> None:
        reply = _ReplyServiceStub(ask_json='{"format":"avos.ask.v1"}')
        session_render_reply_output("q", "raw", reply, json_output=True)
        out = capsys.readouterr().out
        assert '"format":"avos.ask.v1"' in out

    def test_json_path_with_empty_converter_output_reports_error(self) -> None:
        reply = _ReplyServiceStub(ask_json=None)
        with patch("avos_cli.commands.session_ask.print_json") as print_json_mock:
            session_render_reply_output("q", "raw", reply, json_output=True)
        kwargs = print_json_mock.call_args.kwargs
        assert kwargs["success"] is False
        assert kwargs["error"]["code"] == "REPLY_SERVICE_UNAVAILABLE"

    def test_non_json_path_renders_answer_and_evidence(self) -> None:
        reply = _ReplyServiceStub(
            ask_text="ANSWER: Session details.\n\nEVIDENCE:\n- [n1] one\n- [n2] two"
        )
        with (
            patch("avos_cli.commands.session_ask.render_panel") as panel_mock,
            patch("avos_cli.commands.session_ask.render_table") as table_mock,
        ):
            session_render_reply_output("q", "raw", reply, json_output=False)
        panel_mock.assert_called_once()
        table_mock.assert_called_once()

    def test_no_reply_service_non_json_falls_back_to_plain_info(self) -> None:
        with patch("avos_cli.commands.session_ask.print_info") as info_mock:
            session_render_reply_output("q", "raw", None, json_output=False)
        info_mock.assert_called_once_with("raw")
