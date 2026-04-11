"""Extract PR numbers and commit hashes from memory search hit content.

This module provides utilities to parse structured tags from artifact content
returned by the Avos Memory API. The tags follow the format established by
the ingest builders (pr_builder.py, commit_builder.py):

    [pr: #42]
    [hash: abc1234...]
    [repo: org/repo]

Functions:
    extract_refs: Extract refs from a single content string.
    extract_refs_from_hits: Map extraction over a list of SearchHit objects.
    collect_all_refs: Aggregate unique refs across all hits.
    extract_refs_by_note: Extract refs grouped by note_id as unified string arrays.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from avos_cli.models.api import SearchHit

# Compiled regex patterns for tag extraction (shared across the codebase)
_PR_RE = re.compile(r"\[pr:\s*#(\d+)\]", re.IGNORECASE)
_HASH_RE = re.compile(r"\[hash:\s*([a-f0-9]+)\]", re.IGNORECASE)
_REPO_RE = re.compile(r"\[repo:\s*([a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+)\]", re.IGNORECASE)


def _build_references(pr_numbers: list[int], commit_hashes: list[str]) -> list[str]:
    """Build unified reference strings from PR numbers and commit hashes.

    Args:
        pr_numbers: List of PR numbers.
        commit_hashes: List of commit hashes.

    Returns:
        List of formatted reference strings like ["pr #42", "commit abc1234"].
    """
    refs: list[str] = []
    for pr in pr_numbers:
        refs.append(f"pr #{pr}")
    for h in commit_hashes:
        refs.append(f"commit {h}")
    return refs


class ArtifactRef(BaseModel):
    """Structured references extracted from a memory artifact.

    Attributes:
        pr_numbers: List of unique PR numbers found in the content.
        commit_hashes: List of unique commit hashes found in the content.
        references: Unified list of reference strings (e.g., ["pr #42", "commit abc1234"]).
        repo: Repository slug (owner/name) if found, else None.
    """

    model_config = ConfigDict(frozen=True)

    pr_numbers: list[int] = Field(default_factory=list)
    commit_hashes: list[str] = Field(default_factory=list)
    references: list[str] = Field(default_factory=list)
    repo: str | None = None


class NoteRefs(BaseModel):
    """Per-note reference storage.

    Attributes:
        note_id: The note identifier from the memory artifact.
        references: Unified list of reference strings (e.g., ["pr #42", "commit abc1234"]).
    """

    model_config = ConfigDict(frozen=True)

    note_id: str
    references: list[str] = Field(default_factory=list)


def extract_refs(content: str) -> ArtifactRef:
    """Extract PR numbers, commit hashes, and repo from content string.

    Args:
        content: Raw text content from a memory artifact.

    Returns:
        ArtifactRef with extracted references (deduplicated).
    """
    pr_matches = _PR_RE.findall(content)
    pr_numbers = list(dict.fromkeys(int(m) for m in pr_matches))

    hash_matches = _HASH_RE.findall(content)
    commit_hashes = list(dict.fromkeys(hash_matches))

    repo_match = _REPO_RE.search(content)
    repo = repo_match.group(1) if repo_match else None

    references = _build_references(pr_numbers, commit_hashes)

    return ArtifactRef(
        pr_numbers=pr_numbers,
        commit_hashes=commit_hashes,
        references=references,
        repo=repo,
    )


def extract_refs_from_hits(
    hits: list[SearchHit],
) -> list[tuple[SearchHit, ArtifactRef]]:
    """Extract refs from each SearchHit, preserving hit association.

    Args:
        hits: List of SearchHit objects from memory search.

    Returns:
        List of (SearchHit, ArtifactRef) tuples in the same order as input.
    """
    return [(hit, extract_refs(hit.content)) for hit in hits]


def collect_all_refs(hits: list[SearchHit]) -> ArtifactRef:
    """Aggregate unique refs across all search hits.

    Args:
        hits: List of SearchHit objects from memory search.

    Returns:
        Single ArtifactRef with deduplicated PRs and hashes from all hits.
        Uses the first non-None repo found.
    """
    all_prs: list[int] = []
    all_hashes: list[str] = []
    first_repo: str | None = None

    for hit in hits:
        ref = extract_refs(hit.content)
        all_prs.extend(ref.pr_numbers)
        all_hashes.extend(ref.commit_hashes)
        if first_repo is None and ref.repo is not None:
            first_repo = ref.repo

    unique_prs = list(dict.fromkeys(all_prs))
    unique_hashes = list(dict.fromkeys(all_hashes))
    references = _build_references(unique_prs, unique_hashes)

    return ArtifactRef(
        pr_numbers=unique_prs,
        commit_hashes=unique_hashes,
        references=references,
        repo=first_repo,
    )


def extract_refs_by_note(hits: list[SearchHit]) -> list[NoteRefs]:
    """Extract refs grouped by note_id as unified string arrays.

    Args:
        hits: List of SearchHit objects from memory search.

    Returns:
        List of NoteRefs, one per hit, with references as formatted strings.
        Example: [NoteRefs(note_id="11", references=["pr #123", "commit qdsf"])]
    """
    result: list[NoteRefs] = []
    for hit in hits:
        ref = extract_refs(hit.content)
        result.append(NoteRefs(note_id=hit.note_id, references=ref.references))
    return result
