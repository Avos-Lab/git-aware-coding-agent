"""Diff resolver for PR and commit references.

Implements the PR-Wins deduplication strategy: commits that are part of
a referenced PR are suppressed to avoid duplicate content. Extracts
unified diffs from the GitHub REST API for both PRs and commits.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from avos_cli.exceptions import AvosError
from avos_cli.models.diff import (
    DedupDecision,
    DedupPlanItem,
    DiffReferenceType,
    DiffResult,
    DiffStatus,
    ParsedReference,
    ResolvedReference,
)
from avos_cli.utils.logger import get_logger

if TYPE_CHECKING:
    from avos_cli.services.github_client import GitHubClient

_log = get_logger("diff_resolver")


class DiffResolver:
    """Resolves PR and commit references to unified diffs via GitHub API.

    Implements the PR-Wins deduplication strategy:
    1. Build coverage index: map each commit SHA to PRs containing it
    2. For each commit reference, check if it's covered by any PR
    3. Suppress covered commits, keep independent commits
    4. Extract diffs for all kept references

    Args:
        github_client: GitHub REST API client for PR and commit endpoints.
    """

    def __init__(self, github_client: GitHubClient) -> None:
        self._github = github_client

    def resolve(self, references: list[ParsedReference]) -> list[DiffResult]:
        """Resolve references to diffs with PR-Wins deduplication.

        Args:
            references: List of parsed PR/commit references.

        Returns:
            List of DiffResult objects with extracted diffs or status info.
        """
        if not references:
            return []

        pr_refs = [r for r in references if r.reference_type == DiffReferenceType.PR]
        coverage_index = self._build_coverage_index(pr_refs)
        dedup_plan = self._apply_dedup(references, coverage_index)

        results: list[DiffResult] = []
        for plan_item in dedup_plan:
            result = self._extract_diff(plan_item)
            results.append(result)

        return results

    def _build_coverage_index(
        self, pr_refs: list[ParsedReference]
    ) -> dict[str, set[int]]:
        """Build index mapping commit SHAs to PR numbers that contain them.

        Args:
            pr_refs: List of PR references to index.

        Returns:
            Dict mapping full commit SHA to set of PR numbers.
        """
        index: dict[str, set[int]] = {}

        for pr_ref in pr_refs:
            if pr_ref.repo_slug is None:
                continue

            pr_number = int(pr_ref.raw_id)
            owner, repo = pr_ref.repo_slug.split("/", 1)

            try:
                commit_shas = self._github.list_pr_commits(owner, repo, pr_number)
                for sha in commit_shas:
                    if sha not in index:
                        index[sha] = set()
                    index[sha].add(pr_number)
            except AvosError as e:
                _log.warning("Failed to fetch commits for PR #%d: %s", pr_number, e)

        return index

    def _apply_dedup(
        self,
        references: list[ParsedReference],
        coverage_index: dict[str, set[int]],
    ) -> list[DedupPlanItem]:
        """Apply PR-Wins deduplication rule to all references.

        Args:
            references: All parsed references.
            coverage_index: Mapping of commit SHA to covering PR numbers.

        Returns:
            List of DedupPlanItem with keep/suppress decisions.
        """
        plan: list[DedupPlanItem] = []

        for ref in references:
            if ref.reference_type == DiffReferenceType.PR:
                resolved = self._resolve_pr_reference(ref)
                if resolved is None:
                    plan.append(self._make_unresolved_plan_item(ref, "PR resolution failed"))
                else:
                    plan.append(
                        DedupPlanItem(reference=resolved, decision=DedupDecision.KEEP)
                    )
            else:
                resolved, commit_detail = self._resolve_commit_reference(ref)
                if resolved is None:
                    plan.append(
                        self._make_unresolved_plan_item(
                            ref,
                            commit_detail or "Commit SHA expansion failed",
                        )
                    )
                    continue

                full_sha = resolved.full_sha
                if full_sha and full_sha in coverage_index:
                    covering_prs = coverage_index[full_sha]
                    first_pr = min(covering_prs)
                    plan.append(
                        DedupPlanItem(
                            reference=resolved,
                            decision=DedupDecision.SUPPRESS_COVERED_BY_PR,
                            covered_by_pr=first_pr,
                            reason=f"Covered by PR #{first_pr}",
                        )
                    )
                else:
                    plan.append(
                        DedupPlanItem(reference=resolved, decision=DedupDecision.KEEP)
                    )

        return plan

    def _resolve_pr_reference(self, ref: ParsedReference) -> ResolvedReference | None:
        """Resolve a PR reference to canonical form.

        Args:
            ref: Parsed PR reference.

        Returns:
            ResolvedReference or None if resolution fails.
        """
        if ref.repo_slug is None:
            return None

        pr_number = int(ref.raw_id)
        owner, repo = ref.repo_slug.split("/", 1)

        try:
            commit_shas = self._github.list_pr_commits(owner, repo, pr_number)
        except AvosError:
            commit_shas = []

        return ResolvedReference(
            reference_type=DiffReferenceType.PR,
            canonical_id=f"PR #{pr_number}",
            repo_slug=ref.repo_slug,
            pr_number=pr_number,
            commit_shas=commit_shas,
        )

    def _resolve_commit_reference(
        self, ref: ParsedReference
    ) -> tuple[ResolvedReference | None, str | None]:
        """Resolve a commit reference to canonical form with full SHA.

        Uses the GitHub commits API (same as the hosted repo).

        Args:
            ref: Parsed commit reference.

        Returns:
            (resolved, None) on success, or (None, detail) where detail is a
            short error string (e.g. GitHub API message) when resolution fails.
        """
        if ref.repo_slug is None:
            return None, None

        owner, repo = ref.repo_slug.split("/", 1)

        try:
            payload = self._github.get_commit(owner, repo, ref.raw_id)
        except AvosError as e:
            return None, str(e)
        full_sha = str(payload.get("sha", ""))
        if len(full_sha) != 40:
            return None, "Commit response missing full SHA"
        return (
            ResolvedReference(
                reference_type=DiffReferenceType.COMMIT,
                canonical_id=full_sha,
                repo_slug=ref.repo_slug,
                full_sha=full_sha,
            ),
            None,
        )

    def _make_unresolved_plan_item(
        self, ref: ParsedReference, reason: str
    ) -> DedupPlanItem:
        """Create a plan item for an unresolved reference.

        Args:
            ref: The unresolved reference.
            reason: Reason for failure.

        Returns:
            DedupPlanItem with KEEP decision (will produce UNRESOLVED result).
        """
        resolved = ResolvedReference(
            reference_type=ref.reference_type,
            canonical_id=ref.raw_id,
            repo_slug=ref.repo_slug or "unknown",
            pr_number=int(ref.raw_id) if ref.reference_type == DiffReferenceType.PR else None,
            full_sha=ref.raw_id if ref.reference_type == DiffReferenceType.COMMIT else None,
        )
        return DedupPlanItem(
            reference=resolved,
            decision=DedupDecision.KEEP,
            reason=reason,
        )

    def _extract_diff(self, plan_item: DedupPlanItem) -> DiffResult:
        """Extract diff for a single plan item.

        Args:
            plan_item: Dedup plan item with reference and decision.

        Returns:
            DiffResult with diff text or status info.
        """
        ref = plan_item.reference

        if plan_item.decision == DedupDecision.SUPPRESS_COVERED_BY_PR:
            return DiffResult(
                reference_type=ref.reference_type,
                canonical_id=ref.canonical_id,
                repo=ref.repo_slug,
                status=DiffStatus.SUPPRESSED,
                suppressed_reason=f"covered_by_pr:{plan_item.covered_by_pr}",
            )

        if ref.repo_slug is None or ref.repo_slug == "unknown":
            return DiffResult(
                reference_type=ref.reference_type,
                canonical_id=ref.canonical_id,
                repo=ref.repo_slug or "unknown",
                status=DiffStatus.UNRESOLVED,
                error_message="Repository context unknown",
            )

        if plan_item.decision == DedupDecision.KEEP and plan_item.reason:
            return DiffResult(
                reference_type=ref.reference_type,
                canonical_id=ref.canonical_id,
                repo=ref.repo_slug,
                status=DiffStatus.UNRESOLVED,
                error_message=plan_item.reason,
            )

        if ref.reference_type == DiffReferenceType.PR:
            return self._extract_pr_diff(ref)
        return self._extract_commit_diff(ref)

    def _extract_pr_diff(self, ref: ResolvedReference) -> DiffResult:
        """Extract diff for a PR reference.

        Args:
            ref: Resolved PR reference.

        Returns:
            DiffResult with PR diff or error.
        """
        if ref.pr_number is None or ref.repo_slug is None:
            return DiffResult(
                reference_type=ref.reference_type,
                canonical_id=ref.canonical_id,
                repo=ref.repo_slug or "unknown",
                status=DiffStatus.UNRESOLVED,
                error_message="Invalid PR reference",
            )

        owner, repo = ref.repo_slug.split("/", 1)

        try:
            diff_text = self._github.get_pr_diff(owner, repo, ref.pr_number)
            return DiffResult(
                reference_type=ref.reference_type,
                canonical_id=ref.canonical_id,
                repo=ref.repo_slug,
                diff_text=diff_text,
                status=DiffStatus.RESOLVED,
            )
        except AvosError as e:
            return DiffResult(
                reference_type=ref.reference_type,
                canonical_id=ref.canonical_id,
                repo=ref.repo_slug,
                status=DiffStatus.UNRESOLVED,
                error_message=str(e),
            )

    def _extract_commit_diff(self, ref: ResolvedReference) -> DiffResult:
        """Extract diff for a commit reference via GitHub commits API.

        Args:
            ref: Resolved commit reference.

        Returns:
            DiffResult with commit diff or error.
        """
        if ref.full_sha is None:
            return DiffResult(
                reference_type=ref.reference_type,
                canonical_id=ref.canonical_id,
                repo=ref.repo_slug,
                status=DiffStatus.UNRESOLVED,
                error_message="Commit SHA not resolved",
            )

        owner, repo = ref.repo_slug.split("/", 1)

        try:
            diff_text = self._github.get_commit_diff(owner, repo, ref.full_sha)
            if not diff_text:
                return DiffResult(
                    reference_type=ref.reference_type,
                    canonical_id=ref.canonical_id,
                    repo=ref.repo_slug,
                    status=DiffStatus.UNRESOLVED,
                    error_message="Commit has no diff (empty response)",
                )
            return DiffResult(
                reference_type=ref.reference_type,
                canonical_id=ref.canonical_id,
                repo=ref.repo_slug,
                diff_text=diff_text,
                status=DiffStatus.RESOLVED,
            )
        except AvosError as e:
            return DiffResult(
                reference_type=ref.reference_type,
                canonical_id=ref.canonical_id,
                repo=ref.repo_slug,
                status=DiffStatus.UNRESOLVED,
                error_message=str(e),
            )

    def format_output(self, results: list[DiffResult]) -> str:
        """Format diff results as grouped output text.

        Args:
            results: List of DiffResult objects.

        Returns:
            Formatted string with headers and diff content.
        """
        lines: list[str] = []

        for result in results:
            if result.reference_type == DiffReferenceType.PR:
                header = f"=== PR #{result.canonical_id.replace('PR #', '')} ==="
            else:
                header = f"=== COMMIT {result.canonical_id} ==="

            lines.append(header)

            if result.status == DiffStatus.RESOLVED:
                lines.append(result.diff_text or "")
            elif result.status == DiffStatus.SUPPRESSED:
                lines.append(f"[suppressed: {result.suppressed_reason}]")
            else:
                lines.append(f"[unresolved: {result.error_message}]")

            lines.append("")

        return "\n".join(lines)
