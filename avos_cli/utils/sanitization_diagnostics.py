"""Human-readable and JSON diagnostics when sanitization blocks LLM synthesis.

Used when ``SanitizationResult.confidence_score`` is below the ask/history
threshold so users understand why synthesis was skipped and how the score
was affected.
"""

from __future__ import annotations

from typing import Any

from avos_cli.models.query import SanitizationResult

_REDACTION_LABELS: dict[str, str] = {
    "api_key": "API key-like strings (e.g. sk_…, AWS AKIA…)",
    "token": "Bearer tokens or GitHub PAT-style tokens",
    "credential": "password=/secret= style credential fields",
    "private_key": "PEM private key blocks",
    "pii": "email-shaped personal identifiers",
    "injection": "prompt-injection-like phrases (redacted as [REDACTED_INJECTION])",
}


def explain_sanitization_gate(
    result: SanitizationResult,
    threshold: int,
) -> tuple[str, list[str], dict[str, Any]]:
    """Build headline, explanatory lines, and a JSON fragment for tooling.

    Args:
        result: Aggregate sanitization outcome for the retrieved artifacts.
        threshold: Minimum confidence required to proceed to LLM synthesis.

    Returns:
        (headline for print_warning, detail lines for print_info,
         dict to merge into JSON ``data``, e.g. ``{"sanitization": {...}}``).
    """
    score = result.confidence_score
    types = list(result.redaction_types)

    headline = (
        f"Sanitization confidence is {score}/100 "
        f"(minimum {threshold} required for LLM synthesis). "
        "Showing sanitized evidence only, not an LLM summary."
    )

    lines: list[str] = [
        "Why: Retrieved memory matched patterns we treat as sensitive or unsafe to "
        "summarize (API keys, tokens, credentials, PEM private keys, email-shaped PII, "
        "or prompt-injection-like text). Matching spans were replaced with "
        "[REDACTED_*] placeholders. The confidence score reflects estimated remaining "
        "risk after redaction; when it is below the threshold we skip synthesis.",
    ]

    if types:
        described = [_REDACTION_LABELS.get(t, t.replace("_", " ")) for t in types]
        lines.append("Categories flagged across retrieved snippets: " + "; ".join(described) + ".")
    else:
        lines.append(
            "No aggregate redaction category list was recorded (unusual); "
            "the low score may still reflect injection-pattern penalties."
        )

    if result.redaction_applied:
        lines.append(
            "At least one snippet had content redacted before display; "
            "look for [REDACTED_API_KEY], [REDACTED_TOKEN], etc. in the evidence."
        )

    json_fragment: dict[str, Any] = {
        "sanitization": {
            "blocked_synthesis": True,
            "confidence_score": score,
            "required_minimum_confidence": threshold,
            "redaction_applied": result.redaction_applied,
            "redaction_types": types,
            "fallback_reason": "safety_block",
        }
    }

    return headline, lines, json_fragment
