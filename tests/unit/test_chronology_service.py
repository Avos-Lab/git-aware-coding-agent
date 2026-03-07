"""Brutal tests for ChronologyService.

Covers ISO 8601 parsing, UTC normalization, deterministic sort contract
(timestamp ASC, rank ASC, note_id ASC), null/invalid handling, duplicate
timestamps, and 3-run repeatability.
"""

from __future__ import annotations

import pytest

from avos_cli.models.query import RetrievedArtifact
from avos_cli.services.chronology_service import ChronologyService


def _make_artifact(
    note_id: str = "note-1",
    created_at: str = "2026-01-15T10:00:00Z",
    rank: int = 1,
) -> RetrievedArtifact:
    return RetrievedArtifact(
        note_id=note_id, content="content", created_at=created_at, rank=rank
    )


class TestBasicChronologicalSort:
    """Artifacts sorted by timestamp ascending (oldest first)."""

    def test_already_sorted(self):
        svc = ChronologyService()
        arts = [
            _make_artifact(note_id="a", created_at="2026-01-10T00:00:00Z"),
            _make_artifact(note_id="b", created_at="2026-01-15T00:00:00Z"),
            _make_artifact(note_id="c", created_at="2026-01-20T00:00:00Z"),
        ]
        result = svc.sort(arts)
        assert [a.note_id for a in result] == ["a", "b", "c"]

    def test_reverse_sorted(self):
        svc = ChronologyService()
        arts = [
            _make_artifact(note_id="c", created_at="2026-01-20T00:00:00Z"),
            _make_artifact(note_id="b", created_at="2026-01-15T00:00:00Z"),
            _make_artifact(note_id="a", created_at="2026-01-10T00:00:00Z"),
        ]
        result = svc.sort(arts)
        assert [a.note_id for a in result] == ["a", "b", "c"]

    def test_mixed_order(self):
        svc = ChronologyService()
        arts = [
            _make_artifact(note_id="b", created_at="2026-01-15T00:00:00Z"),
            _make_artifact(note_id="a", created_at="2026-01-10T00:00:00Z"),
            _make_artifact(note_id="c", created_at="2026-01-20T00:00:00Z"),
        ]
        result = svc.sort(arts)
        assert [a.note_id for a in result] == ["a", "b", "c"]


class TestTieBreakers:
    """Same timestamp: rank ASC, then note_id ASC."""

    def test_same_timestamp_rank_ascending(self):
        svc = ChronologyService()
        arts = [
            _make_artifact(note_id="a", created_at="2026-01-15T00:00:00Z", rank=3),
            _make_artifact(note_id="b", created_at="2026-01-15T00:00:00Z", rank=1),
            _make_artifact(note_id="c", created_at="2026-01-15T00:00:00Z", rank=2),
        ]
        result = svc.sort(arts)
        assert [a.note_id for a in result] == ["b", "c", "a"]

    def test_same_timestamp_same_rank_note_id_ascending(self):
        svc = ChronologyService()
        arts = [
            _make_artifact(note_id="c", created_at="2026-01-15T00:00:00Z", rank=1),
            _make_artifact(note_id="a", created_at="2026-01-15T00:00:00Z", rank=1),
            _make_artifact(note_id="b", created_at="2026-01-15T00:00:00Z", rank=1),
        ]
        result = svc.sort(arts)
        assert [a.note_id for a in result] == ["a", "b", "c"]


class TestNullAndInvalidTimestamps:
    """Invalid/null timestamps sorted last with stable tie-breakers."""

    def test_empty_timestamp_sorted_last(self):
        svc = ChronologyService()
        arts = [
            _make_artifact(note_id="valid", created_at="2026-01-15T00:00:00Z"),
            _make_artifact(note_id="empty", created_at=""),
        ]
        result = svc.sort(arts)
        assert [a.note_id for a in result] == ["valid", "empty"]

    def test_invalid_timestamp_sorted_last(self):
        svc = ChronologyService()
        arts = [
            _make_artifact(note_id="valid", created_at="2026-01-15T00:00:00Z"),
            _make_artifact(note_id="invalid", created_at="not-a-date"),
        ]
        result = svc.sort(arts)
        assert [a.note_id for a in result] == ["valid", "invalid"]

    def test_multiple_invalid_stable_order(self):
        svc = ChronologyService()
        arts = [
            _make_artifact(note_id="b-invalid", created_at="garbage", rank=2),
            _make_artifact(note_id="a-invalid", created_at="", rank=1),
            _make_artifact(note_id="valid", created_at="2026-01-15T00:00:00Z", rank=3),
        ]
        result = svc.sort(arts)
        assert result[0].note_id == "valid"
        # Invalid ones sorted by rank ASC, then note_id ASC
        assert result[1].note_id == "a-invalid"
        assert result[2].note_id == "b-invalid"


class TestTimezoneHandling:
    """All timestamps treated as UTC."""

    def test_z_suffix_parsed(self):
        svc = ChronologyService()
        arts = [
            _make_artifact(note_id="a", created_at="2026-01-15T10:00:00Z"),
            _make_artifact(note_id="b", created_at="2026-01-15T09:00:00Z"),
        ]
        result = svc.sort(arts)
        assert [a.note_id for a in result] == ["b", "a"]

    def test_offset_suffix_parsed(self):
        svc = ChronologyService()
        arts = [
            _make_artifact(note_id="a", created_at="2026-01-15T10:00:00+00:00"),
            _make_artifact(note_id="b", created_at="2026-01-15T09:00:00+00:00"),
        ]
        result = svc.sort(arts)
        assert [a.note_id for a in result] == ["b", "a"]

    def test_no_timezone_treated_as_utc(self):
        svc = ChronologyService()
        arts = [
            _make_artifact(note_id="a", created_at="2026-01-15T10:00:00"),
            _make_artifact(note_id="b", created_at="2026-01-15T09:00:00"),
        ]
        result = svc.sort(arts)
        assert [a.note_id for a in result] == ["b", "a"]


class TestDeterminism:
    """Same input must produce identical output across runs."""

    def test_three_run_repeatability(self):
        svc = ChronologyService()
        arts = [
            _make_artifact(note_id=f"n-{i}", created_at=f"2026-01-{10+i:02d}T00:00:00Z", rank=(i % 3) + 1)
            for i in range(15)
        ]
        r1 = [a.note_id for a in svc.sort(arts)]
        r2 = [a.note_id for a in svc.sort(arts)]
        r3 = [a.note_id for a in svc.sort(arts)]
        assert r1 == r2 == r3

    def test_shuffled_input_same_output(self):
        svc = ChronologyService()
        import random
        arts = [
            _make_artifact(note_id=f"n-{i}", created_at=f"2026-01-{10+i:02d}T00:00:00Z", rank=i + 1)
            for i in range(10)
        ]
        shuffled = list(arts)
        random.Random(42).shuffle(shuffled)
        r1 = [a.note_id for a in svc.sort(arts)]
        r2 = [a.note_id for a in svc.sort(shuffled)]
        assert r1 == r2


class TestEdgeCases:
    def test_empty_list(self):
        svc = ChronologyService()
        assert svc.sort([]) == []

    def test_single_artifact(self):
        svc = ChronologyService()
        art = _make_artifact(note_id="only")
        result = svc.sort([art])
        assert len(result) == 1
        assert result[0].note_id == "only"

    def test_date_only_format(self):
        svc = ChronologyService()
        arts = [
            _make_artifact(note_id="a", created_at="2026-01-15"),
            _make_artifact(note_id="b", created_at="2026-01-10"),
        ]
        result = svc.sort(arts)
        assert [a.note_id for a in result] == ["b", "a"]
