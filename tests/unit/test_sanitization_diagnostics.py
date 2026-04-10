"""Tests for sanitization gate user-facing diagnostics."""

from __future__ import annotations

from avos_cli.models.query import SanitizationResult
from avos_cli.utils.sanitization_diagnostics import explain_sanitization_gate


def test_explain_includes_score_and_threshold():
    result = SanitizationResult(
        artifacts=[],
        redaction_applied=True,
        redaction_types=["api_key", "pii"],
        confidence_score=30,
    )
    headline, lines, payload = explain_sanitization_gate(result, 70)
    assert "30/100" in headline
    assert "70" in headline
    assert any("API key" in line for line in lines)
    assert payload["sanitization"]["confidence_score"] == 30
    assert payload["sanitization"]["required_minimum_confidence"] == 70
    assert payload["sanitization"]["redaction_types"] == ["api_key", "pii"]
    assert payload["sanitization"]["blocked_synthesis"] is True


def test_explain_empty_redaction_types_branch():
    result = SanitizationResult(
        artifacts=[],
        redaction_applied=False,
        redaction_types=[],
        confidence_score=50,
    )
    _, lines, _ = explain_sanitization_gate(result, 70)
    assert any("No aggregate redaction category" in line for line in lines)
