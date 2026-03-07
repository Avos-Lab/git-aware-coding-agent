"""Tests for Sprint 3 query pipeline models (avos_cli/models/query.py).

Covers valid instantiation, invalid rejection, frozen immutability,
enum behavior, default values, serialization, and edge cases for all
query pipeline internal contracts.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from avos_cli.models.query import (
    BudgetResult,
    FallbackReason,
    GroundedCitation,
    GroundingStatus,
    QueryMode,
    QueryResultEnvelope,
    ReferenceType,
    RetrievedArtifact,
    SanitizationResult,
    SanitizedArtifact,
    SynthesisRequest,
    SynthesisResponse,
    TimelineEvent,
)


class TestQueryMode:
    def test_ask_value(self):
        assert QueryMode.ASK == "ask"

    def test_history_value(self):
        assert QueryMode.HISTORY == "history"

    def test_invalid_mode_not_in_enum(self):
        with pytest.raises(ValueError):
            QueryMode("invalid")


class TestFallbackReason:
    def test_all_values_exist(self):
        assert FallbackReason.LLM_UNAVAILABLE == "llm_unavailable"
        assert FallbackReason.GROUNDING_FAILED == "grounding_failed"
        assert FallbackReason.SAFETY_BLOCK == "safety_block"
        assert FallbackReason.BUDGET_EXHAUSTED == "budget_exhausted"

    def test_enum_count(self):
        assert len(FallbackReason) == 4


class TestGroundingStatus:
    def test_values(self):
        assert GroundingStatus.GROUNDED == "grounded"
        assert GroundingStatus.DROPPED_UNVERIFIABLE == "dropped_unverifiable"


class TestReferenceType:
    def test_values(self):
        assert ReferenceType.NOTE_ID == "note_id"
        assert ReferenceType.PR == "pr"
        assert ReferenceType.ISSUE == "issue"
        assert ReferenceType.COMMIT == "commit"


class TestRetrievedArtifact:
    def test_valid_creation(self):
        art = RetrievedArtifact(
            note_id="abc-123",
            content="Some PR discussion about retry logic",
            created_at="2026-01-15T10:00:00Z",
            rank=1,
        )
        assert art.note_id == "abc-123"
        assert art.rank == 1
        assert art.source_type is None
        assert art.display_ref is None

    def test_all_fields(self):
        art = RetrievedArtifact(
            note_id="abc-123",
            content="content",
            created_at="2026-01-15T10:00:00Z",
            rank=2,
            source_type="raw_pr_thread",
            display_ref="PR #101",
        )
        assert art.source_type == "raw_pr_thread"
        assert art.display_ref == "PR #101"

    def test_frozen(self):
        art = RetrievedArtifact(
            note_id="abc", content="c", created_at="2026-01-15T10:00:00Z", rank=1
        )
        with pytest.raises(ValidationError):
            art.rank = 5  # type: ignore[misc]

    def test_missing_required_fields(self):
        with pytest.raises(ValidationError):
            RetrievedArtifact()  # type: ignore[call-arg]

    def test_missing_note_id(self):
        with pytest.raises(ValidationError):
            RetrievedArtifact(content="c", created_at="2026-01-15T10:00:00Z", rank=1)  # type: ignore[call-arg]

    def test_serialization_round_trip(self):
        art = RetrievedArtifact(
            note_id="abc", content="c", created_at="2026-01-15T10:00:00Z", rank=1
        )
        dumped = art.model_dump()
        restored = RetrievedArtifact(**dumped)
        assert restored == art

    def test_empty_content_allowed(self):
        art = RetrievedArtifact(
            note_id="abc", content="", created_at="2026-01-15T10:00:00Z", rank=1
        )
        assert art.content == ""

    def test_large_rank_value(self):
        art = RetrievedArtifact(
            note_id="abc", content="c", created_at="2026-01-15T10:00:00Z", rank=999999
        )
        assert art.rank == 999999


class TestSanitizedArtifact:
    def test_valid_creation(self):
        art = SanitizedArtifact(
            note_id="abc-123",
            content="Some content with [REDACTED_API_KEY]",
            created_at="2026-01-15T10:00:00Z",
            rank=1,
            redaction_applied=True,
            redaction_types=["api_key"],
        )
        assert art.redaction_applied is True
        assert art.redaction_types == ["api_key"]

    def test_defaults(self):
        art = SanitizedArtifact(
            note_id="abc", content="c", created_at="2026-01-15T10:00:00Z", rank=1
        )
        assert art.redaction_applied is False
        assert art.redaction_types == []
        assert art.source_type is None
        assert art.display_ref is None

    def test_frozen(self):
        art = SanitizedArtifact(
            note_id="abc", content="c", created_at="2026-01-15T10:00:00Z", rank=1
        )
        with pytest.raises(ValidationError):
            art.redaction_applied = True  # type: ignore[misc]

    def test_serialization_round_trip(self):
        art = SanitizedArtifact(
            note_id="abc",
            content="c",
            created_at="2026-01-15T10:00:00Z",
            rank=1,
            redaction_applied=True,
            redaction_types=["token", "pii"],
        )
        dumped = art.model_dump()
        restored = SanitizedArtifact(**dumped)
        assert restored == art


class TestSanitizationResult:
    def test_valid_creation(self):
        art = SanitizedArtifact(
            note_id="a", content="c", created_at="2026-01-15T10:00:00Z", rank=1
        )
        result = SanitizationResult(
            artifacts=[art],
            redaction_applied=True,
            redaction_types=["api_key"],
            confidence_score=92,
        )
        assert len(result.artifacts) == 1
        assert result.confidence_score == 92

    def test_empty_artifacts(self):
        result = SanitizationResult(
            artifacts=[],
            redaction_applied=False,
            redaction_types=[],
            confidence_score=100,
        )
        assert result.artifacts == []

    def test_frozen(self):
        result = SanitizationResult(
            artifacts=[], redaction_applied=False, redaction_types=[], confidence_score=100
        )
        with pytest.raises(ValidationError):
            result.confidence_score = 50  # type: ignore[misc]

    def test_confidence_score_boundaries(self):
        for score in [0, 50, 69, 70, 84, 85, 100]:
            result = SanitizationResult(
                artifacts=[], redaction_applied=False, redaction_types=[], confidence_score=score
            )
            assert result.confidence_score == score


class TestBudgetResult:
    def test_valid_creation(self):
        art = SanitizedArtifact(
            note_id="a", content="c", created_at="2026-01-15T10:00:00Z", rank=1
        )
        result = BudgetResult(
            included=[art],
            excluded=[],
            truncation_flags={"a": True},
            included_count=1,
            excluded_count=0,
        )
        assert result.included_count == 1
        assert result.excluded_count == 0

    def test_truncation_flags_mapping(self):
        result = BudgetResult(
            included=[],
            excluded=[],
            truncation_flags={"note-1": True, "note-2": False},
            included_count=0,
            excluded_count=0,
        )
        assert result.truncation_flags["note-1"] is True
        assert result.truncation_flags["note-2"] is False

    def test_frozen(self):
        result = BudgetResult(
            included=[], excluded=[], truncation_flags={}, included_count=0, excluded_count=0
        )
        with pytest.raises(ValidationError):
            result.included_count = 5  # type: ignore[misc]


class TestGroundedCitation:
    def test_valid_grounded(self):
        cit = GroundedCitation(
            note_id="abc-123",
            display_label="PR #101",
            reference_type=ReferenceType.PR,
            grounding_status=GroundingStatus.GROUNDED,
        )
        assert cit.grounding_status == GroundingStatus.GROUNDED

    def test_dropped_unverifiable(self):
        cit = GroundedCitation(
            note_id="xyz",
            display_label="Unknown",
            reference_type=ReferenceType.NOTE_ID,
            grounding_status=GroundingStatus.DROPPED_UNVERIFIABLE,
        )
        assert cit.grounding_status == GroundingStatus.DROPPED_UNVERIFIABLE

    def test_frozen(self):
        cit = GroundedCitation(
            note_id="abc",
            display_label="PR #1",
            reference_type=ReferenceType.PR,
            grounding_status=GroundingStatus.GROUNDED,
        )
        with pytest.raises(ValidationError):
            cit.note_id = "other"  # type: ignore[misc]

    def test_all_reference_types(self):
        for ref_type in ReferenceType:
            cit = GroundedCitation(
                note_id="abc",
                display_label="label",
                reference_type=ref_type,
                grounding_status=GroundingStatus.GROUNDED,
            )
            assert cit.reference_type == ref_type


class TestTimelineEvent:
    def test_valid_creation(self):
        evt = TimelineEvent(
            timestamp="2026-01-15T10:00:00Z",
            event_class="Introduction",
            summary="Initial implementation of retry logic",
            supporting_refs=["abc-123", "def-456"],
        )
        assert evt.event_class == "Introduction"
        assert len(evt.supporting_refs) == 2

    def test_defaults(self):
        evt = TimelineEvent(
            timestamp="2026-01-15T10:00:00Z",
            event_class="Bug Fix",
            summary="Fixed crash",
        )
        assert evt.supporting_refs == []

    def test_frozen(self):
        evt = TimelineEvent(
            timestamp="2026-01-15T10:00:00Z",
            event_class="Refactor",
            summary="Cleaned up",
        )
        with pytest.raises(ValidationError):
            evt.summary = "changed"  # type: ignore[misc]


class TestSynthesisRequest:
    def test_valid_ask_request(self):
        art = SanitizedArtifact(
            note_id="a", content="c", created_at="2026-01-15T10:00:00Z", rank=1
        )
        req = SynthesisRequest(
            mode=QueryMode.ASK,
            query="How does auth work?",
            provider="anthropic",
            model="claude-sonnet-4-5-20250929",
            prompt_template_version="ask_v1",
            artifacts=[art],
        )
        assert req.mode == QueryMode.ASK
        assert req.query == "How does auth work?"

    def test_valid_history_request(self):
        req = SynthesisRequest(
            mode=QueryMode.HISTORY,
            query="payment system",
            provider="anthropic",
            model="claude-sonnet-4-5-20250929",
            prompt_template_version="history_v1",
            artifacts=[],
        )
        assert req.mode == QueryMode.HISTORY

    def test_budget_meta_default(self):
        req = SynthesisRequest(
            mode=QueryMode.ASK,
            query="q",
            provider="p",
            model="m",
            prompt_template_version="v1",
            artifacts=[],
        )
        assert req.budget_meta is None

    def test_frozen(self):
        req = SynthesisRequest(
            mode=QueryMode.ASK,
            query="q",
            provider="p",
            model="m",
            prompt_template_version="v1",
            artifacts=[],
        )
        with pytest.raises(ValidationError):
            req.query = "other"  # type: ignore[misc]


class TestSynthesisResponse:
    def test_valid_ask_response(self):
        resp = SynthesisResponse(
            answer_text="Auth uses JWT tokens.",
            evidence_refs=[
                GroundedCitation(
                    note_id="abc",
                    display_label="PR #10",
                    reference_type=ReferenceType.PR,
                    grounding_status=GroundingStatus.GROUNDED,
                )
            ],
        )
        assert resp.answer_text == "Auth uses JWT tokens."
        assert len(resp.evidence_refs) == 1

    def test_defaults(self):
        resp = SynthesisResponse(answer_text="answer")
        assert resp.evidence_refs == []
        assert resp.timeline_events == []
        assert resp.warnings == []

    def test_with_timeline_events(self):
        evt = TimelineEvent(
            timestamp="2026-01-15T10:00:00Z",
            event_class="Introduction",
            summary="Added auth",
        )
        resp = SynthesisResponse(
            answer_text="Timeline of auth",
            timeline_events=[evt],
        )
        assert len(resp.timeline_events) == 1

    def test_with_warnings(self):
        resp = SynthesisResponse(
            answer_text="answer",
            warnings=["2 citations removed as unverifiable"],
        )
        assert len(resp.warnings) == 1

    def test_frozen(self):
        resp = SynthesisResponse(answer_text="answer")
        with pytest.raises(ValidationError):
            resp.answer_text = "other"  # type: ignore[misc]


class TestQueryResultEnvelope:
    def test_ask_success(self):
        env = QueryResultEnvelope(
            mode=QueryMode.ASK,
            answer="Auth uses JWT.",
            citations=[],
            fallback_used=False,
        )
        assert env.mode == QueryMode.ASK
        assert env.answer == "Auth uses JWT."
        assert env.timeline is None
        assert env.fallback_used is False

    def test_history_success(self):
        evt = TimelineEvent(
            timestamp="2026-01-15T10:00:00Z",
            event_class="Introduction",
            summary="Added auth",
        )
        env = QueryResultEnvelope(
            mode=QueryMode.HISTORY,
            timeline=[evt],
            citations=[],
            fallback_used=False,
        )
        assert env.timeline is not None
        assert len(env.timeline) == 1

    def test_fallback_with_reason(self):
        env = QueryResultEnvelope(
            mode=QueryMode.ASK,
            answer="Fallback content",
            citations=[],
            fallback_used=True,
            fallback_reason=FallbackReason.LLM_UNAVAILABLE,
        )
        assert env.fallback_used is True
        assert env.fallback_reason == FallbackReason.LLM_UNAVAILABLE

    def test_defaults(self):
        env = QueryResultEnvelope(
            mode=QueryMode.ASK,
            citations=[],
            fallback_used=False,
        )
        assert env.answer is None
        assert env.timeline is None
        assert env.warnings == []
        assert env.fallback_reason is None

    def test_frozen(self):
        env = QueryResultEnvelope(
            mode=QueryMode.ASK, citations=[], fallback_used=False
        )
        with pytest.raises(ValidationError):
            env.fallback_used = True  # type: ignore[misc]

    def test_serialization_round_trip(self):
        cit = GroundedCitation(
            note_id="abc",
            display_label="PR #1",
            reference_type=ReferenceType.PR,
            grounding_status=GroundingStatus.GROUNDED,
        )
        env = QueryResultEnvelope(
            mode=QueryMode.ASK,
            answer="answer",
            citations=[cit],
            fallback_used=False,
            warnings=["truncated"],
        )
        dumped = env.model_dump()
        restored = QueryResultEnvelope(**dumped)
        assert restored.mode == env.mode
        assert restored.answer == env.answer
        assert len(restored.citations) == 1
