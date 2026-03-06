"""Ingest lock manager for preventing concurrent ingest runs.

Uses a JSON lock file (.avos/ingest.lock) containing PID and timestamp.
Supports stale-lock detection via PID liveness check and configurable
time threshold (default 1 hour).
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from avos_cli.exceptions import IngestLockError
from avos_cli.utils.logger import get_logger

_log = get_logger("config.lock")

_LOCK_FILENAME = "ingest.lock"
_DEFAULT_STALE_THRESHOLD = 3600  # 1 hour


class IngestLockManager:
    """Manages the ingest lock file for single-process exclusion.

    Args:
        avos_dir: Path to the .avos directory.
        stale_threshold_seconds: Seconds after which a lock with a dead PID
            is considered stale and can be broken.
    """

    def __init__(
        self,
        avos_dir: Path,
        stale_threshold_seconds: int = _DEFAULT_STALE_THRESHOLD,
    ) -> None:
        self._lock_path = avos_dir / _LOCK_FILENAME
        self._stale_threshold = stale_threshold_seconds

    def acquire(self) -> None:
        """Acquire the ingest lock.

        Raises:
            IngestLockError: If another live process holds the lock.
        """
        if self._lock_path.exists():
            existing = self._read_lock()
            if existing is None:
                _log.warning("Removing corrupt lock file: %s", self._lock_path)
                self._lock_path.unlink(missing_ok=True)
            elif self._is_stale(existing):
                _log.warning(
                    "Breaking stale lock (pid=%d, age=%.0fs)",
                    int(existing["pid"]),
                    time.time() - float(existing["acquired_at"]),
                )
                self._lock_path.unlink(missing_ok=True)
            else:
                pid = int(existing["pid"])
                raise IngestLockError(
                    f"Ingest lock held by pid {pid}",
                    holder_pid=pid,
                )

        self._write_lock()

    def release(self) -> None:
        """Release the ingest lock. Safe to call even if not held."""
        self._lock_path.unlink(missing_ok=True)

    def is_locked(self) -> bool:
        """Check whether the lock file exists."""
        return self._lock_path.exists()

    def __enter__(self) -> IngestLockManager:
        self.acquire()
        return self

    def __exit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        self.release()

    def _write_lock(self) -> None:
        """Write the lock file with current PID and timestamp."""
        data = {"pid": os.getpid(), "acquired_at": time.time()}
        self._lock_path.write_text(json.dumps(data), encoding="utf-8")

    def _read_lock(self) -> dict[str, int | float] | None:
        """Read and parse the lock file. Returns None if corrupt."""
        try:
            content = self._lock_path.read_text(encoding="utf-8")
            if not content.strip():
                return None
            raw = json.loads(content)
            if not isinstance(raw, dict):
                return None
            if "pid" not in raw or "acquired_at" not in raw:
                return None
            return {"pid": int(raw["pid"]), "acquired_at": float(raw["acquired_at"])}
        except (json.JSONDecodeError, OSError, ValueError, TypeError):
            return None

    def _is_stale(self, lock_data: dict[str, int | float]) -> bool:
        """Determine if a lock is stale (old AND holder PID is dead).

        A lock is stale only when BOTH conditions are met:
        1. The lock age exceeds the stale threshold.
        2. The holder PID is no longer alive.
        """
        age = time.time() - float(lock_data["acquired_at"])
        if age < self._stale_threshold:
            return False
        return not self._pid_alive(int(lock_data["pid"]))

    @staticmethod
    def _pid_alive(pid: int) -> bool:
        """Check if a process with the given PID is alive."""
        try:
            os.kill(pid, 0)
            return True
        except (OSError, ProcessLookupError):
            return False
