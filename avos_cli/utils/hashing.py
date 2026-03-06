"""Content hashing for artifact idempotency.

Provides deterministic SHA-256 hashing of string content.
Used by artifact builders to generate content_hash() values
that enable duplicate detection during ingestion.
"""

from __future__ import annotations

import hashlib


def content_hash(data: str) -> str:
    """Compute a deterministic SHA-256 hex digest of the given string.

    Args:
        data: The string content to hash.

    Returns:
        64-character lowercase hex string of the SHA-256 digest.
    """
    return hashlib.sha256(data.encode("utf-8")).hexdigest()
