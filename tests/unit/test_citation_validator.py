"""Brutal tests for CitationValidator.

Covers structured JSON extraction, inline parsing fallback, exact note_id
grounding, minimum 2 threshold, ungrounded removal, warning generation,
and hostile edge cases.
"""

from __future__ import annotations

import json

from avos_cli.models.query import GroundingStatus, ReferenceType, SanitizedArtifact
from avos_cli.services.citation_validator import CitationValidator


def _make_sanitized(note_id: str = "note-1") -> SanitizedArtifact:
    return SanitizedArtifact(
        note_id=note_id, content="c", created_at="2026-01-15T10:00:00Z", rank=1
    )


class TestStructuredExtraction:
    """Extract citations from structured JSON in LLM response."""

    def test_json_citations_extracted(self):
        svc = CitationValidator()
        artifacts = [_make_sanitized("abc"), _make_sanitized("def")]
        response_text = json.dumps({
            "answer": "Auth uses JWT.",
            "citations": [{"note_id": "abc"}, {"note_id": "def"}],
        })
        grounded, _, _ = svc.validate(response_text, artifacts)
        assert len(grounded) == 2
        assert all(c.grounding_status == GroundingStatus.GROUNDED for c in grounded)

    def test_json_with_display_labels(self):
        svc = CitationValidator()
        artifacts = [_make_sanitized("abc")]
        response_text = json.dumps({
            "answer": "text",
            "citations": [{"note_id": "abc", "display_label": "PR #101"}],
        })
        grounded, _, _ = svc.validate(response_text, artifacts)
        assert grounded[0].display_label == "PR #101"


class TestInlineExtraction:
    """Fallback to inline [note_id] parsing when no structured JSON."""

    def test_inline_note_ids_extracted(self):
        svc = CitationValidator()
        artifacts = [_make_sanitized("abc-123"), _make_sanitized("def-456")]
        response_text = "Auth uses JWT [abc-123] and tokens [def-456]."
        grounded, _, _ = svc.validate(response_text, artifacts)
        assert len(grounded) == 2

    def test_inline_with_ungrounded(self):
        svc = CitationValidator()
        artifacts = [_make_sanitized("abc-123")]
        response_text = "Auth uses JWT [abc-123] and [nonexistent]."
        grounded, dropped, _ = svc.validate(response_text, artifacts)
        assert len(grounded) == 1
        assert len(dropped) == 1
        assert dropped[0].grounding_status == GroundingStatus.DROPPED_UNVERIFIABLE


class TestGroundingRules:
    """Exact note_id match only; no fuzzy matching."""

    def test_exact_match_required(self):
        svc = CitationValidator()
        artifacts = [_make_sanitized("abc-123")]
        response_text = json.dumps({
            "answer": "text",
            "citations": [{"note_id": "abc-123"}],
        })
        grounded, _, _ = svc.validate(response_text, artifacts)
        assert len(grounded) == 1

    def test_partial_match_rejected(self):
        svc = CitationValidator()
        artifacts = [_make_sanitized("abc-123")]
        response_text = json.dumps({
            "answer": "text",
            "citations": [{"note_id": "abc"}],
        })
        grounded, dropped, _ = svc.validate(response_text, artifacts)
        assert len(grounded) == 0
        assert len(dropped) == 1

    def test_case_sensitive(self):
        svc = CitationValidator()
        artifacts = [_make_sanitized("ABC-123")]
        response_text = json.dumps({
            "answer": "text",
            "citations": [{"note_id": "abc-123"}],
        })
        grounded, _, _ = svc.validate(response_text, artifacts)
        assert len(grounded) == 0

    def test_duplicate_citations_deduplicated(self):
        svc = CitationValidator()
        artifacts = [_make_sanitized("abc")]
        response_text = json.dumps({
            "answer": "text",
            "citations": [{"note_id": "abc"}, {"note_id": "abc"}],
        })
        grounded, _, _ = svc.validate(response_text, artifacts)
        assert len(grounded) == 1


class TestMinimumThreshold:
    """Minimum 2 grounded citations; below = grounding failure."""

    def test_two_grounded_passes(self):
        svc = CitationValidator()
        artifacts = [_make_sanitized("a"), _make_sanitized("b")]
        response_text = json.dumps({
            "answer": "text",
            "citations": [{"note_id": "a"}, {"note_id": "b"}],
        })
        grounded, _, _ = svc.validate(response_text, artifacts)
        assert len(grounded) >= 2

    def test_one_grounded_below_threshold(self):
        svc = CitationValidator()
        artifacts = [_make_sanitized("a"), _make_sanitized("b")]
        response_text = json.dumps({
            "answer": "text",
            "citations": [{"note_id": "a"}],
        })
        grounded, _, _ = svc.validate(response_text, artifacts)
        assert len(grounded) == 1
        # Caller checks len(grounded) < 2 for fallback decision

    def test_zero_grounded(self):
        svc = CitationValidator()
        artifacts = [_make_sanitized("a")]
        response_text = json.dumps({
            "answer": "text",
            "citations": [{"note_id": "nonexistent"}],
        })
        grounded, dropped, _ = svc.validate(response_text, artifacts)
        assert len(grounded) == 0
        assert len(dropped) == 1


class TestWarnings:
    """Warnings emitted for dropped citations."""

    def test_warning_on_dropped_citation(self):
        svc = CitationValidator()
        artifacts = [_make_sanitized("a"), _make_sanitized("b")]
        response_text = json.dumps({
            "answer": "text",
            "citations": [{"note_id": "a"}, {"note_id": "b"}, {"note_id": "fake"}],
        })
        _, dropped, warnings = svc.validate(response_text, artifacts)
        assert len(dropped) == 1
        assert any("unverifiable" in w.lower() or "dropped" in w.lower() for w in warnings)

    def test_no_warning_when_all_grounded(self):
        svc = CitationValidator()
        artifacts = [_make_sanitized("a")]
        response_text = json.dumps({
            "answer": "text",
            "citations": [{"note_id": "a"}],
        })
        _, _, warnings = svc.validate(response_text, artifacts)
        assert len(warnings) == 0


class TestEdgeCases:
    """Hostile and edge case inputs."""

    def test_empty_response_text(self):
        svc = CitationValidator()
        artifacts = [_make_sanitized("a")]
        grounded, _, _ = svc.validate("", artifacts)
        assert len(grounded) == 0

    def test_no_citations_in_response(self):
        svc = CitationValidator()
        artifacts = [_make_sanitized("a")]
        response_text = "Just a plain answer with no references."
        grounded, _, _ = svc.validate(response_text, artifacts)
        assert len(grounded) == 0

    def test_malformed_json(self):
        svc = CitationValidator()
        artifacts = [_make_sanitized("a")]
        response_text = '{"answer": "text", "citations": [{"note_id": "a"'
        grounded, _, _ = svc.validate(response_text, artifacts)
        # Falls back to inline parsing
        assert isinstance(grounded, list)

    def test_empty_artifacts_list(self):
        svc = CitationValidator()
        response_text = json.dumps({
            "answer": "text",
            "citations": [{"note_id": "a"}],
        })
        grounded, dropped, _ = svc.validate(response_text, [])
        assert len(grounded) == 0
        assert len(dropped) == 1

    def test_reference_type_defaults_to_note_id(self):
        svc = CitationValidator()
        artifacts = [_make_sanitized("abc")]
        response_text = json.dumps({
            "answer": "text",
            "citations": [{"note_id": "abc"}],
        })
        grounded, _, _ = svc.validate(response_text, artifacts)
        assert grounded[0].reference_type == ReferenceType.NOTE_ID
