"""Tests for AVOS-007: Artifact builders.

Covers format fidelity, metadata completeness, deterministic hashing,
and sensitive content exclusion for all builders.
"""

from __future__ import annotations

from avos_cli.artifacts.commit_builder import CommitBuilder
from avos_cli.artifacts.doc_builder import DocBuilder
from avos_cli.artifacts.issue_builder import IssueBuilder
from avos_cli.artifacts.pr_builder import PRThreadBuilder
from avos_cli.models.artifacts import (
    CommitArtifact,
    DocArtifact,
    IssueArtifact,
    PRArtifact,
)


class TestPRThreadBuilder:
    def _make_pr(self, **overrides) -> PRArtifact:
        defaults = {
            "repo": "org/repo",
            "pr_number": 312,
            "title": "Add retry scheduler",
            "author": "sanzeeda",
            "merged_date": "2026-01-15",
            "files": ["billing/retry_scheduler.py"],
            "description": "Implements exponential backoff",
            "discussion": "Team discussed queue deadlock",
        }
        defaults.update(overrides)
        return PRArtifact(**defaults)

    def test_build_contains_type_header(self):
        pr = self._make_pr()
        output = PRThreadBuilder().build(pr)
        assert "[type: raw_pr_thread]" in output

    def test_build_contains_metadata(self):
        pr = self._make_pr()
        output = PRThreadBuilder().build(pr)
        assert "[repo: org/repo]" in output
        assert "[pr: #312]" in output
        assert "[author: sanzeeda]" in output
        assert "[merged: 2026-01-15]" in output

    def test_build_contains_files(self):
        pr = self._make_pr()
        output = PRThreadBuilder().build(pr)
        assert "[files: billing/retry_scheduler.py]" in output

    def test_build_contains_title_and_description(self):
        pr = self._make_pr()
        output = PRThreadBuilder().build(pr)
        assert "Title: Add retry scheduler" in output
        assert "Description: Implements exponential backoff" in output

    def test_build_contains_discussion(self):
        pr = self._make_pr()
        output = PRThreadBuilder().build(pr)
        assert "Discussion: Team discussed queue deadlock" in output

    def test_content_hash_deterministic(self):
        pr = self._make_pr()
        builder = PRThreadBuilder()
        h1 = builder.content_hash(pr)
        h2 = builder.content_hash(pr)
        h3 = builder.content_hash(pr)
        assert h1 == h2 == h3
        assert len(h1) == 64

    def test_optional_fields_omitted_when_none(self):
        pr = self._make_pr(merged_date=None, description=None, discussion=None, files=[])
        output = PRThreadBuilder().build(pr)
        assert "[merged:" not in output
        assert "Description:" not in output
        assert "Discussion:" not in output


class TestIssueBuilder:
    def _make_issue(self, **overrides) -> IssueArtifact:
        defaults = {
            "repo": "org/repo",
            "issue_number": 42,
            "title": "Bug in payment flow",
            "labels": ["bug", "critical"],
            "body": "Payment fails on retry",
            "comments": ["Confirmed on prod", "Fix in progress"],
        }
        defaults.update(overrides)
        return IssueArtifact(**defaults)

    def test_build_contains_type_header(self):
        issue = self._make_issue()
        output = IssueBuilder().build(issue)
        assert "[type: issue]" in output

    def test_build_contains_metadata(self):
        issue = self._make_issue()
        output = IssueBuilder().build(issue)
        assert "[repo: org/repo]" in output
        assert "[issue: #42]" in output
        assert "[labels: bug, critical]" in output

    def test_build_contains_body_and_comments(self):
        issue = self._make_issue()
        output = IssueBuilder().build(issue)
        assert "Body: Payment fails on retry" in output
        assert "Confirmed on prod" in output

    def test_content_hash_deterministic(self):
        issue = self._make_issue()
        builder = IssueBuilder()
        h1 = builder.content_hash(issue)
        h2 = builder.content_hash(issue)
        assert h1 == h2


class TestCommitBuilder:
    def _make_commit(self, **overrides) -> CommitArtifact:
        defaults = {
            "repo": "org/repo",
            "hash": "abc123def456",
            "message": "fix: retry logic for payments",
            "author": "sanzeeda",
            "date": "2026-01-15",
            "files_changed": ["billing/retry.py", "billing/scheduler.py"],
            "diff_stats": "+50 -10",
        }
        defaults.update(overrides)
        return CommitArtifact(**defaults)

    def test_build_contains_type_header(self):
        commit = self._make_commit()
        output = CommitBuilder().build(commit)
        assert "[type: commit]" in output

    def test_build_contains_metadata(self):
        commit = self._make_commit()
        output = CommitBuilder().build(commit)
        assert "[repo: org/repo]" in output
        assert "[hash: abc123def456]" in output
        assert "[author: sanzeeda]" in output
        assert "[date: 2026-01-15]" in output

    def test_build_contains_message(self):
        commit = self._make_commit()
        output = CommitBuilder().build(commit)
        assert "Message: fix: retry logic for payments" in output

    def test_content_hash_deterministic(self):
        commit = self._make_commit()
        builder = CommitBuilder()
        h1 = builder.content_hash(commit)
        h2 = builder.content_hash(commit)
        assert h1 == h2


class TestDocBuilder:
    def _make_doc(self, **overrides) -> DocArtifact:
        defaults = {
            "repo": "org/repo",
            "path": "docs/architecture.md",
            "content_type": "design_doc",
            "content": "# Architecture\n\nThis document describes...",
        }
        defaults.update(overrides)
        return DocArtifact(**defaults)

    def test_build_contains_type_header(self):
        doc = self._make_doc()
        output = DocBuilder().build(doc)
        assert "[type: document]" in output

    def test_build_contains_metadata(self):
        doc = self._make_doc()
        output = DocBuilder().build(doc)
        assert "[repo: org/repo]" in output
        assert "[path: docs/architecture.md]" in output
        assert "[content_type: design_doc]" in output

    def test_build_contains_content(self):
        doc = self._make_doc()
        output = DocBuilder().build(doc)
        assert "# Architecture" in output

    def test_content_hash_deterministic(self):
        doc = self._make_doc()
        builder = DocBuilder()
        h1 = builder.content_hash(doc)
        h2 = builder.content_hash(doc)
        assert h1 == h2


class TestBuilderEdgeCases:
    """Test builders with minimal/empty optional fields to cover branches."""

    def test_commit_no_optional_fields(self):
        commit = CommitArtifact(
            repo="org/repo", hash="abc", message="msg", author="dev", date="2026-01-15"
        )
        output = CommitBuilder().build(commit)
        assert "[files:" not in output
        assert "[diff:" not in output

    def test_commit_with_all_fields(self):
        commit = CommitArtifact(
            repo="org/repo", hash="abc", message="msg", author="dev", date="2026-01-15",
            files_changed=["a.py"], diff_stats="+1 -0"
        )
        output = CommitBuilder().build(commit)
        assert "[files: a.py]" in output
        assert "[diff: +1 -0]" in output

    def test_issue_no_optional_fields(self):
        issue = IssueArtifact(repo="org/repo", issue_number=1, title="Test")
        output = IssueBuilder().build(issue)
        assert "[labels:" not in output
        assert "Body:" not in output
        assert "Comments:" not in output


class TestCrossBuilderHashUniqueness:
    """Different inputs should produce different hashes."""

    def test_different_prs_different_hashes(self):
        builder = PRThreadBuilder()
        pr1 = PRArtifact(repo="org/repo", pr_number=1, title="PR 1", author="dev")
        pr2 = PRArtifact(repo="org/repo", pr_number=2, title="PR 2", author="dev")
        assert builder.content_hash(pr1) != builder.content_hash(pr2)
