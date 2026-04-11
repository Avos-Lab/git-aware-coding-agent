"""Unit tests for artifact_ref_extractor module.

Tests extraction of PR numbers, commit hashes, and repo slugs from
memory search hit content using regex patterns.
"""

from __future__ import annotations

import pytest

from avos_cli.models.api import SearchHit
from avos_cli.parsers.artifact_ref_extractor import (
    ArtifactRef,
    NoteRefs,
    collect_all_refs,
    extract_refs,
    extract_refs_by_note,
    extract_refs_from_hits,
)


class TestArtifactRefModel:
    """Tests for the ArtifactRef Pydantic model."""

    def test_default_values(self) -> None:
        """ArtifactRef should have empty lists and None repo by default."""
        ref = ArtifactRef()
        assert ref.pr_numbers == []
        assert ref.commit_hashes == []
        assert ref.references == []
        assert ref.repo is None

    def test_with_values(self) -> None:
        """ArtifactRef should accept pr_numbers, commit_hashes, references, and repo."""
        ref = ArtifactRef(
            pr_numbers=[42, 123],
            commit_hashes=["abc1234", "def5678"],
            references=["pr #42", "pr #123", "commit abc1234", "commit def5678"],
            repo="org/repo",
        )
        assert ref.pr_numbers == [42, 123]
        assert ref.commit_hashes == ["abc1234", "def5678"]
        assert ref.references == ["pr #42", "pr #123", "commit abc1234", "commit def5678"]
        assert ref.repo == "org/repo"

    def test_frozen(self) -> None:
        """ArtifactRef should be immutable (frozen)."""
        from pydantic import ValidationError

        ref = ArtifactRef(pr_numbers=[1])
        with pytest.raises(ValidationError):
            ref.pr_numbers = [2]  # type: ignore[misc]

    def test_references_field_default(self) -> None:
        """ArtifactRef references field should default to empty list."""
        ref = ArtifactRef(pr_numbers=[1], commit_hashes=["abc"])
        assert ref.references == []


class TestNoteRefsModel:
    """Tests for the NoteRefs Pydantic model."""

    def test_with_values(self) -> None:
        """NoteRefs should accept note_id and references."""
        note_refs = NoteRefs(
            note_id="note_123",
            references=["pr #42", "commit abc1234"],
        )
        assert note_refs.note_id == "note_123"
        assert note_refs.references == ["pr #42", "commit abc1234"]

    def test_default_references(self) -> None:
        """NoteRefs references should default to empty list."""
        note_refs = NoteRefs(note_id="note_456")
        assert note_refs.note_id == "note_456"
        assert note_refs.references == []

    def test_frozen(self) -> None:
        """NoteRefs should be immutable (frozen)."""
        from pydantic import ValidationError

        note_refs = NoteRefs(note_id="note_1", references=["pr #1"])
        with pytest.raises(ValidationError):
            note_refs.references = ["pr #2"]  # type: ignore[misc]


class TestExtractRefs:
    """Tests for extract_refs function on single content strings."""

    def test_pr_content(self) -> None:
        """Should extract PR number from PR note content."""
        content = """[type: raw_pr_thread]
[repo: org/repo]
[pr: #42]
[author: devuser]
[merged: 2026-01-15]
Title: Add ingest lock
"""
        ref = extract_refs(content)
        assert ref.pr_numbers == [42]
        assert ref.commit_hashes == []
        assert ref.references == ["pr #42"]
        assert ref.repo == "org/repo"

    def test_commit_content(self) -> None:
        """Should extract commit hash from commit note content."""
        content = """[type: commit]
[repo: org/repo]
[hash: a1b2c3d4e5f6]
[author: devuser]
[date: 2026-01-10T08:00:00Z]
Message: Skip duplicate content hash
"""
        ref = extract_refs(content)
        assert ref.pr_numbers == []
        assert ref.commit_hashes == ["a1b2c3d4e5f6"]
        assert ref.references == ["commit a1b2c3d4e5f6"]
        assert ref.repo == "org/repo"

    def test_mixed_content(self) -> None:
        """Should extract both PR and commit from mixed content."""
        content = """[repo: org/repo]
[pr: #42]
[hash: abc123]
Some discussion about the PR and its commits.
"""
        ref = extract_refs(content)
        assert ref.pr_numbers == [42]
        assert ref.commit_hashes == ["abc123"]
        assert ref.references == ["pr #42", "commit abc123"]
        assert ref.repo == "org/repo"

    def test_multiple_prs(self) -> None:
        """Should extract multiple PR numbers from content."""
        content = """[repo: org/repo]
[pr: #42]
[pr: #123]
[pr: #456]
"""
        ref = extract_refs(content)
        assert ref.pr_numbers == [42, 123, 456]

    def test_multiple_commits(self) -> None:
        """Should extract multiple commit hashes from content."""
        content = """[repo: org/repo]
[hash: abc1234]
[hash: def5678]
[hash: 999aaabbb]
"""
        ref = extract_refs(content)
        assert ref.commit_hashes == ["abc1234", "def5678", "999aaabbb"]

    def test_missing_tags(self) -> None:
        """Should return empty ArtifactRef when no tags present."""
        content = "Just some plain text without any tags."
        ref = extract_refs(content)
        assert ref.pr_numbers == []
        assert ref.commit_hashes == []
        assert ref.repo is None

    def test_case_insensitive_pr(self) -> None:
        """Should match PR tag case-insensitively."""
        content = "[PR: #99]"
        ref = extract_refs(content)
        assert ref.pr_numbers == [99]

    def test_case_insensitive_hash(self) -> None:
        """Should match hash tag case-insensitively."""
        content = "[HASH: ABCDEF]"
        ref = extract_refs(content)
        assert ref.commit_hashes == ["ABCDEF"]

    def test_case_insensitive_repo(self) -> None:
        """Should match repo tag case-insensitively."""
        content = "[REPO: Org/Repo]"
        ref = extract_refs(content)
        assert ref.repo == "Org/Repo"

    def test_whitespace_variations(self) -> None:
        """Should handle whitespace variations in tags."""
        content = """[pr:  #42]
[hash:   abc123]
[repo:  org/repo]
"""
        ref = extract_refs(content)
        assert ref.pr_numbers == [42]
        assert ref.commit_hashes == ["abc123"]
        assert ref.repo == "org/repo"

    def test_empty_content(self) -> None:
        """Should handle empty content gracefully."""
        ref = extract_refs("")
        assert ref.pr_numbers == []
        assert ref.commit_hashes == []
        assert ref.repo is None

    def test_partial_tags(self) -> None:
        """Should not match malformed tags."""
        content = "[pr: ] [hash:] [repo:]"
        ref = extract_refs(content)
        assert ref.pr_numbers == []
        assert ref.commit_hashes == []
        assert ref.repo is None

    def test_repo_without_slash(self) -> None:
        """Should not match repo without owner/name format."""
        content = "[repo: justarepo]"
        ref = extract_refs(content)
        assert ref.repo is None

    def test_short_hash(self) -> None:
        """Should extract short commit hashes (7+ chars)."""
        content = "[hash: abc1234]"
        ref = extract_refs(content)
        assert ref.commit_hashes == ["abc1234"]

    def test_full_sha_hash(self) -> None:
        """Should extract full 40-char SHA hashes."""
        full_sha = "a" * 40
        content = f"[hash: {full_sha}]"
        ref = extract_refs(content)
        assert ref.commit_hashes == [full_sha]

    def test_deduplicates_prs(self) -> None:
        """Should deduplicate repeated PR numbers."""
        content = "[pr: #42] [pr: #42] [pr: #42]"
        ref = extract_refs(content)
        assert ref.pr_numbers == [42]

    def test_deduplicates_hashes(self) -> None:
        """Should deduplicate repeated commit hashes."""
        content = "[hash: abc123] [hash: abc123]"
        ref = extract_refs(content)
        assert ref.commit_hashes == ["abc123"]


class TestExtractRefsFromHits:
    """Tests for extract_refs_from_hits function."""

    def _make_hit(self, content: str, note_id: str = "note_1") -> SearchHit:
        """Helper to create a SearchHit with given content."""
        return SearchHit(
            note_id=note_id,
            content=content,
            created_at="2026-01-15T10:00:00Z",
            rank=1,
        )

    def test_single_hit(self) -> None:
        """Should extract refs from a single hit."""
        hit = self._make_hit("[repo: org/repo]\n[pr: #42]")
        results = extract_refs_from_hits([hit])
        assert len(results) == 1
        assert results[0][0] is hit
        assert results[0][1].pr_numbers == [42]
        assert results[0][1].repo == "org/repo"

    def test_multiple_hits(self) -> None:
        """Should extract refs from multiple hits."""
        hit1 = self._make_hit("[pr: #1]", note_id="note_1")
        hit2 = self._make_hit("[hash: abc123]", note_id="note_2")
        hit3 = self._make_hit("[pr: #2]\n[hash: def456]", note_id="note_3")

        results = extract_refs_from_hits([hit1, hit2, hit3])
        assert len(results) == 3

        assert results[0][1].pr_numbers == [1]
        assert results[0][1].commit_hashes == []

        assert results[1][1].pr_numbers == []
        assert results[1][1].commit_hashes == ["abc123"]

        assert results[2][1].pr_numbers == [2]
        assert results[2][1].commit_hashes == ["def456"]

    def test_empty_hits_list(self) -> None:
        """Should return empty list for empty input."""
        results = extract_refs_from_hits([])
        assert results == []

    def test_preserves_hit_order(self) -> None:
        """Should preserve the order of hits in output."""
        hits = [
            self._make_hit("[pr: #3]", note_id="a"),
            self._make_hit("[pr: #1]", note_id="b"),
            self._make_hit("[pr: #2]", note_id="c"),
        ]
        results = extract_refs_from_hits(hits)
        assert results[0][0].note_id == "a"
        assert results[1][0].note_id == "b"
        assert results[2][0].note_id == "c"


class TestCollectAllRefs:
    """Tests for collect_all_refs function."""

    def _make_hit(self, content: str, note_id: str = "note_1") -> SearchHit:
        """Helper to create a SearchHit with given content."""
        return SearchHit(
            note_id=note_id,
            content=content,
            created_at="2026-01-15T10:00:00Z",
            rank=1,
        )

    def test_aggregates_prs(self) -> None:
        """Should aggregate unique PR numbers from all hits."""
        hits = [
            self._make_hit("[pr: #1]"),
            self._make_hit("[pr: #2]"),
            self._make_hit("[pr: #3]"),
        ]
        ref = collect_all_refs(hits)
        assert sorted(ref.pr_numbers) == [1, 2, 3]

    def test_aggregates_hashes(self) -> None:
        """Should aggregate unique commit hashes from all hits."""
        hits = [
            self._make_hit("[hash: abc1234]"),
            self._make_hit("[hash: def5678]"),
            self._make_hit("[hash: 9990aaa]"),
        ]
        ref = collect_all_refs(hits)
        assert sorted(ref.commit_hashes) == ["9990aaa", "abc1234", "def5678"]

    def test_deduplicates_across_hits(self) -> None:
        """Should deduplicate PRs and hashes across multiple hits."""
        hits = [
            self._make_hit("[pr: #42]\n[hash: abc123]"),
            self._make_hit("[pr: #42]\n[hash: def456]"),
            self._make_hit("[pr: #99]\n[hash: abc123]"),
        ]
        ref = collect_all_refs(hits)
        assert sorted(ref.pr_numbers) == [42, 99]
        assert sorted(ref.commit_hashes) == ["abc123", "def456"]

    def test_uses_first_repo(self) -> None:
        """Should use the first non-None repo found."""
        hits = [
            self._make_hit("[pr: #1]"),  # no repo
            self._make_hit("[repo: first/repo]\n[pr: #2]"),
            self._make_hit("[repo: second/repo]\n[pr: #3]"),
        ]
        ref = collect_all_refs(hits)
        assert ref.repo == "first/repo"

    def test_empty_hits(self) -> None:
        """Should return empty ArtifactRef for empty hits list."""
        ref = collect_all_refs([])
        assert ref.pr_numbers == []
        assert ref.commit_hashes == []
        assert ref.repo is None

    def test_no_refs_in_any_hit(self) -> None:
        """Should return empty ArtifactRef when no hits have refs."""
        hits = [
            self._make_hit("plain text"),
            self._make_hit("more plain text"),
        ]
        ref = collect_all_refs(hits)
        assert ref.pr_numbers == []
        assert ref.commit_hashes == []
        assert ref.repo is None

    def test_mixed_content_types(self) -> None:
        """Should handle mix of PR notes, commit notes, and empty notes."""
        hits = [
            self._make_hit("""[type: raw_pr_thread]
[repo: org/repo]
[pr: #42]
Title: Feature A"""),
            self._make_hit("""[type: commit]
[repo: org/repo]
[hash: abc1234]
Message: Fix bug"""),
            self._make_hit("Some discussion without tags"),
        ]
        ref = collect_all_refs(hits)
        assert ref.pr_numbers == [42]
        assert ref.commit_hashes == ["abc1234"]
        assert ref.repo == "org/repo"

    def test_references_aggregated(self) -> None:
        """Should aggregate references as unified strings."""
        hits = [
            self._make_hit("[pr: #1]\n[hash: abc123]"),
            self._make_hit("[pr: #2]"),
        ]
        ref = collect_all_refs(hits)
        assert ref.references == ["pr #1", "pr #2", "commit abc123"]


class TestExtractRefsByNote:
    """Tests for extract_refs_by_note function."""

    def _make_hit(self, content: str, note_id: str = "note_1") -> SearchHit:
        """Helper to create a SearchHit with given content."""
        return SearchHit(
            note_id=note_id,
            content=content,
            created_at="2026-01-15T10:00:00Z",
            rank=1,
        )

    def test_single_hit_with_pr(self) -> None:
        """Should extract refs from a single hit with PR."""
        hit = self._make_hit("[pr: #42]", note_id="note_11")
        results = extract_refs_by_note([hit])
        assert len(results) == 1
        assert results[0].note_id == "note_11"
        assert results[0].references == ["pr #42"]

    def test_single_hit_with_commit(self) -> None:
        """Should extract refs from a single hit with commit."""
        hit = self._make_hit("[hash: abc1234]", note_id="note_12")
        results = extract_refs_by_note([hit])
        assert len(results) == 1
        assert results[0].note_id == "note_12"
        assert results[0].references == ["commit abc1234"]

    def test_single_hit_with_mixed_refs(self) -> None:
        """Should extract both PR and commit refs from a single hit."""
        hit = self._make_hit("[pr: #123]\n[hash: def456]", note_id="note_11")
        results = extract_refs_by_note([hit])
        assert len(results) == 1
        assert results[0].note_id == "note_11"
        assert results[0].references == ["pr #123", "commit def456"]

    def test_multiple_hits(self) -> None:
        """Should extract refs from multiple hits, one NoteRefs per hit."""
        hits = [
            self._make_hit("[pr: #123]\n[hash: def456]", note_id="note_11"),
            self._make_hit("[pr: #45]", note_id="note_12"),
            self._make_hit("[hash: abc789]", note_id="note_13"),
        ]
        results = extract_refs_by_note(hits)
        assert len(results) == 3

        assert results[0].note_id == "note_11"
        assert results[0].references == ["pr #123", "commit def456"]

        assert results[1].note_id == "note_12"
        assert results[1].references == ["pr #45"]

        assert results[2].note_id == "note_13"
        assert results[2].references == ["commit abc789"]

    def test_empty_hits_list(self) -> None:
        """Should return empty list for empty input."""
        results = extract_refs_by_note([])
        assert results == []

    def test_hit_with_no_refs(self) -> None:
        """Should return NoteRefs with empty references for hit without tags."""
        hit = self._make_hit("Plain text without any tags", note_id="note_99")
        results = extract_refs_by_note([hit])
        assert len(results) == 1
        assert results[0].note_id == "note_99"
        assert results[0].references == []

    def test_preserves_hit_order(self) -> None:
        """Should preserve the order of hits in output."""
        hits = [
            self._make_hit("[pr: #3]", note_id="c"),
            self._make_hit("[pr: #1]", note_id="a"),
            self._make_hit("[pr: #2]", note_id="b"),
        ]
        results = extract_refs_by_note(hits)
        assert results[0].note_id == "c"
        assert results[1].note_id == "a"
        assert results[2].note_id == "b"

    def test_multiple_prs_and_commits_in_one_note(self) -> None:
        """Should extract multiple PRs and commits from one note."""
        hit = self._make_hit("[pr: #1]\n[pr: #2]\n[hash: aaa]\n[hash: bbb]", note_id="note_multi")
        results = extract_refs_by_note([hit])
        assert len(results) == 1
        assert results[0].note_id == "note_multi"
        assert results[0].references == ["pr #1", "pr #2", "commit aaa", "commit bbb"]
