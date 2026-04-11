"""Unit tests for DiffSummaryService.

Tests the service that summarizes git diffs using the REPLY_MODEL
via the git_diff_agent.md prompt template.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx

from avos_cli.models.diff import DiffReferenceType, DiffResult, DiffStatus
from avos_cli.services.diff_summary_service import DiffSummaryService


class TestDiffSummaryServiceInit:
    """Tests for DiffSummaryService initialization."""

    def test_init_stores_credentials(self) -> None:
        """Should store API credentials correctly."""
        service = DiffSummaryService(
            api_key="test-key",
            api_url="https://api.example.com/v1/chat/completions",
            model="gpt-4",
        )
        assert service._api_key == "test-key"
        assert service._api_url == "https://api.example.com/v1/chat/completions"
        assert service._model == "gpt-4"

    def test_init_strips_trailing_slash_from_url(self) -> None:
        """Should strip trailing slash from API URL."""
        service = DiffSummaryService(
            api_key="test-key",
            api_url="https://api.example.com/v1/",
            model="gpt-4",
        )
        assert service._api_url == "https://api.example.com/v1"


class TestSummarizeDiffs:
    """Tests for summarize_diffs method."""

    def _make_resolved_diff(
        self,
        canonical_id: str,
        diff_text: str,
        ref_type: DiffReferenceType = DiffReferenceType.PR,
    ) -> DiffResult:
        """Helper to create a resolved DiffResult."""
        return DiffResult(
            reference_type=ref_type,
            canonical_id=canonical_id,
            repo="org/repo",
            diff_text=diff_text,
            status=DiffStatus.RESOLVED,
        )

    def _make_unresolved_diff(self, canonical_id: str) -> DiffResult:
        """Helper to create an unresolved DiffResult."""
        return DiffResult(
            reference_type=DiffReferenceType.PR,
            canonical_id=canonical_id,
            repo="org/repo",
            status=DiffStatus.UNRESOLVED,
            error_message="Not found",
        )

    def _make_suppressed_diff(self, canonical_id: str) -> DiffResult:
        """Helper to create a suppressed DiffResult."""
        return DiffResult(
            reference_type=DiffReferenceType.COMMIT,
            canonical_id=canonical_id,
            repo="org/repo",
            status=DiffStatus.SUPPRESSED,
            suppressed_reason="covered_by_pr:123",
        )

    def test_empty_results_returns_empty_dict(self) -> None:
        """Should return empty dict for empty input."""
        service = DiffSummaryService(
            api_key="test-key",
            api_url="https://api.example.com/v1/chat/completions",
            model="gpt-4",
        )
        result = service.summarize_diffs([])
        assert result == {}

    def test_skips_unresolved_diffs(self) -> None:
        """Should skip unresolved diffs and not call API."""
        service = DiffSummaryService(
            api_key="test-key",
            api_url="https://api.example.com/v1/chat/completions",
            model="gpt-4",
        )
        with patch.object(service, "_client") as mock_client:
            result = service.summarize_diffs([self._make_unresolved_diff("PR #1")])
            mock_client.post.assert_not_called()
            assert result == {}

    def test_skips_suppressed_diffs(self) -> None:
        """Should skip suppressed diffs and not call API."""
        service = DiffSummaryService(
            api_key="test-key",
            api_url="https://api.example.com/v1/chat/completions",
            model="gpt-4",
        )
        with patch.object(service, "_client") as mock_client:
            result = service.summarize_diffs([self._make_suppressed_diff("abc123")])
            mock_client.post.assert_not_called()
            assert result == {}

    def test_summarizes_resolved_diff(self) -> None:
        """Should call API and return summary for resolved diff."""
        service = DiffSummaryService(
            api_key="test-key",
            api_url="https://api.example.com/v1/chat/completions",
            model="gpt-4",
        )

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "## Summary\nThis diff adds a feature."}}]
        }

        with patch.object(service, "_client") as mock_client:
            mock_client.post.return_value = mock_response

            diff = self._make_resolved_diff("PR #123", "diff --git a/foo.py b/foo.py\n+new line")
            result = service.summarize_diffs([diff])

            assert "PR #123" in result
            assert result["PR #123"] == "## Summary\nThis diff adds a feature."
            mock_client.post.assert_called_once()

    def test_summarizes_multiple_resolved_diffs(self) -> None:
        """Should summarize multiple resolved diffs."""
        service = DiffSummaryService(
            api_key="test-key",
            api_url="https://api.example.com/v1/chat/completions",
            model="gpt-4",
        )

        mock_response_1 = MagicMock()
        mock_response_1.status_code = 200
        mock_response_1.json.return_value = {
            "choices": [{"message": {"content": "Summary for PR 1"}}]
        }

        mock_response_2 = MagicMock()
        mock_response_2.status_code = 200
        mock_response_2.json.return_value = {
            "choices": [{"message": {"content": "Summary for commit"}}]
        }

        with patch.object(service, "_client") as mock_client:
            mock_client.post.side_effect = [mock_response_1, mock_response_2]

            diffs = [
                self._make_resolved_diff("PR #1", "diff 1"),
                self._make_resolved_diff("abc123", "diff 2", DiffReferenceType.COMMIT),
            ]
            result = service.summarize_diffs(diffs)

            assert len(result) == 2
            assert result["PR #1"] == "Summary for PR 1"
            assert result["abc123"] == "Summary for commit"

    def test_handles_api_error_gracefully(self) -> None:
        """Should skip diff on API error and continue with others."""
        service = DiffSummaryService(
            api_key="test-key",
            api_url="https://api.example.com/v1/chat/completions",
            model="gpt-4",
        )

        mock_response_error = MagicMock()
        mock_response_error.status_code = 500
        mock_response_error.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Server error", request=MagicMock(), response=mock_response_error
        )

        mock_response_ok = MagicMock()
        mock_response_ok.status_code = 200
        mock_response_ok.json.return_value = {
            "choices": [{"message": {"content": "Summary 2"}}]
        }

        with patch.object(service, "_client") as mock_client:
            mock_client.post.side_effect = [mock_response_error, mock_response_ok]

            diffs = [
                self._make_resolved_diff("PR #1", "diff 1"),
                self._make_resolved_diff("PR #2", "diff 2"),
            ]
            result = service.summarize_diffs(diffs)

            assert "PR #1" not in result
            assert result["PR #2"] == "Summary 2"

    def test_handles_empty_choices(self) -> None:
        """Should skip diff when API returns empty choices."""
        service = DiffSummaryService(
            api_key="test-key",
            api_url="https://api.example.com/v1/chat/completions",
            model="gpt-4",
        )

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"choices": []}

        with patch.object(service, "_client") as mock_client:
            mock_client.post.return_value = mock_response

            diff = self._make_resolved_diff("PR #1", "diff text")
            result = service.summarize_diffs([diff])

            assert result == {}

    def test_handles_missing_content(self) -> None:
        """Should skip diff when API returns no content."""
        service = DiffSummaryService(
            api_key="test-key",
            api_url="https://api.example.com/v1/chat/completions",
            model="gpt-4",
        )

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"choices": [{"message": {}}]}

        with patch.object(service, "_client") as mock_client:
            mock_client.post.return_value = mock_response

            diff = self._make_resolved_diff("PR #1", "diff text")
            result = service.summarize_diffs([diff])

            assert result == {}

    def test_skips_diff_with_none_diff_text(self) -> None:
        """Should skip resolved diff with None diff_text."""
        service = DiffSummaryService(
            api_key="test-key",
            api_url="https://api.example.com/v1/chat/completions",
            model="gpt-4",
        )

        diff = DiffResult(
            reference_type=DiffReferenceType.PR,
            canonical_id="PR #1",
            repo="org/repo",
            diff_text=None,
            status=DiffStatus.RESOLVED,
        )

        with patch.object(service, "_client") as mock_client:
            result = service.summarize_diffs([diff])
            mock_client.post.assert_not_called()
            assert result == {}

    def test_mixed_diff_statuses(self) -> None:
        """Should only summarize resolved diffs with valid diff_text."""
        service = DiffSummaryService(
            api_key="test-key",
            api_url="https://api.example.com/v1/chat/completions",
            model="gpt-4",
        )

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "Good summary"}}]
        }

        with patch.object(service, "_client") as mock_client:
            mock_client.post.return_value = mock_response

            diffs = [
                self._make_unresolved_diff("PR #1"),
                self._make_suppressed_diff("abc123"),
                self._make_resolved_diff("PR #2", "valid diff"),
            ]
            result = service.summarize_diffs(diffs)

            assert len(result) == 1
            assert result["PR #2"] == "Good summary"
            mock_client.post.assert_called_once()


class TestPromptLoading:
    """Tests for prompt template loading."""

    def test_loads_git_diff_agent_prompt(self) -> None:
        """Should load the git_diff_agent.md prompt template."""
        service = DiffSummaryService(
            api_key="test-key",
            api_url="https://api.example.com/v1/chat/completions",
            model="gpt-4",
        )

        prompt = service._load_prompt("test diff content")
        assert "GIT DIFF:" in prompt
        assert "test diff content" in prompt
        assert "Git Diff Analyst" in prompt
