"""Brutal tests for ContextBudgetService.

Covers deterministic comparator, hard caps (ask/history), per-artifact
truncation, minimum evidence floor, budget metadata, ordering stability,
and hostile edge cases.
"""

from __future__ import annotations

import pytest

from avos_cli.models.query import SanitizedArtifact
from avos_cli.services.context_budget_service import ContextBudgetService


def _make_sanitized(
    note_id: str = "note-1",
    content: str = "content",
    created_at: str = "2026-01-15T10:00:00Z",
    rank: int = 1,
) -> SanitizedArtifact:
    return SanitizedArtifact(
        note_id=note_id, content=content, created_at=created_at, rank=rank
    )


class TestAskModeBudget:
    """Ask mode: max 6 artifacts, 800 chars per excerpt."""

    def test_under_cap_all_included(self):
        svc = ContextBudgetService()
        arts = [_make_sanitized(note_id=f"n-{i}") for i in range(4)]
        result = svc.pack(arts, mode="ask")
        assert result.included_count == 4
        assert result.excluded_count == 0

    def test_at_cap_all_included(self):
        svc = ContextBudgetService()
        arts = [_make_sanitized(note_id=f"n-{i}") for i in range(6)]
        result = svc.pack(arts, mode="ask")
        assert result.included_count == 6

    def test_over_cap_trimmed(self):
        svc = ContextBudgetService()
        arts = [_make_sanitized(note_id=f"n-{i}", rank=i + 1) for i in range(10)]
        result = svc.pack(arts, mode="ask")
        assert result.included_count == 6
        assert result.excluded_count == 4

    def test_truncation_at_800_chars(self):
        svc = ContextBudgetService()
        long_content = "x" * 1000
        art = _make_sanitized(content=long_content)
        result = svc.pack([art], mode="ask")
        assert len(result.included[0].content) <= 803  # 800 + "..."
        assert result.included[0].content.endswith("...")
        assert result.truncation_flags[art.note_id] is True

    def test_no_truncation_under_limit(self):
        svc = ContextBudgetService()
        art = _make_sanitized(content="x" * 500)
        result = svc.pack([art], mode="ask")
        assert result.included[0].content == "x" * 500
        assert result.truncation_flags[art.note_id] is False


class TestHistoryModeBudget:
    """History mode: max 10 artifacts, 600 chars per excerpt."""

    def test_under_cap_all_included(self):
        svc = ContextBudgetService()
        arts = [_make_sanitized(note_id=f"n-{i}") for i in range(8)]
        result = svc.pack(arts, mode="history")
        assert result.included_count == 8

    def test_over_cap_trimmed(self):
        svc = ContextBudgetService()
        arts = [_make_sanitized(note_id=f"n-{i}", rank=i + 1) for i in range(15)]
        result = svc.pack(arts, mode="history")
        assert result.included_count == 10
        assert result.excluded_count == 5

    def test_truncation_at_600_chars(self):
        svc = ContextBudgetService()
        long_content = "y" * 800
        art = _make_sanitized(content=long_content)
        result = svc.pack([art], mode="history")
        assert len(result.included[0].content) <= 603
        assert result.included[0].content.endswith("...")


class TestDeterministicOrdering:
    """Comparator: rank ASC, created_at DESC, note_id ASC."""

    def test_rank_ascending(self):
        svc = ContextBudgetService()
        arts = [
            _make_sanitized(note_id="a", rank=3),
            _make_sanitized(note_id="b", rank=1),
            _make_sanitized(note_id="c", rank=2),
        ]
        result = svc.pack(arts, mode="ask")
        ids = [a.note_id for a in result.included]
        assert ids == ["b", "c", "a"]

    def test_same_rank_created_at_descending(self):
        svc = ContextBudgetService()
        arts = [
            _make_sanitized(note_id="a", rank=1, created_at="2026-01-10T00:00:00Z"),
            _make_sanitized(note_id="b", rank=1, created_at="2026-01-15T00:00:00Z"),
            _make_sanitized(note_id="c", rank=1, created_at="2026-01-12T00:00:00Z"),
        ]
        result = svc.pack(arts, mode="ask")
        ids = [a.note_id for a in result.included]
        assert ids == ["b", "c", "a"]  # newest first for same rank

    def test_same_rank_same_date_note_id_ascending(self):
        svc = ContextBudgetService()
        arts = [
            _make_sanitized(note_id="c", rank=1, created_at="2026-01-15T00:00:00Z"),
            _make_sanitized(note_id="a", rank=1, created_at="2026-01-15T00:00:00Z"),
            _make_sanitized(note_id="b", rank=1, created_at="2026-01-15T00:00:00Z"),
        ]
        result = svc.pack(arts, mode="ask")
        ids = [a.note_id for a in result.included]
        assert ids == ["a", "b", "c"]

    def test_determinism_across_runs(self):
        svc = ContextBudgetService()
        arts = [
            _make_sanitized(note_id=f"n-{i}", rank=(i % 3) + 1, created_at=f"2026-01-{10+i:02d}T00:00:00Z")
            for i in range(10)
        ]
        r1 = svc.pack(arts, mode="ask")
        r2 = svc.pack(arts, mode="ask")
        r3 = svc.pack(arts, mode="ask")
        ids1 = [a.note_id for a in r1.included]
        ids2 = [a.note_id for a in r2.included]
        ids3 = [a.note_id for a in r3.included]
        assert ids1 == ids2 == ids3


class TestNullHandling:
    """Null rank and null created_at sorted last with stable tie-breakers."""

    def test_null_rank_sorted_last(self):
        svc = ContextBudgetService()
        arts = [
            _make_sanitized(note_id="a", rank=1),
            _make_sanitized(note_id="b", rank=999999999),  # simulates null -> max int
            _make_sanitized(note_id="c", rank=2),
        ]
        result = svc.pack(arts, mode="ask")
        ids = [a.note_id for a in result.included]
        assert ids[-1] == "b"

    def test_empty_created_at_sorted_last_in_tie(self):
        svc = ContextBudgetService()
        arts = [
            _make_sanitized(note_id="a", rank=1, created_at="2026-01-15T00:00:00Z"),
            _make_sanitized(note_id="b", rank=1, created_at=""),
        ]
        result = svc.pack(arts, mode="ask")
        ids = [a.note_id for a in result.included]
        assert ids == ["a", "b"]


class TestMinimumEvidenceFloor:
    """Below 2 artifacts = signal fallback needed."""

    def test_zero_artifacts_signals_fallback(self):
        svc = ContextBudgetService()
        result = svc.pack([], mode="ask")
        assert result.included_count == 0
        # Caller checks included_count < 2 for fallback

    def test_one_artifact_below_floor(self):
        svc = ContextBudgetService()
        result = svc.pack([_make_sanitized()], mode="ask")
        assert result.included_count == 1

    def test_two_artifacts_meets_floor(self):
        svc = ContextBudgetService()
        arts = [_make_sanitized(note_id=f"n-{i}") for i in range(2)]
        result = svc.pack(arts, mode="ask")
        assert result.included_count == 2


class TestBudgetMetadata:
    """Budget result must carry accurate metadata."""

    def test_truncation_flags_complete(self):
        svc = ContextBudgetService()
        arts = [
            _make_sanitized(note_id="short", content="x" * 100),
            _make_sanitized(note_id="long", content="x" * 1000),
        ]
        result = svc.pack(arts, mode="ask")
        assert "short" in result.truncation_flags
        assert "long" in result.truncation_flags
        assert result.truncation_flags["short"] is False
        assert result.truncation_flags["long"] is True

    def test_excluded_artifacts_preserved(self):
        svc = ContextBudgetService()
        arts = [_make_sanitized(note_id=f"n-{i}", rank=i + 1) for i in range(8)]
        result = svc.pack(arts, mode="ask")
        assert result.excluded_count == 2
        excluded_ids = {a.note_id for a in result.excluded}
        assert len(excluded_ids) == 2

    def test_included_plus_excluded_equals_total(self):
        svc = ContextBudgetService()
        arts = [_make_sanitized(note_id=f"n-{i}", rank=i + 1) for i in range(10)]
        result = svc.pack(arts, mode="ask")
        assert result.included_count + result.excluded_count == 10
