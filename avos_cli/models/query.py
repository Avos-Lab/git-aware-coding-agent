"""Query pipeline internal contracts for Sprint 3 (AVOS-012..015).

Defines frozen Pydantic models for the query synthesis pipeline:
retrieval, sanitization, budget packing, citation grounding,
chronology, synthesis request/response, and result envelopes.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict


class QueryMode(str, Enum):
    """Synthesis mode selector for ask vs history pipelines."""

    ASK = "ask"
    HISTORY = "history"


class FallbackReason(str, Enum):
    """Categorized reasons for falling back from synthesis to raw results."""

    LLM_UNAVAILABLE = "llm_unavailable"
    GROUNDING_FAILED = "grounding_failed"
    SAFETY_BLOCK = "safety_block"
    BUDGET_EXHAUSTED = "budget_exhausted"


class GroundingStatus(str, Enum):
    """Citation grounding validation outcome."""

    GROUNDED = "grounded"
    DROPPED_UNVERIFIABLE = "dropped_unverifiable"


class ReferenceType(str, Enum):
    """Type of evidence reference for display purposes."""

    NOTE_ID = "note_id"
    PR = "pr"
    ISSUE = "issue"
    COMMIT = "commit"


class RetrievedArtifact(BaseModel):
    """A single artifact returned from Memory API search.

    Args:
        note_id: Unique identifier from Memory API.
        content: Full text content of the note.
        created_at: ISO 8601 creation timestamp.
        rank: Relevance rank (1 = best match).
        source_type: Classified artifact type (e.g. raw_pr_thread).
        display_ref: Optional human-friendly label (e.g. PR #101).
    """

    model_config = ConfigDict(frozen=True)

    note_id: str
    content: str
    created_at: str
    rank: int
    source_type: str | None = None
    display_ref: str | None = None


class SanitizedArtifact(BaseModel):
    """An artifact after sanitization/redaction processing.

    Carries the same fields as RetrievedArtifact plus redaction audit metadata.

    Args:
        note_id: Unique identifier from Memory API.
        content: Sanitized text content (secrets/PII redacted).
        created_at: ISO 8601 creation timestamp.
        rank: Relevance rank.
        source_type: Classified artifact type.
        display_ref: Optional human-friendly label.
        redaction_applied: Whether any redaction was performed.
        redaction_types: List of redaction categories applied.
    """

    model_config = ConfigDict(frozen=True)

    note_id: str
    content: str
    created_at: str
    rank: int
    source_type: str | None = None
    display_ref: str | None = None
    redaction_applied: bool = False
    redaction_types: list[str] = []


class SanitizationResult(BaseModel):
    """Aggregate result of sanitization across all artifacts.

    Args:
        artifacts: List of sanitized artifacts.
        redaction_applied: Whether any redaction occurred across the set.
        redaction_types: Union of all redaction categories applied.
        confidence_score: Sanitization confidence (0-100).
    """

    model_config = ConfigDict(frozen=True)

    artifacts: list[SanitizedArtifact]
    redaction_applied: bool
    redaction_types: list[str]
    confidence_score: int


class BudgetResult(BaseModel):
    """Result of context-budget packing.

    Args:
        included: Artifacts selected for synthesis (within budget).
        excluded: Artifacts cut due to budget constraints.
        truncation_flags: Map of note_id -> was_truncated.
        included_count: Number of included artifacts.
        excluded_count: Number of excluded artifacts.
    """

    model_config = ConfigDict(frozen=True)

    included: list[SanitizedArtifact]
    excluded: list[SanitizedArtifact]
    truncation_flags: dict[str, bool]
    included_count: int
    excluded_count: int


class GroundedCitation(BaseModel):
    """A citation validated against retrieved artifacts.

    Args:
        note_id: The artifact note_id this citation references.
        display_label: Human-friendly label (e.g. PR #101, Issue #42).
        reference_type: Category of the reference.
        grounding_status: Whether the citation is grounded or dropped.
    """

    model_config = ConfigDict(frozen=True)

    note_id: str
    display_label: str
    reference_type: ReferenceType
    grounding_status: GroundingStatus


class TimelineEvent(BaseModel):
    """A classified event in a chronological history timeline.

    Args:
        timestamp: ISO 8601 timestamp of the event.
        event_class: Classification (Introduction, Expansion, Bug Fix, etc.).
        summary: Brief description of the event.
        supporting_refs: List of note_ids supporting this event.
    """

    model_config = ConfigDict(frozen=True)

    timestamp: str
    event_class: str
    summary: str
    supporting_refs: list[str] = []


class SynthesisRequest(BaseModel):
    """Request payload for LLM synthesis.

    Args:
        mode: ask or history pipeline selector.
        query: User's question or subject.
        provider: LLM provider name.
        model: LLM model identifier.
        prompt_template_version: Version tag for prompt template.
        artifacts: Packed, sanitized artifacts for context.
        budget_meta: Optional budget metadata for diagnostics.
    """

    model_config = ConfigDict(frozen=True)

    mode: QueryMode
    query: str
    provider: str
    model: str
    prompt_template_version: str
    artifacts: list[SanitizedArtifact]
    budget_meta: dict[str, object] | None = None


class SynthesisResponse(BaseModel):
    """Response from LLM synthesis.

    Args:
        answer_text: The synthesized answer or timeline narrative.
        evidence_refs: Grounded citation references.
        timeline_events: Classified timeline events (history mode).
        warnings: Any warnings (truncation, partial grounding, etc.).
    """

    model_config = ConfigDict(frozen=True)

    answer_text: str
    evidence_refs: list[GroundedCitation] = []
    timeline_events: list[TimelineEvent] = []
    warnings: list[str] = []


class QueryResultEnvelope(BaseModel):
    """Final result envelope returned to CLI layer.

    Args:
        mode: ask or history.
        answer: Synthesized answer text (ask mode).
        timeline: Chronological events (history mode).
        citations: Grounded citations for evidence display.
        fallback_used: Whether fallback was triggered.
        warnings: Any warnings to display.
        fallback_reason: Categorized reason if fallback was used.
    """

    model_config = ConfigDict(frozen=True)

    mode: QueryMode
    answer: str | None = None
    timeline: list[TimelineEvent] | None = None
    citations: list[GroundedCitation]
    fallback_used: bool
    warnings: list[str] = []
    fallback_reason: FallbackReason | None = None
