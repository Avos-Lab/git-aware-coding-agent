"""Tests for ingest lock manager.

Covers acquire, release, stale-break, PID liveness check,
concurrent lock rejection, and corrupt lock file handling.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from avos_cli.config.lock import IngestLockManager
from avos_cli.exceptions import IngestLockError


@pytest.fixture()
def avos_dir(tmp_path: Path) -> Path:
    """Create .avos directory."""
    d = tmp_path / ".avos"
    d.mkdir()
    return d


@pytest.fixture()
def lock_mgr(avos_dir: Path) -> IngestLockManager:
    """Lock manager with default 1-hour stale threshold."""
    return IngestLockManager(avos_dir)


class TestAcquire:
    def test_acquire_creates_lock_file(self, lock_mgr: IngestLockManager, avos_dir: Path):
        lock_mgr.acquire()
        lock_path = avos_dir / "ingest.lock"
        assert lock_path.exists()

    def test_lock_file_contains_pid_and_timestamp(
        self, lock_mgr: IngestLockManager, avos_dir: Path
    ):
        lock_mgr.acquire()
        data = json.loads((avos_dir / "ingest.lock").read_text())
        assert data["pid"] == os.getpid()
        assert "acquired_at" in data
        assert isinstance(data["acquired_at"], float)

    def test_acquire_twice_raises(self, lock_mgr: IngestLockManager):
        lock_mgr.acquire()
        with pytest.raises(IngestLockError) as exc_info:
            lock_mgr.acquire()
        assert exc_info.value.holder_pid == os.getpid()

    def test_acquire_fails_when_another_process_holds_lock(
        self, avos_dir: Path
    ):
        lock_data = {"pid": os.getpid(), "acquired_at": time.time()}
        (avos_dir / "ingest.lock").write_text(json.dumps(lock_data))

        mgr2 = IngestLockManager(avos_dir)
        with pytest.raises(IngestLockError):
            mgr2.acquire()


class TestRelease:
    def test_release_removes_lock_file(self, lock_mgr: IngestLockManager, avos_dir: Path):
        lock_mgr.acquire()
        lock_mgr.release()
        assert not (avos_dir / "ingest.lock").exists()

    def test_release_without_acquire_is_safe(self, lock_mgr: IngestLockManager):
        lock_mgr.release()

    def test_double_release_is_safe(self, lock_mgr: IngestLockManager):
        lock_mgr.acquire()
        lock_mgr.release()
        lock_mgr.release()


class TestStaleBreak:
    def test_stale_lock_is_broken(self, avos_dir: Path):
        """A lock older than stale_threshold_seconds with a dead PID is broken."""
        stale_data = {"pid": 999999999, "acquired_at": time.time() - 7200}
        (avos_dir / "ingest.lock").write_text(json.dumps(stale_data))

        mgr = IngestLockManager(avos_dir, stale_threshold_seconds=3600)
        mgr.acquire()
        assert (avos_dir / "ingest.lock").exists()
        data = json.loads((avos_dir / "ingest.lock").read_text())
        assert data["pid"] == os.getpid()

    def test_fresh_lock_with_dead_pid_not_broken(self, avos_dir: Path):
        """A recent lock (within threshold) is NOT broken even if PID is dead."""
        fresh_data = {"pid": 999999999, "acquired_at": time.time()}
        (avos_dir / "ingest.lock").write_text(json.dumps(fresh_data))

        mgr = IngestLockManager(avos_dir, stale_threshold_seconds=3600)
        with pytest.raises(IngestLockError):
            mgr.acquire()

    def test_old_lock_with_live_pid_not_broken(self, avos_dir: Path):
        """A lock held by a live process is NOT broken even if old."""
        old_data = {"pid": os.getpid(), "acquired_at": time.time() - 7200}
        (avos_dir / "ingest.lock").write_text(json.dumps(old_data))

        mgr = IngestLockManager(avos_dir, stale_threshold_seconds=3600)
        with pytest.raises(IngestLockError):
            mgr.acquire()


class TestCorruptLock:
    def test_corrupt_lock_file_is_removed(self, avos_dir: Path):
        """A corrupt lock file is treated as stale and removed."""
        (avos_dir / "ingest.lock").write_text("{bad json")

        mgr = IngestLockManager(avos_dir)
        mgr.acquire()
        data = json.loads((avos_dir / "ingest.lock").read_text())
        assert data["pid"] == os.getpid()

    def test_empty_lock_file_is_removed(self, avos_dir: Path):
        (avos_dir / "ingest.lock").write_text("")

        mgr = IngestLockManager(avos_dir)
        mgr.acquire()
        assert (avos_dir / "ingest.lock").exists()


class TestContextManager:
    def test_context_manager_acquires_and_releases(
        self, lock_mgr: IngestLockManager, avos_dir: Path
    ):
        with lock_mgr:
            assert (avos_dir / "ingest.lock").exists()
        assert not (avos_dir / "ingest.lock").exists()

    def test_context_manager_releases_on_exception(
        self, lock_mgr: IngestLockManager, avos_dir: Path
    ):
        with pytest.raises(ValueError), lock_mgr:
            raise ValueError("boom")
        assert not (avos_dir / "ingest.lock").exists()


class TestIsLocked:
    def test_not_locked_initially(self, lock_mgr: IngestLockManager):
        assert not lock_mgr.is_locked()

    def test_locked_after_acquire(self, lock_mgr: IngestLockManager):
        lock_mgr.acquire()
        assert lock_mgr.is_locked()

    def test_not_locked_after_release(self, lock_mgr: IngestLockManager):
        lock_mgr.acquire()
        lock_mgr.release()
        assert not lock_mgr.is_locked()
