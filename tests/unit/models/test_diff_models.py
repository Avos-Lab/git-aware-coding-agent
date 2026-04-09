"""Tests for diff pipeline Pydantic models.

Covers model validation, frozen constraints, enum values, and edge cases
for ParsedReference, ResolvedReference, DedupPlanItem, and DiffResult.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from avos_cli.models.diff import (
    DedupDecision,
    DedupPlanItem,
    DiffReferenceType,
    DiffResult,
    DiffStatus,
    ParsedReference,
    ResolvedReference,
)


class TestDiffReferenceType:
    """Tests for DiffReferenceType enum."""

    def test_pr_value(self):
        assert DiffReferenceType.PR.value == "pr"

    def test_commit_value(self):
        assert DiffReferenceType.COMMIT.value == "commit"

    def test_string_comparison(self):
        assert DiffReferenceType.PR == "pr"
        assert DiffReferenceType.COMMIT == "commit"


class TestDedupDecision:
    """Tests for DedupDecision enum."""

    def test_keep_value(self):
        assert DedupDecision.KEEP.value == "keep"

    def test_suppress_covered_by_pr_value(self):
        assert DedupDecision.SUPPRESS_COVERED_BY_PR.value == "suppress_covered_by_pr"


class TestDiffStatus:
    """Tests for DiffStatus enum."""

    def test_resolved_value(self):
        assert DiffStatus.RESOLVED.value == "resolved"

    def test_unresolved_value(self):
        assert DiffStatus.UNRESOLVED.value == "unresolved"

    def test_suppressed_value(self):
        assert DiffStatus.SUPPRESSED.value == "suppressed"


class TestParsedReference:
    """Tests for ParsedReference model."""

    def test_pr_reference_creation(self):
        ref = ParsedReference(
            reference_type=DiffReferenceType.PR,
            raw_id="1245",
            repo_slug="org/repo",
        )
        assert ref.reference_type == DiffReferenceType.PR
        assert ref.raw_id == "1245"
        assert ref.repo_slug == "org/repo"

    def test_commit_reference_creation(self):
        ref = ParsedReference(
            reference_type=DiffReferenceType.COMMIT,
            raw_id="8c3a1b2",
            repo_slug="org/repo",
        )
        assert ref.reference_type == DiffReferenceType.COMMIT
        assert ref.raw_id == "8c3a1b2"
        assert ref.repo_slug == "org/repo"

    def test_frozen_model(self):
        ref = ParsedReference(
            reference_type=DiffReferenceType.PR,
            raw_id="1245",
            repo_slug="org/repo",
        )
        with pytest.raises(ValidationError):
            ref.raw_id = "9999"

    def test_required_fields(self):
        with pytest.raises(ValidationError):
            ParsedReference(reference_type=DiffReferenceType.PR, raw_id="1245")

    def test_repo_slug_optional_none(self):
        ref = ParsedReference(
            reference_type=DiffReferenceType.PR,
            raw_id="1245",
            repo_slug=None,
        )
        assert ref.repo_slug is None


class TestResolvedReference:
    """Tests for ResolvedReference model."""

    def test_pr_resolved_reference(self):
        ref = ResolvedReference(
            reference_type=DiffReferenceType.PR,
            canonical_id="PR #1245",
            repo_slug="org/repo",
            pr_number=1245,
            commit_shas=["abc123def456", "789xyz000111"],
        )
        assert ref.reference_type == DiffReferenceType.PR
        assert ref.canonical_id == "PR #1245"
        assert ref.pr_number == 1245
        assert len(ref.commit_shas) == 2
        assert ref.full_sha is None

    def test_commit_resolved_reference(self):
        ref = ResolvedReference(
            reference_type=DiffReferenceType.COMMIT,
            canonical_id="abc123def456789012345678901234567890abcd",
            repo_slug="org/repo",
            full_sha="abc123def456789012345678901234567890abcd",
        )
        assert ref.reference_type == DiffReferenceType.COMMIT
        assert ref.full_sha == "abc123def456789012345678901234567890abcd"
        assert ref.pr_number is None
        assert ref.commit_shas == []

    def test_frozen_model(self):
        ref = ResolvedReference(
            reference_type=DiffReferenceType.COMMIT,
            canonical_id="abc123",
            repo_slug="org/repo",
            full_sha="abc123",
        )
        with pytest.raises(ValidationError):
            ref.full_sha = "xyz789"

    def test_default_commit_shas_empty(self):
        ref = ResolvedReference(
            reference_type=DiffReferenceType.COMMIT,
            canonical_id="abc123",
            repo_slug="org/repo",
        )
        assert ref.commit_shas == []


class TestDedupPlanItem:
    """Tests for DedupPlanItem model."""

    def test_keep_decision(self):
        resolved = ResolvedReference(
            reference_type=DiffReferenceType.PR,
            canonical_id="PR #1245",
            repo_slug="org/repo",
            pr_number=1245,
        )
        item = DedupPlanItem(
            reference=resolved,
            decision=DedupDecision.KEEP,
        )
        assert item.decision == DedupDecision.KEEP
        assert item.covered_by_pr is None
        assert item.reason is None

    def test_suppress_decision_with_coverage(self):
        resolved = ResolvedReference(
            reference_type=DiffReferenceType.COMMIT,
            canonical_id="abc123def456",
            repo_slug="org/repo",
            full_sha="abc123def456",
        )
        item = DedupPlanItem(
            reference=resolved,
            decision=DedupDecision.SUPPRESS_COVERED_BY_PR,
            covered_by_pr=1245,
            reason="Commit is part of PR #1245",
        )
        assert item.decision == DedupDecision.SUPPRESS_COVERED_BY_PR
        assert item.covered_by_pr == 1245
        assert "PR #1245" in item.reason

    def test_frozen_model(self):
        resolved = ResolvedReference(
            reference_type=DiffReferenceType.PR,
            canonical_id="PR #1",
            repo_slug="org/repo",
            pr_number=1,
        )
        item = DedupPlanItem(reference=resolved, decision=DedupDecision.KEEP)
        with pytest.raises(ValidationError):
            item.decision = DedupDecision.SUPPRESS_COVERED_BY_PR


class TestDiffResult:
    """Tests for DiffResult model."""

    def test_resolved_pr_diff(self):
        result = DiffResult(
            reference_type=DiffReferenceType.PR,
            canonical_id="PR #1245",
            repo="org/repo",
            diff_text="diff --git a/file.py b/file.py\n+new line",
            status=DiffStatus.RESOLVED,
        )
        assert result.reference_type == DiffReferenceType.PR
        assert result.canonical_id == "PR #1245"
        assert result.repo == "org/repo"
        assert result.diff_text is not None
        assert result.status == DiffStatus.RESOLVED
        assert result.suppressed_reason is None
        assert result.error_message is None

    def test_resolved_commit_diff(self):
        result = DiffResult(
            reference_type=DiffReferenceType.COMMIT,
            canonical_id="abc123def456789012345678901234567890abcd",
            repo="org/repo",
            diff_text="diff --git a/file.py b/file.py\n-old line\n+new line",
            status=DiffStatus.RESOLVED,
        )
        assert result.reference_type == DiffReferenceType.COMMIT
        assert result.status == DiffStatus.RESOLVED

    def test_suppressed_commit(self):
        result = DiffResult(
            reference_type=DiffReferenceType.COMMIT,
            canonical_id="abc123def456",
            repo="org/repo",
            diff_text=None,
            status=DiffStatus.SUPPRESSED,
            suppressed_reason="covered_by_pr:1245",
        )
        assert result.status == DiffStatus.SUPPRESSED
        assert result.suppressed_reason == "covered_by_pr:1245"
        assert result.diff_text is None

    def test_unresolved_with_error(self):
        result = DiffResult(
            reference_type=DiffReferenceType.PR,
            canonical_id="PR #9999",
            repo="org/repo",
            diff_text=None,
            status=DiffStatus.UNRESOLVED,
            error_message="PR not found",
        )
        assert result.status == DiffStatus.UNRESOLVED
        assert result.error_message == "PR not found"
        assert result.diff_text is None

    def test_frozen_model(self):
        result = DiffResult(
            reference_type=DiffReferenceType.PR,
            canonical_id="PR #1",
            repo="org/repo",
            status=DiffStatus.RESOLVED,
            diff_text="diff",
        )
        with pytest.raises(ValidationError):
            result.status = DiffStatus.UNRESOLVED

    def test_required_fields(self):
        with pytest.raises(ValidationError):
            DiffResult(
                reference_type=DiffReferenceType.PR,
                canonical_id="PR #1",
            )

    def test_diff_text_can_be_empty_string(self):
        result = DiffResult(
            reference_type=DiffReferenceType.COMMIT,
            canonical_id="abc123",
            repo="org/repo",
            diff_text="",
            status=DiffStatus.RESOLVED,
        )
        assert result.diff_text == ""
