"""Time utilities for date calculations and TTL checks.

Provides helpers for computing date windows (e.g. "180 days ago"),
checking TTL expiry, parsing ISO 8601 timestamps, and artifact
active-window filtering with parse-audit support.
All datetime operations use UTC.
"""

from __future__ import annotations

import logging
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


_audit_log = logging.getLogger("avos_cli.ttl_parse_audit")


def is_artifact_active(
    timestamp_str: str,
    ttl_hours: int = 24,
    *,
    artifact_id: str = "",
    command_context: str = "",
) -> bool:
    """Check whether an artifact timestamp is within the active TTL window.

    Wraps is_within_ttl with structured parse-audit logging on failure.
    On parse error the artifact is excluded from the active set and a
    parse-audit record is emitted (architecture Section 5.3 mandate).

    Args:
        timestamp_str: ISO 8601 formatted timestamp from the artifact.
        ttl_hours: Active window in hours (default 24).
        artifact_id: Identifier for the artifact (for audit trail).
        command_context: Calling command name ('team' or 'conflicts').

    Returns:
        True if the artifact is within the active window, False otherwise
        (including on parse failure).
    """
    try:
        return is_within_ttl(timestamp_str, ttl_hours)
    except (ValueError, TypeError, OverflowError) as exc:
        _audit_log.warning(
            "TTL parse-audit: artifact=%s raw_timestamp=%r "
            "error_category=%s command=%s",
            artifact_id,
            timestamp_str,
            type(exc).__name__,
            command_context,
        )
        return False
