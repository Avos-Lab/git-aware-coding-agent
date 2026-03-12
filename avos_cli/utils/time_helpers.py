"""Time utilities for date calculations and TTL checks.

Provides helpers for computing date windows (e.g. "180 days ago"),
checking TTL expiry, and parsing ISO 8601 timestamps.
All datetime operations use UTC.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone


def days_ago(n: int) -> datetime:
    """Return a UTC datetime representing N days before now.

    Args:
        n: Number of days to subtract from the current time.

    Returns:
        UTC-aware datetime N days in the past.
    """
    return datetime.now(tz=timezone.utc) - timedelta(days=n)


def is_within_ttl(timestamp_iso: str, hours: int) -> bool:
    """Check whether an ISO 8601 timestamp is within the last N hours.

    Args:
        timestamp_iso: ISO 8601 formatted timestamp string.
        hours: TTL window in hours.

    Returns:
        True if the timestamp is within the last `hours` hours.
    """
    dt = parse_iso8601(timestamp_iso)
    cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=hours)
    return dt >= cutoff


def parse_iso8601(timestamp: str) -> datetime:
    """Parse an ISO 8601 timestamp string into a UTC-aware datetime.

    Handles 'Z' suffix, timezone offsets, and naive timestamps
    (which are assumed to be UTC).

    Args:
        timestamp: ISO 8601 formatted string.

    Returns:
        Timezone-aware datetime in UTC.
    """
    cleaned = timestamp.replace("Z", "+00:00")
    dt = datetime.fromisoformat(cleaned)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt
