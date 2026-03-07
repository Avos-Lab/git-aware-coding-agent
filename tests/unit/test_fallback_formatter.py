"""Brutal tests for QueryFallbackFormatter.

Covers ask top-3 fallback, history chronological fallback, approved
templates, sanitized-only output, reason headers, deterministic ordering,
and edge cases.
"""

from __future__ import annotations

import pytest

from avos_cli.models.query import FallbackReason, SanitizedArtifact
from avos_cli.services.query_fallback_formatter import QueryFallbackFormatter


def _make_sanitized(
    note_id: str = "note-1",
    content: str = "sanitized content",
    created_at: str = "2026-01-15T10:00:00Z",
    rank: int = 1,
) -> SanitizedArtifact:
    return SanitizedArtifact(
        note_id=note_id, content=content, created_at=created_at, rank=rank
    )


class TestAskFallback:
    """Ask fallback: header + exactly top 3 sanitized items."""

    def test_exactly_three_items(self):
        svc = QueryFallbackFormatter()
        arts = [_make_sanitized(note_id=f"n-{i}", rank=i + 1) for i in range(5)]
        output = svc.format_ask_fallback(arts, FallbackReason.LLM_UNAVAILABLE)
        assert output.count("---") >= 2  # at least 3 items separated
        assert "n-0" in output
        assert "n-1" in output
        assert "n-2" in output
        assert "n-3" not in output
        assert "n-4" not in output

    def test_fewer_than_three_shows_all(self):
        svc = QueryFallbackFormatter()
        arts = [_make_sanitized(note_id="only-one")]
        output = svc.format_ask_fallback(arts, FallbackReason.LLM_UNAVAILABLE)
        assert "only-one" in output

    def test_header_contains_reason(self):
        svc = QueryFallbackFormatter()
        arts = [_make_sanitized()]
        output = svc.format_ask_fallback(arts, FallbackReason.LLM_UNAVAILABLE)
        assert "unavailable" in output.lower() or "safety" in output.lower() or "fallback" in output.lower()

    def test_header_for_grounding_failed(self):
        svc = QueryFallbackFormatter()
        arts = [_make_sanitized()]
        output = svc.format_ask_fallback(arts, FallbackReason.GROUNDING_FAILED)
        assert "fallback" in output.lower() or "grounding" in output.lower()

    def test_header_for_safety_block(self):
        svc = QueryFallbackFormatter()
        arts = [_make_sanitized()]
        output = svc.format_ask_fallback(arts, FallbackReason.SAFETY_BLOCK)
        assert "safety" in output.lower() or "fallback" in output.lower()

    def test_ordering_by_rank(self):
        svc = QueryFallbackFormatter()
        arts = [
            _make_sanitized(note_id="r3", rank=3),
            _make_sanitized(note_id="r1", rank=1),
            _make_sanitized(note_id="r2", rank=2),
        ]
        output = svc.format_ask_fallback(arts, FallbackReason.LLM_UNAVAILABLE)
        pos_r1 = output.index("r1")
        pos_r2 = output.index("r2")
        pos_r3 = output.index("r3")
        assert pos_r1 < pos_r2 < pos_r3

    def test_empty_artifacts(self):
        svc = QueryFallbackFormatter()
        output = svc.format_ask_fallback([], FallbackReason.LLM_UNAVAILABLE)
        assert "no" in output.lower() or "unavailable" in output.lower()


class TestHistoryFallback:
    """History fallback: header + chronological sanitized items."""

    def test_chronological_order(self):
        svc = QueryFallbackFormatter()
        arts = [
            _make_sanitized(note_id="later", created_at="2026-01-20T00:00:00Z"),
            _make_sanitized(note_id="earlier", created_at="2026-01-10T00:00:00Z"),
            _make_sanitized(note_id="middle", created_at="2026-01-15T00:00:00Z"),
        ]
        output = svc.format_history_fallback(arts, FallbackReason.LLM_UNAVAILABLE)
        pos_earlier = output.index("earlier")
        pos_middle = output.index("middle")
        pos_later = output.index("later")
        assert pos_earlier < pos_middle < pos_later

    def test_header_contains_reason(self):
        svc = QueryFallbackFormatter()
        arts = [_make_sanitized()]
        output = svc.format_history_fallback(arts, FallbackReason.LLM_UNAVAILABLE)
        assert "timeline" in output.lower() or "fallback" in output.lower()

    def test_empty_artifacts(self):
        svc = QueryFallbackFormatter()
        output = svc.format_history_fallback([], FallbackReason.LLM_UNAVAILABLE)
        assert "no" in output.lower() or "unavailable" in output.lower()

    def test_all_items_shown(self):
        svc = QueryFallbackFormatter()
        arts = [_make_sanitized(note_id=f"n-{i}", created_at=f"2026-01-{10+i:02d}T00:00:00Z") for i in range(7)]
        output = svc.format_history_fallback(arts, FallbackReason.LLM_UNAVAILABLE)
        for i in range(7):
            assert f"n-{i}" in output


class TestOutputFormat:
    """Structured block format with metadata + sanitized excerpt."""

    def test_contains_note_id(self):
        svc = QueryFallbackFormatter()
        art = _make_sanitized(note_id="abc-123", content="Some evidence")
        output = svc.format_ask_fallback([art], FallbackReason.LLM_UNAVAILABLE)
        assert "abc-123" in output

    def test_contains_excerpt(self):
        svc = QueryFallbackFormatter()
        art = _make_sanitized(content="This is the sanitized excerpt text.")
        output = svc.format_ask_fallback([art], FallbackReason.LLM_UNAVAILABLE)
        assert "sanitized excerpt text" in output

    def test_contains_timestamp(self):
        svc = QueryFallbackFormatter()
        art = _make_sanitized(created_at="2026-01-15T10:00:00Z")
        output = svc.format_ask_fallback([art], FallbackReason.LLM_UNAVAILABLE)
        assert "2026-01-15" in output


class TestDeterminism:
    """Same input must produce identical output."""

    def test_ask_deterministic(self):
        svc = QueryFallbackFormatter()
        arts = [_make_sanitized(note_id=f"n-{i}", rank=i + 1) for i in range(5)]
        o1 = svc.format_ask_fallback(arts, FallbackReason.LLM_UNAVAILABLE)
        o2 = svc.format_ask_fallback(arts, FallbackReason.LLM_UNAVAILABLE)
        o3 = svc.format_ask_fallback(arts, FallbackReason.LLM_UNAVAILABLE)
        assert o1 == o2 == o3

    def test_history_deterministic(self):
        svc = QueryFallbackFormatter()
        arts = [
            _make_sanitized(note_id=f"n-{i}", created_at=f"2026-01-{10+i:02d}T00:00:00Z")
            for i in range(5)
        ]
        o1 = svc.format_history_fallback(arts, FallbackReason.LLM_UNAVAILABLE)
        o2 = svc.format_history_fallback(arts, FallbackReason.LLM_UNAVAILABLE)
        o3 = svc.format_history_fallback(arts, FallbackReason.LLM_UNAVAILABLE)
        assert o1 == o2 == o3
