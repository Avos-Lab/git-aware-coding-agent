"""Tests for DiffResolver.

Covers coverage index building, PR-Wins deduplication logic,
patch extraction orchestration, and error handling.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from avos_cli.models.diff import (
    DedupDecision,
    DiffReferenceType,
    DiffStatus,
    ParsedReference,
)
from avos_cli.services.diff_resolver import DiffResolver


@pytest.fixture()
def mock_github_client() -> MagicMock:
    return MagicMock()


@pytest.fixture()
def mock_git_client() -> MagicMock:
    return MagicMock()


@pytest.fixture()
def resolver(mock_github_client: MagicMock, mock_git_client: MagicMock) -> DiffResolver:
    return DiffResolver(
        github_client=mock_github_client,
        git_client=mock_git_client,
        repo_path=Path("/tmp/repo"),
    )


class TestBuildCoverageIndex:
    """Tests for _build_coverage_index method."""

    def test_single_pr_with_commits(
        self, resolver: DiffResolver, mock_github_client: MagicMock
    ):
        """Test coverage index with single PR containing commits."""
        mock_github_client.list_pr_commits.return_value = [
            "abc123def456789012345678901234567890abcd",
            "def456789012345678901234567890abcdef12",
        ]

        pr_refs = [
            ParsedReference(
                reference_type=DiffReferenceType.PR,
                raw_id="1245",
                repo_slug="org/repo",
            )
        ]

        index = resolver._build_coverage_index(pr_refs)

        assert "abc123def456789012345678901234567890abcd" in index
        assert "def456789012345678901234567890abcdef12" in index
        assert 1245 in index["abc123def456789012345678901234567890abcd"]
        assert 1245 in index["def456789012345678901234567890abcdef12"]

    def test_multiple_prs_with_overlapping_commits(
        self, resolver: DiffResolver, mock_github_client: MagicMock
    ):
        """Test coverage index with multiple PRs sharing commits."""
        mock_github_client.list_pr_commits.side_effect = [
            ["sha1_full_40_chars_padding_to_40_chars"],
            ["sha1_full_40_chars_padding_to_40_chars", "sha2_unique_to_pr2_padding"],
        ]

        pr_refs = [
            ParsedReference(
                reference_type=DiffReferenceType.PR,
                raw_id="100",
                repo_slug="org/repo",
            ),
            ParsedReference(
                reference_type=DiffReferenceType.PR,
                raw_id="200",
                repo_slug="org/repo",
            ),
        ]

        index = resolver._build_coverage_index(pr_refs)

        assert 100 in index["sha1_full_40_chars_padding_to_40_chars"]
        assert 200 in index["sha1_full_40_chars_padding_to_40_chars"]
        assert 200 in index["sha2_unique_to_pr2_padding"]
        assert 100 not in index["sha2_unique_to_pr2_padding"]

    def test_empty_pr_list(self, resolver: DiffResolver):
        """Test coverage index with no PRs."""
        index = resolver._build_coverage_index([])
        assert index == {}

    def test_pr_with_no_commits(
        self, resolver: DiffResolver, mock_github_client: MagicMock
    ):
        """Test coverage index when PR has no commits."""
        mock_github_client.list_pr_commits.return_value = []

        pr_refs = [
            ParsedReference(
                reference_type=DiffReferenceType.PR,
                raw_id="1",
                repo_slug="org/repo",
            )
        ]

        index = resolver._build_coverage_index(pr_refs)
        assert index == {}


class TestApplyDedup:
    """Tests for _apply_dedup method (PR-Wins rule)."""

    def test_pr_always_kept(
        self, resolver: DiffResolver, mock_github_client: MagicMock
    ):
        """Test that PR references are always kept."""
        mock_github_client.list_pr_commits.return_value = ["sha1"]

        pr_ref = ParsedReference(
            reference_type=DiffReferenceType.PR,
            raw_id="1245",
            repo_slug="org/repo",
        )

        plan = resolver._apply_dedup([pr_ref], {"sha1": {1245}})

        assert len(plan) == 1
        assert plan[0].decision == DedupDecision.KEEP

    def test_commit_covered_by_pr_suppressed(
        self, resolver: DiffResolver, mock_git_client: MagicMock
    ):
        """Test that commit covered by a PR is suppressed."""
        mock_git_client.expand_short_sha.return_value = (
            "abc123def456789012345678901234567890abcd"
        )

        commit_ref = ParsedReference(
            reference_type=DiffReferenceType.COMMIT,
            raw_id="abc123d",
            repo_slug="org/repo",
        )

        coverage_index = {"abc123def456789012345678901234567890abcd": {1245}}

        plan = resolver._apply_dedup([commit_ref], coverage_index)

        assert len(plan) == 1
        assert plan[0].decision == DedupDecision.SUPPRESS_COVERED_BY_PR
        assert plan[0].covered_by_pr == 1245

    def test_commit_not_covered_kept(
        self, resolver: DiffResolver, mock_git_client: MagicMock
    ):
        """Test that commit not covered by any PR is kept."""
        mock_git_client.expand_short_sha.return_value = (
            "xyz789def456789012345678901234567890abcd"
        )

        commit_ref = ParsedReference(
            reference_type=DiffReferenceType.COMMIT,
            raw_id="xyz789d",
            repo_slug="org/repo",
        )

        coverage_index = {"abc123def456789012345678901234567890abcd": {1245}}

        plan = resolver._apply_dedup([commit_ref], coverage_index)

        assert len(plan) == 1
        assert plan[0].decision == DedupDecision.KEEP

    def test_commit_covered_by_multiple_prs(
        self, resolver: DiffResolver, mock_git_client: MagicMock
    ):
        """Test commit covered by multiple PRs picks first PR."""
        mock_git_client.expand_short_sha.return_value = (
            "abc123def456789012345678901234567890abcd"
        )

        commit_ref = ParsedReference(
            reference_type=DiffReferenceType.COMMIT,
            raw_id="abc123d",
            repo_slug="org/repo",
        )

        coverage_index = {"abc123def456789012345678901234567890abcd": {100, 200, 300}}

        plan = resolver._apply_dedup([commit_ref], coverage_index)

        assert plan[0].decision == DedupDecision.SUPPRESS_COVERED_BY_PR
        assert plan[0].covered_by_pr in {100, 200, 300}


class TestExtractDiff:
    """Tests for _extract_diff method."""

    def test_extract_pr_diff(
        self, resolver: DiffResolver, mock_github_client: MagicMock
    ):
        """Test extracting diff for a PR reference."""
        mock_github_client.get_pr_diff.return_value = "diff --git a/file.py b/file.py\n+new"

        from avos_cli.models.diff import DedupPlanItem, ResolvedReference

        resolved = ResolvedReference(
            reference_type=DiffReferenceType.PR,
            canonical_id="PR #1245",
            repo_slug="org/repo",
            pr_number=1245,
        )
        plan_item = DedupPlanItem(reference=resolved, decision=DedupDecision.KEEP)

        result = resolver._extract_diff(plan_item)

        assert result.status == DiffStatus.RESOLVED
        assert result.diff_text == "diff --git a/file.py b/file.py\n+new"
        assert result.canonical_id == "PR #1245"

    def test_extract_commit_diff(
        self, resolver: DiffResolver, mock_git_client: MagicMock
    ):
        """Test extracting diff for a commit reference."""
        mock_git_client.commit_patch.return_value = "diff --git a/file.py b/file.py\n-old\n+new"

        from avos_cli.models.diff import DedupPlanItem, ResolvedReference

        resolved = ResolvedReference(
            reference_type=DiffReferenceType.COMMIT,
            canonical_id="abc123def456789012345678901234567890abcd",
            repo_slug="org/repo",
            full_sha="abc123def456789012345678901234567890abcd",
        )
        plan_item = DedupPlanItem(reference=resolved, decision=DedupDecision.KEEP)

        result = resolver._extract_diff(plan_item)

        assert result.status == DiffStatus.RESOLVED
        assert "diff --git" in result.diff_text

    def test_extract_suppressed_commit(self, resolver: DiffResolver):
        """Test that suppressed commits return suppressed status."""
        from avos_cli.models.diff import DedupPlanItem, ResolvedReference

        resolved = ResolvedReference(
            reference_type=DiffReferenceType.COMMIT,
            canonical_id="abc123def456789012345678901234567890abcd",
            repo_slug="org/repo",
            full_sha="abc123def456789012345678901234567890abcd",
        )
        plan_item = DedupPlanItem(
            reference=resolved,
            decision=DedupDecision.SUPPRESS_COVERED_BY_PR,
            covered_by_pr=1245,
            reason="Covered by PR #1245",
        )

        result = resolver._extract_diff(plan_item)

        assert result.status == DiffStatus.SUPPRESSED
        assert result.diff_text is None
        assert "1245" in result.suppressed_reason


class TestResolve:
    """Tests for the main resolve method."""

    def test_resolve_single_pr(
        self, resolver: DiffResolver, mock_github_client: MagicMock
    ):
        """Test resolving a single PR reference."""
        mock_github_client.list_pr_commits.return_value = ["sha1", "sha2"]
        mock_github_client.get_pr_diff.return_value = "diff content"

        refs = [
            ParsedReference(
                reference_type=DiffReferenceType.PR,
                raw_id="1245",
                repo_slug="org/repo",
            )
        ]

        results = resolver.resolve(refs)

        assert len(results) == 1
        assert results[0].status == DiffStatus.RESOLVED
        assert results[0].canonical_id == "PR #1245"

    def test_resolve_single_commit(
        self, resolver: DiffResolver, mock_git_client: MagicMock
    ):
        """Test resolving a single commit reference."""
        mock_git_client.expand_short_sha.return_value = (
            "abc123def456789012345678901234567890abcd"
        )
        mock_git_client.commit_patch.return_value = "diff content"

        refs = [
            ParsedReference(
                reference_type=DiffReferenceType.COMMIT,
                raw_id="abc123d",
                repo_slug="org/repo",
            )
        ]

        results = resolver.resolve(refs)

        assert len(results) == 1
        assert results[0].status == DiffStatus.RESOLVED

    def test_resolve_pr_and_overlapping_commit(
        self,
        resolver: DiffResolver,
        mock_github_client: MagicMock,
        mock_git_client: MagicMock,
    ):
        """Test PR-Wins: commit covered by PR is suppressed."""
        mock_github_client.list_pr_commits.return_value = [
            "abc123def456789012345678901234567890abcd"
        ]
        mock_github_client.get_pr_diff.return_value = "pr diff"
        mock_git_client.expand_short_sha.return_value = (
            "abc123def456789012345678901234567890abcd"
        )

        refs = [
            ParsedReference(
                reference_type=DiffReferenceType.PR,
                raw_id="1245",
                repo_slug="org/repo",
            ),
            ParsedReference(
                reference_type=DiffReferenceType.COMMIT,
                raw_id="abc123d",
                repo_slug="org/repo",
            ),
        ]

        results = resolver.resolve(refs)

        assert len(results) == 2
        pr_result = next(r for r in results if r.reference_type == DiffReferenceType.PR)
        commit_result = next(
            r for r in results if r.reference_type == DiffReferenceType.COMMIT
        )

        assert pr_result.status == DiffStatus.RESOLVED
        assert commit_result.status == DiffStatus.SUPPRESSED

    def test_resolve_pr_and_independent_commit(
        self,
        resolver: DiffResolver,
        mock_github_client: MagicMock,
        mock_git_client: MagicMock,
    ):
        """Test that independent commit is kept."""
        mock_github_client.list_pr_commits.return_value = ["sha_in_pr"]
        mock_github_client.get_pr_diff.return_value = "pr diff"
        mock_git_client.expand_short_sha.return_value = (
            "independent_sha_not_in_pr_padding"
        )
        mock_git_client.commit_patch.return_value = "commit diff"

        refs = [
            ParsedReference(
                reference_type=DiffReferenceType.PR,
                raw_id="1245",
                repo_slug="org/repo",
            ),
            ParsedReference(
                reference_type=DiffReferenceType.COMMIT,
                raw_id="indepen",
                repo_slug="org/repo",
            ),
        ]

        results = resolver.resolve(refs)

        assert len(results) == 2
        assert all(r.status == DiffStatus.RESOLVED for r in results)

    def test_resolve_empty_list(self, resolver: DiffResolver):
        """Test resolving empty reference list."""
        results = resolver.resolve([])
        assert results == []


class TestErrorHandling:
    """Tests for error handling in diff resolution."""

    def test_pr_not_found_returns_unresolved(
        self, resolver: DiffResolver, mock_github_client: MagicMock
    ):
        """Test that PR not found returns unresolved status."""
        from avos_cli.exceptions import ResourceNotFoundError

        mock_github_client.list_pr_commits.side_effect = ResourceNotFoundError(
            "PR not found"
        )
        mock_github_client.get_pr_diff.side_effect = ResourceNotFoundError(
            "PR not found"
        )

        refs = [
            ParsedReference(
                reference_type=DiffReferenceType.PR,
                raw_id="9999",
                repo_slug="org/repo",
            )
        ]

        results = resolver.resolve(refs)

        assert len(results) == 1
        assert results[0].status == DiffStatus.UNRESOLVED
        assert results[0].error_message is not None

    def test_commit_sha_expansion_fails(
        self, resolver: DiffResolver, mock_git_client: MagicMock
    ):
        """Test that failed SHA expansion returns unresolved."""
        mock_git_client.expand_short_sha.return_value = None

        refs = [
            ParsedReference(
                reference_type=DiffReferenceType.COMMIT,
                raw_id="invalid",
                repo_slug="org/repo",
            )
        ]

        results = resolver.resolve(refs)

        assert len(results) == 1
        assert results[0].status == DiffStatus.UNRESOLVED

    def test_missing_repo_slug_returns_unresolved(self, resolver: DiffResolver):
        """Test that missing repo slug returns unresolved."""
        refs = [
            ParsedReference(
                reference_type=DiffReferenceType.PR,
                raw_id="1245",
                repo_slug=None,
            )
        ]

        results = resolver.resolve(refs)

        assert len(results) == 1
        assert results[0].status == DiffStatus.UNRESOLVED
        assert "repo" in results[0].error_message.lower()


class TestFormatOutput:
    """Tests for format_output method."""

    def test_format_resolved_pr(
        self, resolver: DiffResolver, mock_github_client: MagicMock
    ):
        """Test formatting resolved PR output."""
        mock_github_client.list_pr_commits.return_value = []
        mock_github_client.get_pr_diff.return_value = "diff --git a/f.py b/f.py\n+new"

        refs = [
            ParsedReference(
                reference_type=DiffReferenceType.PR,
                raw_id="1245",
                repo_slug="org/repo",
            )
        ]

        results = resolver.resolve(refs)
        output = resolver.format_output(results)

        assert "=== PR #1245 ===" in output
        assert "diff --git" in output

    def test_format_suppressed_commit(self, resolver: DiffResolver):
        """Test formatting suppressed commit output."""
        from avos_cli.models.diff import DiffResult

        results = [
            DiffResult(
                reference_type=DiffReferenceType.COMMIT,
                canonical_id="abc123def456",
                repo="org/repo",
                status=DiffStatus.SUPPRESSED,
                suppressed_reason="covered_by_pr:1245",
            )
        ]

        output = resolver.format_output(results)

        assert "=== COMMIT abc123def456 ===" in output
        assert "[suppressed:" in output
        assert "1245" in output
