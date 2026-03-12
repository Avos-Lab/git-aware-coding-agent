"""Query fallback formatter for deterministic raw-result rendering.

Produces approved-template fallback output when LLM synthesis is
unavailable, ungrounded, or blocked by safety policy. Uses only
sanitized artifacts -- never raw unsanitized content.
"""

from __future__ import annotations

from avos_cli.models.query import FallbackReason, SanitizedArtifact
from avos_cli.services.chronology_service import ChronologyService

_ASK_MAX_FALLBACK_ITEMS = 3

_REASON_LABELS: dict[FallbackReason, str] = {
    FallbackReason.LLM_UNAVAILABLE: "LLM synthesis unavailable",
    FallbackReason.GROUNDING_FAILED: "Citation grounding verification failed",
    FallbackReason.SAFETY_BLOCK: "Blocked by safety/redaction checks",
    FallbackReason.BUDGET_EXHAUSTED: "Context budget exhausted",
}

_EPOCH = "1970-01-01T00:00:00Z"


class QueryFallbackFormatter:
    """Formats deterministic fallback output for ask and history commands.

    Ask fallback: top 3 sanitized items by rank contract.
    History fallback: all items in chronological order.
    """

    def __init__(self) -> None:
        self._chrono = ChronologyService()

    def format_ask_fallback(
        self,
        artifacts: list[SanitizedArtifact],
        reason: FallbackReason,
    ) -> str:
        """Format ask-mode fallback output.

        Args:
            artifacts: Sanitized artifacts (pre-sorted by budget service or raw).
            reason: Why fallback was triggered.

        Returns:
            Formatted fallback string with header and up to 3 items.
        """
        label = _REASON_LABELS.get(reason, "Synthesis fallback")
        header = f"Answer unavailable due to {label.lower()}. Top sanitized evidence:"

        if not artifacts:
            return f"{header}\n\nNo matching evidence found."

        sorted_arts = sorted(artifacts, key=self._ask_sort_key)
        selected = sorted_arts[:_ASK_MAX_FALLBACK_ITEMS]

        lines = [header, ""]
        for art in selected:
            lines.append(self._format_item(art))
            lines.append("---")

        return "\n".join(lines)

    def format_history_fallback(
        self,
        artifacts: list[SanitizedArtifact],
        reason: FallbackReason,
    ) -> str:
        """Format history-mode fallback output.

        Args:
            artifacts: Sanitized artifacts.
            reason: Why fallback was triggered.

        Returns:
            Formatted fallback string with header and chronological items.
        """
        label = _REASON_LABELS.get(reason, "Synthesis fallback")
        header = f"Timeline unavailable due to {label.lower()}. Sanitized chronological evidence:"

        if not artifacts:
            return f"{header}\n\nNo matching evidence found."

        sorted_arts = sorted(
            artifacts,
            key=lambda art: (art.created_at if art.created_at else _EPOCH, art.note_id),
        )

        lines = [header, ""]
        for art in sorted_arts:
            lines.append(self._format_item(art))
            lines.append("---")

        return "\n".join(lines)

    def _format_item(self, art: SanitizedArtifact) -> str:
        """Format a single fallback item block."""
        return (
            f"[{art.note_id}] ({art.created_at})\n"
            f"{art.content}"
        )

    def _ask_sort_key(self, art: SanitizedArtifact) -> tuple[int, str, str]:
        """Ask fallback sort: rank ASC, created_at DESC, note_id ASC."""
        created_at = art.created_at if art.created_at else _EPOCH
        inverted_date = "".join(chr(0xFFFF - ord(c)) for c in created_at)
        return (art.rank, inverted_date, art.note_id)
