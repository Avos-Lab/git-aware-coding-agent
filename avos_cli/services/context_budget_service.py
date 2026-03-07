"""Context budget service for query pipeline artifact packing.

Applies deterministic ranking, truncation, and hard caps to sanitized
artifacts before LLM synthesis. Ensures stable ordering across runs
and preserves citation metadata for downstream grounding.
"""

from __future__ import annotations

from avos_cli.models.query import BudgetResult, SanitizedArtifact
from avos_cli.utils.logger import get_logger

_log = get_logger("context_budget")

_ASK_MAX_ARTIFACTS = 6
_ASK_EXCERPT_CAP = 800
_HISTORY_MAX_ARTIFACTS = 10
_HISTORY_EXCERPT_CAP = 600

_EPOCH = "1970-01-01T00:00:00Z"
_MAX_RANK = 999999999


class ContextBudgetService:
    """Packs sanitized artifacts within model context budget.

    Sorting contract: rank ASC, created_at DESC, note_id ASC.
    Null rank -> max int (sorted last). Empty created_at -> epoch (sorted last for DESC).
    """

    def pack(
        self,
        artifacts: list[SanitizedArtifact],
        mode: str,
    ) -> BudgetResult:
        """Rank, sort, truncate, and cap artifacts for synthesis.

        Args:
            artifacts: Sanitized artifacts to pack.
            mode: 'ask' or 'history' -- determines caps and excerpt limits.

        Returns:
            BudgetResult with included/excluded artifacts and metadata.
        """
        if mode == "ask":
            max_count = _ASK_MAX_ARTIFACTS
            excerpt_cap = _ASK_EXCERPT_CAP
        else:
            max_count = _HISTORY_MAX_ARTIFACTS
            excerpt_cap = _HISTORY_EXCERPT_CAP

        sorted_arts = sorted(artifacts, key=self._sort_key)

        included_raw = sorted_arts[:max_count]
        excluded_raw = sorted_arts[max_count:]

        included: list[SanitizedArtifact] = []
        truncation_flags: dict[str, bool] = {}

        for art in included_raw:
            truncated_content, was_truncated = self._truncate(art.content, excerpt_cap)
            truncation_flags[art.note_id] = was_truncated
            if was_truncated:
                included.append(
                    SanitizedArtifact(
                        note_id=art.note_id,
                        content=truncated_content,
                        created_at=art.created_at,
                        rank=art.rank,
                        source_type=art.source_type,
                        display_ref=art.display_ref,
                        redaction_applied=art.redaction_applied,
                        redaction_types=art.redaction_types,
                    )
                )
            else:
                truncation_flags[art.note_id] = False
                included.append(art)

        return BudgetResult(
            included=included,
            excluded=list(excluded_raw),
            truncation_flags=truncation_flags,
            included_count=len(included),
            excluded_count=len(excluded_raw),
        )

    def _sort_key(self, art: SanitizedArtifact) -> tuple[int, str, str]:
        """Deterministic sort key: rank ASC, created_at DESC, note_id ASC.

        For DESC on created_at, we negate by using a complement string trick:
        reverse the sort by prepending a character that inverts ordering.
        """
        rank = art.rank if art.rank < _MAX_RANK else _MAX_RANK
        created_at = art.created_at if art.created_at else _EPOCH
        # For descending created_at: invert by negating character ordinals
        inverted_date = "".join(chr(0xFFFF - ord(c)) for c in created_at)
        return (rank, inverted_date, art.note_id)

    def _truncate(self, content: str, cap: int) -> tuple[str, bool]:
        """Truncate content to cap with '...' marker if needed."""
        if len(content) <= cap:
            return content, False
        return content[:cap] + "...", True
