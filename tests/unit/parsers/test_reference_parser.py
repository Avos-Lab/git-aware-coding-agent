"""Tests for ReferenceParser.

Covers regex-based parsing of PR and commit references with various formats,
edge cases, ambiguous inputs, and repo context handling.
"""

from __future__ import annotations

import pytest

from avos_cli.models.diff import DiffReferenceType
from avos_cli.parsers.reference_parser import ReferenceParser


@pytest.fixture()
def parser() -> ReferenceParser:
    return ReferenceParser()


class TestPRParsing:
    """Tests for PR reference parsing."""

    def test_pr_hash_format(self, parser: ReferenceParser):
        """PR #1245 format."""
        ref = parser.parse("PR #1245", default_repo="org/repo")
        assert ref is not None
        assert ref.reference_type == DiffReferenceType.PR
        assert ref.raw_id == "1245"
        assert ref.repo_slug == "org/repo"

    def test_pr_lowercase(self, parser: ReferenceParser):
        """pr #1245 lowercase format."""
        ref = parser.parse("pr #1245", default_repo="org/repo")
        assert ref is not None
        assert ref.reference_type == DiffReferenceType.PR
        assert ref.raw_id == "1245"

    def test_pr_no_space(self, parser: ReferenceParser):
        """PR#1245 without space."""
        ref = parser.parse("PR#1245", default_repo="org/repo")
        assert ref is not None
        assert ref.reference_type == DiffReferenceType.PR
        assert ref.raw_id == "1245"

    def test_bare_hash_number(self, parser: ReferenceParser):
        """#1245 bare format (assumes PR in context)."""
        ref = parser.parse("#1245", default_repo="org/repo")
        assert ref is not None
        assert ref.reference_type == DiffReferenceType.PR
        assert ref.raw_id == "1245"

    def test_pr_with_repo_prefix(self, parser: ReferenceParser):
        """org/repo#1245 format with explicit repo."""
        ref = parser.parse("org/repo#1245", default_repo=None)
        assert ref is not None
        assert ref.reference_type == DiffReferenceType.PR
        assert ref.raw_id == "1245"
        assert ref.repo_slug == "org/repo"

    def test_pr_with_repo_prefix_overrides_default(self, parser: ReferenceParser):
        """Explicit repo in reference overrides default."""
        ref = parser.parse("other/project#999", default_repo="org/repo")
        assert ref is not None
        assert ref.repo_slug == "other/project"
        assert ref.raw_id == "999"

    def test_pr_with_trailing_text(self, parser: ReferenceParser):
        """PR #1245 Storage Layer Refactor - extracts just the number."""
        ref = parser.parse("PR #1245 Storage Layer Refactor", default_repo="org/repo")
        assert ref is not None
        assert ref.reference_type == DiffReferenceType.PR
        assert ref.raw_id == "1245"

    def test_pr_in_sentence(self, parser: ReferenceParser):
        """See PR #1245 for details."""
        ref = parser.parse("See PR #1245 for details", default_repo="org/repo")
        assert ref is not None
        assert ref.raw_id == "1245"

    def test_pr_with_author_and_date(self, parser: ReferenceParser):
        """PR #1245 Storage Layer Refactor @smahmudrahat Mar 2026."""
        ref = parser.parse(
            "PR #1245 Storage Layer Refactor @smahmudrahat Mar 2026",
            default_repo="org/repo",
        )
        assert ref is not None
        assert ref.raw_id == "1245"


class TestCommitParsing:
    """Tests for commit reference parsing."""

    def test_commit_prefix_short_sha(self, parser: ReferenceParser):
        """Commit 8c3a1b2 format."""
        ref = parser.parse("Commit 8c3a1b2", default_repo="org/repo")
        assert ref is not None
        assert ref.reference_type == DiffReferenceType.COMMIT
        assert ref.raw_id == "8c3a1b2"
        assert ref.repo_slug == "org/repo"

    def test_commit_lowercase(self, parser: ReferenceParser):
        """commit 8c3a1b2 lowercase."""
        ref = parser.parse("commit 8c3a1b2", default_repo="org/repo")
        assert ref is not None
        assert ref.reference_type == DiffReferenceType.COMMIT
        assert ref.raw_id == "8c3a1b2"

    def test_commit_full_sha(self, parser: ReferenceParser):
        """Commit with full 40-char SHA."""
        full_sha = "8c3a1b2def456789012345678901234567890abc"
        ref = parser.parse(f"Commit {full_sha}", default_repo="org/repo")
        assert ref is not None
        assert ref.reference_type == DiffReferenceType.COMMIT
        assert ref.raw_id == full_sha

    def test_bare_sha_7_chars(self, parser: ReferenceParser):
        """Bare 7-char SHA without prefix."""
        ref = parser.parse("8c3a1b2", default_repo="org/repo")
        assert ref is not None
        assert ref.reference_type == DiffReferenceType.COMMIT
        assert ref.raw_id == "8c3a1b2"

    def test_bare_sha_8_chars(self, parser: ReferenceParser):
        """Bare 8-char SHA without prefix."""
        ref = parser.parse("8c3a1b2f", default_repo="org/repo")
        assert ref is not None
        assert ref.reference_type == DiffReferenceType.COMMIT
        assert ref.raw_id == "8c3a1b2f"

    def test_bare_sha_40_chars(self, parser: ReferenceParser):
        """Bare full 40-char SHA."""
        full_sha = "8c3a1b2def456789012345678901234567890abc"
        ref = parser.parse(full_sha, default_repo="org/repo")
        assert ref is not None
        assert ref.reference_type == DiffReferenceType.COMMIT
        assert ref.raw_id == full_sha

    def test_commit_with_message(self, parser: ReferenceParser):
        """Commit 8c3a1b2 Add ETag support - extracts just the SHA."""
        ref = parser.parse("Commit 8c3a1b2 Add ETag support", default_repo="org/repo")
        assert ref is not None
        assert ref.reference_type == DiffReferenceType.COMMIT
        assert ref.raw_id == "8c3a1b2"

    def test_commit_colon_format(self, parser: ReferenceParser):
        """Commit: 8c3a1b2 format with colon."""
        ref = parser.parse("Commit: 8c3a1b2", default_repo="org/repo")
        assert ref is not None
        assert ref.reference_type == DiffReferenceType.COMMIT
        assert ref.raw_id == "8c3a1b2"


class TestEdgeCases:
    """Tests for edge cases and invalid inputs."""

    def test_empty_string_returns_none(self, parser: ReferenceParser):
        ref = parser.parse("", default_repo="org/repo")
        assert ref is None

    def test_whitespace_only_returns_none(self, parser: ReferenceParser):
        ref = parser.parse("   ", default_repo="org/repo")
        assert ref is None

    def test_no_match_returns_none(self, parser: ReferenceParser):
        ref = parser.parse("This is just text", default_repo="org/repo")
        assert ref is None

    def test_pr_without_repo_and_no_default(self, parser: ReferenceParser):
        """PR reference without repo context returns None repo_slug."""
        ref = parser.parse("PR #1245", default_repo=None)
        assert ref is not None
        assert ref.repo_slug is None

    def test_commit_without_repo_and_no_default(self, parser: ReferenceParser):
        """Commit reference without repo context returns None repo_slug."""
        ref = parser.parse("Commit 8c3a1b2", default_repo=None)
        assert ref is not None
        assert ref.repo_slug is None

    def test_sha_too_short_returns_none(self, parser: ReferenceParser):
        """SHA with less than 7 chars is not valid."""
        ref = parser.parse("abc123", default_repo="org/repo")
        assert ref is None

    def test_sha_with_invalid_chars_returns_none(self, parser: ReferenceParser):
        """SHA with non-hex characters is not valid."""
        ref = parser.parse("8c3a1b2xyz", default_repo="org/repo")
        assert ref is None

    def test_number_alone_not_parsed_as_pr(self, parser: ReferenceParser):
        """Plain number without # is not a PR."""
        ref = parser.parse("1245", default_repo="org/repo")
        assert ref is None

    def test_pr_number_zero_invalid(self, parser: ReferenceParser):
        """PR #0 is invalid."""
        ref = parser.parse("PR #0", default_repo="org/repo")
        assert ref is None

    def test_negative_pr_number_invalid(self, parser: ReferenceParser):
        """PR #-1 is invalid."""
        ref = parser.parse("PR #-1", default_repo="org/repo")
        assert ref is None


class TestMultipleReferences:
    """Tests for parse_all method with multiple references."""

    def test_parse_all_single_pr(self, parser: ReferenceParser):
        refs = parser.parse_all(["PR #1245"], default_repo="org/repo")
        assert len(refs) == 1
        assert refs[0].raw_id == "1245"

    def test_parse_all_mixed_types(self, parser: ReferenceParser):
        refs = parser.parse_all(
            ["PR #1245", "Commit 8c3a1b2"],
            default_repo="org/repo",
        )
        assert len(refs) == 2
        assert refs[0].reference_type == DiffReferenceType.PR
        assert refs[1].reference_type == DiffReferenceType.COMMIT

    def test_parse_all_skips_invalid(self, parser: ReferenceParser):
        refs = parser.parse_all(
            ["PR #1245", "invalid text", "Commit 8c3a1b2"],
            default_repo="org/repo",
        )
        assert len(refs) == 2

    def test_parse_all_empty_list(self, parser: ReferenceParser):
        refs = parser.parse_all([], default_repo="org/repo")
        assert refs == []

    def test_parse_all_all_invalid(self, parser: ReferenceParser):
        refs = parser.parse_all(
            ["invalid", "also invalid"],
            default_repo="org/repo",
        )
        assert refs == []


class TestRepoSlugParsing:
    """Tests for repository slug extraction."""

    def test_github_url_style_repo(self, parser: ReferenceParser):
        """github.com/org/repo#123 style."""
        ref = parser.parse("github.com/org/repo#123", default_repo=None)
        assert ref is not None
        assert ref.repo_slug == "org/repo"
        assert ref.raw_id == "123"

    def test_https_github_url(self, parser: ReferenceParser):
        """https://github.com/org/repo/pull/123 style."""
        ref = parser.parse(
            "https://github.com/org/repo/pull/123",
            default_repo=None,
        )
        assert ref is not None
        assert ref.reference_type == DiffReferenceType.PR
        assert ref.repo_slug == "org/repo"
        assert ref.raw_id == "123"

    def test_github_commit_url(self, parser: ReferenceParser):
        """https://github.com/org/repo/commit/abc1234 style."""
        ref = parser.parse(
            "https://github.com/org/repo/commit/abc1234def",
            default_repo=None,
        )
        assert ref is not None
        assert ref.reference_type == DiffReferenceType.COMMIT
        assert ref.repo_slug == "org/repo"
        assert ref.raw_id == "abc1234def"
