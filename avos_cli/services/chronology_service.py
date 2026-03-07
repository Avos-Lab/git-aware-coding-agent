"""Chronology service for deterministic timeline ordering.

Parses ISO 8601 timestamps, normalizes to UTC, and sorts artifacts
using a stable deterministic comparator for the history command pipeline.
"""

from __future__ import annotations

from datetime import datetime, timezone

from avos_cli.models.query import RetrievedArtifact
from avos_cli.utils.logger import get_logger

_log = get_logger("chronology")

_MAX_DATETIME = datetime(9999, 12, 31, 23, 59, 59, tzinfo=timezone.utc)


class ChronologyService:
    """Sorts artifacts chronologically with deterministic tie-breakers.

    Sort contract: timestamp ASC, rank ASC, note_id ASC.
    Invalid/null timestamps are sorted last.
    """

    def sort(self, artifacts: list[RetrievedArtifact]) -> list[RetrievedArtifact]:
        """Sort artifacts in chronological order.

        Args:
            artifacts: Artifacts to sort (not mutated).

        Returns:
            New list sorted by (timestamp ASC, rank ASC, note_id ASC).
        """
        return sorted(artifacts, key=self._sort_key)

    def _sort_key(self, art: RetrievedArtifact) -> tuple[datetime, int, str]:
        """Build deterministic sort key for an artifact."""
        ts = self._parse_timestamp(art.created_at)
        return (ts, art.rank, art.note_id)

    def _parse_timestamp(self, value: str) -> datetime:
        """Parse ISO 8601 timestamp to UTC datetime.

        Invalid or empty values return _MAX_DATETIME (sorted last).
        Naive datetimes are assumed UTC.
        """
        if not value or not value.strip():
            return _MAX_DATETIME

        cleaned = value.strip()

        for fmt in (
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%dT%H:%M:%SZ",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d",
        ):
            try:
                dt = datetime.strptime(cleaned, fmt)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.astimezone(timezone.utc)
            except ValueError:
                continue

        _log.warning("Unparseable timestamp '%s', sorting last", value)
        return _MAX_DATETIME
