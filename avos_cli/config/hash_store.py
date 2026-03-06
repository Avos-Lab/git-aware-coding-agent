"""Ingest hash store for artifact deduplication.

Manages .avos/ingest_hashes.json which maps content hashes to metadata.
Used by the ingest command to skip already-stored artifacts on re-runs.
Each entry stores artifact_type, source_id, and stored_at timestamp.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

from avos_cli.config.state import atomic_write
from avos_cli.utils.logger import get_logger

_log = get_logger("config.hash_store")

_HASH_STORE_FILENAME = "ingest_hashes.json"


class IngestHashStore:
    """Manages the content hash store for ingest deduplication.

    Args:
        avos_dir: Path to the .avos directory.
    """

    def __init__(self, avos_dir: Path) -> None:
        self._path = avos_dir / _HASH_STORE_FILENAME
        self._store: dict[str, dict[str, str]] = {}

    def load(self) -> None:
        """Load the hash store from disk. Quarantines corrupt files."""
        if not self._path.exists():
            self._store = {}
            return

        try:
            content = self._path.read_text(encoding="utf-8")
            if not content.strip():
                self._store = {}
                return
            data = json.loads(content)
            if not isinstance(data, dict):
                _log.warning("Hash store is not a dict, treating as corrupt")
                self._quarantine()
                self._store = {}
                return
            self._store = data
        except (json.JSONDecodeError, UnicodeDecodeError):
            _log.warning("Corrupt hash store, quarantining: %s", self._path)
            self._quarantine()
            self._store = {}

    def save(self) -> None:
        """Persist the hash store to disk atomically."""
        content = json.dumps(self._store, indent=2, sort_keys=True)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(self._path, content)

    def contains(self, content_hash: str) -> bool:
        """Check if a content hash is already stored."""
        return content_hash in self._store

    def add(self, content_hash: str, artifact_type: str, source_id: str) -> None:
        """Add a content hash with metadata. Idempotent for duplicates."""
        if content_hash in self._store:
            return
        self._store[content_hash] = {
            "artifact_type": artifact_type,
            "source_id": source_id,
            "stored_at": datetime.now(tz=timezone.utc).isoformat(),
        }

    def get_entry(self, content_hash: str) -> dict[str, str] | None:
        """Get the metadata entry for a hash, or None if not found."""
        return self._store.get(content_hash)

    def count(self) -> int:
        """Return the number of stored hashes."""
        return len(self._store)

    def _quarantine(self) -> None:
        """Move a corrupt hash store file to a .corrupt backup."""
        ts = int(time.time())
        corrupt_path = self._path.with_suffix(f"{self._path.suffix}.corrupt.{ts}")
        try:
            self._path.rename(corrupt_path)
            _log.warning("Quarantined: %s -> %s", self._path, corrupt_path)
        except OSError as e:
            _log.error("Failed to quarantine %s: %s", self._path, e)
