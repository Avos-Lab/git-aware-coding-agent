"""Citation validator for query pipeline grounding enforcement.

Extracts citations from LLM synthesis responses and validates each
against retrieved artifact note_ids. Ungrounded citations are dropped
with warnings. Supports structured JSON and inline [note_id] fallback.
"""

from __future__ import annotations

import json
import re

from avos_cli.models.query import (
    GroundedCitation,
    GroundingStatus,
    ReferenceType,
    SanitizedArtifact,
)
from avos_cli.utils.logger import get_logger

_log = get_logger("citation_validator")

_INLINE_CITATION_PATTERN = re.compile(r"\[([a-zA-Z0-9_\-]+)\]")

_MIN_GROUNDED_THRESHOLD = 2


class CitationValidator:
    """Validates LLM synthesis citations against retrieved artifacts.

    Grounding rule: exact note_id match only. No fuzzy matching.
    Minimum threshold: 2 grounded citations for synthesis acceptance.
    """

    def validate(
        self,
        response_text: str,
        artifacts: list[SanitizedArtifact],
    ) -> tuple[list[GroundedCitation], list[GroundedCitation], list[str]]:
        """Validate citations in LLM response against retrieved artifacts.

        Args:
            response_text: Raw LLM response text (may contain JSON or inline refs).
            artifacts: The sanitized artifacts that were sent to the LLM.

        Returns:
            Tuple of (grounded_citations, dropped_citations, warnings).
        """
        valid_ids = {art.note_id for art in artifacts}
        raw_citations = self._extract_citations(response_text)

        seen: set[str] = set()
        grounded: list[GroundedCitation] = []
        dropped: list[GroundedCitation] = []
        warnings: list[str] = []

        for note_id, display_label in raw_citations:
            if note_id in seen:
                continue
            seen.add(note_id)

            if note_id in valid_ids:
                grounded.append(
                    GroundedCitation(
                        note_id=note_id,
                        display_label=display_label or note_id,
                        reference_type=ReferenceType.NOTE_ID,
                        grounding_status=GroundingStatus.GROUNDED,
                    )
                )
            else:
                dropped.append(
                    GroundedCitation(
                        note_id=note_id,
                        display_label=display_label or note_id,
                        reference_type=ReferenceType.NOTE_ID,
                        grounding_status=GroundingStatus.DROPPED_UNVERIFIABLE,
                    )
                )

        if dropped:
            warnings.append(
                f"{len(dropped)} citation(s) dropped as unverifiable: "
                f"{', '.join(c.note_id for c in dropped)}"
            )

        return grounded, dropped, warnings

    def _extract_citations(
        self, response_text: str
    ) -> list[tuple[str, str | None]]:
        """Extract citation note_ids from response, preferring structured JSON.

        Returns:
            List of (note_id, display_label_or_none) tuples.
        """
        structured = self._try_structured_extraction(response_text)
        if structured is not None:
            return structured
        return self._inline_extraction(response_text)

    def _try_structured_extraction(
        self, response_text: str
    ) -> list[tuple[str, str | None]] | None:
        """Try to parse citations from JSON structure in response."""
        cleaned = re.sub(r"^```(?:json)?\s*\n?", "", response_text.strip())
        cleaned = re.sub(r"\n?```\s*$", "", cleaned)
        try:
            data = json.loads(cleaned)
        except (json.JSONDecodeError, TypeError):
            return None

        if not isinstance(data, dict):
            return None

        citations_raw = data.get("citations")
        if not isinstance(citations_raw, list):
            return None

        results: list[tuple[str, str | None]] = []
        for item in citations_raw:
            if isinstance(item, dict) and "note_id" in item:
                note_id = str(item["note_id"])
                display_label = item.get("display_label")
                results.append((note_id, display_label))

        return results if results else None

    def _inline_extraction(
        self, response_text: str
    ) -> list[tuple[str, str | None]]:
        """Fallback: extract [note_id] patterns from plain text."""
        matches = _INLINE_CITATION_PATTERN.findall(response_text)
        return [(m, None) for m in matches]
