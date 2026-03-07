"""Sanitization service for query pipeline data governance.

Detects and redacts secrets, credentials, PII, and prompt-injection
markers from retrieved artifacts before LLM synthesis or fallback output.
Produces typed redaction tokens and a deterministic confidence score.
"""

from __future__ import annotations

import re

from avos_cli.models.query import (
    RetrievedArtifact,
    SanitizationResult,
    SanitizedArtifact,
)
from avos_cli.utils.logger import get_logger

_log = get_logger("sanitization")

# --- Pattern definitions ---

_API_KEY_PATTERNS: list[tuple[re.Pattern[str], str, str]] = [
    (re.compile(r"sk_[a-zA-Z0-9_]{10,}"), "[REDACTED_API_KEY]", "api_key"),
    (re.compile(r"AKIA[0-9A-Z]{16}"), "[REDACTED_API_KEY]", "api_key"),
]

_TOKEN_PATTERNS: list[tuple[re.Pattern[str], str, str]] = [
    (re.compile(r"ghp_[a-zA-Z0-9]{10,}"), "[REDACTED_TOKEN]", "token"),
    (re.compile(r"gho_[a-zA-Z0-9]{10,}"), "[REDACTED_TOKEN]", "token"),
    (re.compile(r"ghs_[a-zA-Z0-9]{10,}"), "[REDACTED_TOKEN]", "token"),
    (re.compile(r"ghu_[a-zA-Z0-9]{10,}"), "[REDACTED_TOKEN]", "token"),
    (re.compile(r"github_pat_[a-zA-Z0-9_]{10,}"), "[REDACTED_TOKEN]", "token"),
    (re.compile(r"Bearer\s+[A-Za-z0-9\-._~+/]+=*", re.IGNORECASE), "[REDACTED_TOKEN]", "token"),
]

_CREDENTIAL_PATTERNS: list[tuple[re.Pattern[str], str, str]] = [
    (re.compile(r'(?:password|passwd|pwd)\s*[=:]\s*["\']?[^\s"\']{4,}["\']?', re.IGNORECASE), "[REDACTED_CREDENTIAL]", "credential"),
    (re.compile(r'(?:secret|api_secret)\s*[=:]\s*["\']?[^\s"\']{4,}["\']?', re.IGNORECASE), "[REDACTED_CREDENTIAL]", "credential"),
]

_PRIVATE_KEY_PATTERN = re.compile(
    r"-----BEGIN\s+(?:RSA\s+)?PRIVATE\s+KEY-----.*?-----END\s+(?:RSA\s+)?PRIVATE\s+KEY-----",
    re.DOTALL,
)

_PII_PATTERNS: list[tuple[re.Pattern[str], str, str]] = [
    (re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"), "[REDACTED_PII]", "pii"),
]

_INJECTION_MARKERS: list[re.Pattern[str]] = [
    re.compile(r"ignore\s+(?:all\s+)?previous\s+instructions", re.IGNORECASE),
    re.compile(r"<\|system\|>", re.IGNORECASE),
    re.compile(r"\[SYSTEM\]\s*:", re.IGNORECASE),
    re.compile(r"you\s+are\s+now\s+a\s+different", re.IGNORECASE),
    re.compile(r"override\s+(?:the\s+)?policy", re.IGNORECASE),
    re.compile(r"reveal\s+(?:all\s+)?secrets", re.IGNORECASE),
    re.compile(r"disregard\s+(?:all\s+)?(?:prior|previous)", re.IGNORECASE),
]

_ALL_REDACTION_PATTERNS = _API_KEY_PATTERNS + _TOKEN_PATTERNS + _CREDENTIAL_PATTERNS + _PII_PATTERNS

_BASE_CONFIDENCE = 100
_PATTERN_DETECTION_WEIGHT = 40
_STRUCTURED_FIELD_WEIGHT = 25
_PII_WEIGHT = 20
_INJECTION_PENALTY_WEIGHT = 40


class SanitizationService:
    """Sanitizes retrieved artifacts by redacting secrets, credentials, and PII.

    Produces a confidence score reflecting sanitization completeness.
    Deterministic: same input always yields same output and score.
    """

    def sanitize(self, artifacts: list[RetrievedArtifact]) -> SanitizationResult:
        """Sanitize a list of retrieved artifacts.

        Args:
            artifacts: Raw artifacts from Memory API search.

        Returns:
            SanitizationResult with sanitized artifacts, redaction metadata,
            and confidence score (0-100).
        """
        if not artifacts:
            return SanitizationResult(
                artifacts=[],
                redaction_applied=False,
                redaction_types=[],
                confidence_score=100,
            )

        sanitized_list: list[SanitizedArtifact] = []
        all_redaction_types: set[str] = set()
        any_redaction = False
        total_injection_hits = 0

        for art in artifacts:
            content, redaction_types, had_redaction = self._redact_content(art.content)
            if had_redaction:
                any_redaction = True
                all_redaction_types.update(redaction_types)

            injection_hits = self._count_injection_markers(content)
            total_injection_hits += injection_hits

            content, injection_redacted = self._redact_injection_markers(content)
            if injection_redacted:
                any_redaction = True
                all_redaction_types.add("injection")
                redaction_types.add("injection")

            sanitized_list.append(
                SanitizedArtifact(
                    note_id=art.note_id,
                    content=content,
                    created_at=art.created_at,
                    rank=art.rank,
                    source_type=art.source_type,
                    display_ref=art.display_ref,
                    redaction_applied=had_redaction or injection_redacted,
                    redaction_types=sorted(redaction_types),
                )
            )

        confidence = self._compute_confidence(
            any_redaction, all_redaction_types, total_injection_hits
        )

        return SanitizationResult(
            artifacts=sanitized_list,
            redaction_applied=any_redaction,
            redaction_types=sorted(all_redaction_types),
            confidence_score=confidence,
        )

    def _redact_content(self, content: str) -> tuple[str, set[str], bool]:
        """Apply all redaction patterns to content.

        Returns:
            Tuple of (redacted_content, redaction_type_set, had_any_redaction).
        """
        redacted = content
        types: set[str] = set()
        had_redaction = False

        # Private key blocks first (multiline)
        if _PRIVATE_KEY_PATTERN.search(redacted):
            redacted = _PRIVATE_KEY_PATTERN.sub("[REDACTED_PRIVATE_KEY]", redacted)
            types.add("private_key")
            had_redaction = True

        for pattern, replacement, rtype in _ALL_REDACTION_PATTERNS:
            if pattern.search(redacted):
                redacted = pattern.sub(replacement, redacted)
                types.add(rtype)
                had_redaction = True

        return redacted, types, had_redaction

    def _count_injection_markers(self, content: str) -> int:
        """Count prompt-injection marker hits in content."""
        count = 0
        for marker in _INJECTION_MARKERS:
            if marker.search(content):
                count += 1
        return count

    def _redact_injection_markers(self, content: str) -> tuple[str, bool]:
        """Remove prompt-injection markers from content.

        Returns:
            Tuple of (redacted_content, had_any_redaction).
        """
        redacted = content
        had_redaction = False
        for marker in _INJECTION_MARKERS:
            if marker.search(redacted):
                redacted = marker.sub("[REDACTED_INJECTION]", redacted)
                had_redaction = True
        return redacted, had_redaction

    def _compute_confidence(
        self,
        any_redaction: bool,
        redaction_types: set[str],
        injection_hits: int,
    ) -> int:
        """Compute deterministic sanitization confidence score (0-100).

        Scoring uses the defined weight constants to produce meaningful
        differentiation. Injection markers are heavily penalized since
        they indicate potential prompt injection attempts.

        - Start at 100 (base).
        - Deduct _PATTERN_DETECTION_WEIGHT for secrets/credentials found.
        - Deduct _PII_WEIGHT for PII found.
        - Deduct _INJECTION_PENALTY_WEIGHT per injection marker (capped).
        """
        score = _BASE_CONFIDENCE

        if any_redaction:
            if "api_key" in redaction_types or "token" in redaction_types:
                score -= _PATTERN_DETECTION_WEIGHT
            if "private_key" in redaction_types:
                score -= _PATTERN_DETECTION_WEIGHT
            if "credential" in redaction_types:
                score -= _STRUCTURED_FIELD_WEIGHT
            if "pii" in redaction_types:
                score -= _PII_WEIGHT

        if injection_hits > 0:
            penalty = min(injection_hits * _INJECTION_PENALTY_WEIGHT, 60)
            score -= penalty

        return max(0, min(100, score))
