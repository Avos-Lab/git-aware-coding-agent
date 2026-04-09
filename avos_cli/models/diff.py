"""Diff pipeline models for PR and commit reference resolution.

Defines Pydantic models for the git diff extraction pipeline:
parsed references, resolved references, deduplication plan items,
and final diff results.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict


class DiffReferenceType(str, Enum):
    """Type of diff reference: PR or commit."""

    PR = "pr"
    COMMIT = "commit"


class DedupDecision(str, Enum):
    """Deduplication decision for a reference."""

    KEEP = "keep"
    SUPPRESS_COVERED_BY_PR = "suppress_covered_by_pr"


class DiffStatus(str, Enum):
    """Resolution status of a diff extraction."""

    RESOLVED = "resolved"
    UNRESOLVED = "unresolved"
    SUPPRESSED = "suppressed"


class ParsedReference(BaseModel):
    """A parsed PR or commit reference from raw input.

    Args:
        reference_type: Whether this is a PR or commit reference.
        raw_id: The raw identifier (PR number or short/full SHA).
        repo_slug: Repository slug 'org/repo', or None if ambiguous.
    """

    model_config = ConfigDict(frozen=True)

    reference_type: DiffReferenceType
    raw_id: str
    repo_slug: str | None


class ResolvedReference(BaseModel):
    """A fully resolved reference with canonical identifiers.

    For PRs: includes the list of commit SHAs contained in the PR.
    For commits: includes the expanded full SHA.

    Args:
        reference_type: Whether this is a PR or commit reference.
        canonical_id: Canonical display ID (e.g., 'PR #1245' or full SHA).
        repo_slug: Repository slug 'org/repo'.
        pr_number: PR number (for PR references).
        full_sha: Full 40-char commit SHA (for commit references).
        commit_shas: List of commit SHAs contained in this PR (for PR refs).
    """

    model_config = ConfigDict(frozen=True)

    reference_type: DiffReferenceType
    canonical_id: str
    repo_slug: str
    pr_number: int | None = None
    full_sha: str | None = None
    commit_shas: list[str] = []


class DedupPlanItem(BaseModel):
    """A deduplication plan item with decision and reasoning.

    Args:
        reference: The resolved reference being evaluated.
        decision: Keep or suppress this reference.
        covered_by_pr: PR number that covers this commit (if suppressed).
        reason: Human-readable reason for the decision.
    """

    model_config = ConfigDict(frozen=True)

    reference: ResolvedReference
    decision: DedupDecision
    covered_by_pr: int | None = None
    reason: str | None = None


class DiffResult(BaseModel):
    """Final result of diff extraction for a single reference.

    Args:
        reference_type: Whether this is a PR or commit reference.
        canonical_id: Canonical display ID (e.g., 'PR #1245' or full SHA).
        repo: Repository slug 'org/repo'.
        diff_text: The unified diff text, or None if unresolved/suppressed.
        status: Resolution status (resolved, unresolved, suppressed).
        suppressed_reason: Reason for suppression (e.g., 'covered_by_pr:1245').
        error_message: Error message if unresolved.
    """

    model_config = ConfigDict(frozen=True)

    reference_type: DiffReferenceType
    canonical_id: str
    repo: str
    diff_text: str | None = None
    status: DiffStatus
    suppressed_reason: str | None = None
    error_message: str | None = None
