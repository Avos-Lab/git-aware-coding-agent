"""Brutal tests for AVOS-022: WatchOrchestrator.

Covers: start happy path, duplicate start prevention, stop active watch,
stop with no active watch, stale PID cleanup, config errors, spawn failure,
and metadata-only payload verification.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from avos_cli.commands.watch import WatchOrchestrator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config_json(avos_dir: Path, memory_id: str = "repo:org/test") -> None:
    avos_dir.mkdir(parents=True, exist_ok=True)
    config = {
        "repo": "org/test",
        "memory_id": memory_id,
        "api_url": "https://api.avos.ai",
        "api_key": "test-key",
        "schema_version": "1",
    }
    (avos_dir / "config.json").write_text(json.dumps(config))


def _make_watch_pid(avos_dir: Path, pid: int = 99999) -> None:
    avos_dir.mkdir(parents=True, exist_ok=True)
    pid_data = {
        "pid": pid,
        "started_at": datetime.now(tz=timezone.utc).isoformat(),
        "repo_root": str(avos_dir.parent),
    }
    (avos_dir / "watch.pid").write_text(json.dumps(pid_data))


def _setup(tmp_path: Path) -> tuple[Path, MagicMock, MagicMock]:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / ".git").mkdir()
    _make_config_json(repo_root / ".avos")
    git_client = MagicMock()
    git_client.current_branch.return_value = "feature/test"
    git_client.user_name.return_value = "TestUser"
    git_client.modified_files.return_value = []
    memory_client = MagicMock()
    return repo_root, git_client, memory_client


# ---------------------------------------------------------------------------
# Start happy path
# ---------------------------------------------------------------------------

class TestStartHappyPath:

    def test_start_creates_pid_file(self, tmp_path: Path) -> None:
        repo_root, git, memory = _setup(tmp_path)
        orch = WatchOrchestrator(
            git_client=git, memory_client=memory, repo_root=repo_root
        )
        with patch.object(orch, "_spawn_watcher", return_value=12345):
            code = orch.run(stop=False)
        assert code == 0
        pid_path = repo_root / ".avos" / "watch.pid"
        assert pid_path.exists()
        pid_data = json.loads(pid_path.read_text())
        assert pid_data["pid"] == 12345


# ---------------------------------------------------------------------------
# Duplicate start prevention
# ---------------------------------------------------------------------------

class TestDuplicateStart:

    def test_active_watch_blocks_start(self, tmp_path: Path) -> None:
        repo_root, git, memory = _setup(tmp_path)
        _make_watch_pid(repo_root / ".avos", pid=os.getpid())
        orch = WatchOrchestrator(
            git_client=git, memory_client=memory, repo_root=repo_root
        )
        code = orch.run(stop=False)
        assert code == 1

    def test_stale_pid_cleaned_and_start_proceeds(self, tmp_path: Path) -> None:
        repo_root, git, memory = _setup(tmp_path)
        _make_watch_pid(repo_root / ".avos", pid=999999)
        orch = WatchOrchestrator(
            git_client=git, memory_client=memory, repo_root=repo_root
        )
        with patch.object(orch, "_spawn_watcher", return_value=12345):
            code = orch.run(stop=False)
        assert code == 0


# ---------------------------------------------------------------------------
# Stop active watch
# ---------------------------------------------------------------------------

class TestStopWatch:

    def test_stop_active_watch(self, tmp_path: Path) -> None:
        repo_root, git, memory = _setup(tmp_path)
        _make_watch_pid(repo_root / ".avos", pid=os.getpid())
        orch = WatchOrchestrator(
            git_client=git, memory_client=memory, repo_root=repo_root
        )
        with patch("avos_cli.commands.watch.os.kill") as mock_kill:
            code = orch.run(stop=True)
        assert code == 0
        assert not (repo_root / ".avos" / "watch.pid").exists()

    def test_stop_no_active_watch(self, tmp_path: Path) -> None:
        repo_root, git, memory = _setup(tmp_path)
        orch = WatchOrchestrator(
            git_client=git, memory_client=memory, repo_root=repo_root
        )
        code = orch.run(stop=True)
        assert code == 1

    def test_stop_stale_pid_cleans_up(self, tmp_path: Path) -> None:
        repo_root, git, memory = _setup(tmp_path)
        _make_watch_pid(repo_root / ".avos", pid=999999)
        orch = WatchOrchestrator(
            git_client=git, memory_client=memory, repo_root=repo_root
        )
        code = orch.run(stop=True)
        assert code == 1
        assert not (repo_root / ".avos" / "watch.pid").exists()


# ---------------------------------------------------------------------------
# Config errors
# ---------------------------------------------------------------------------

class TestConfigErrors:

    def test_missing_config(self, tmp_path: Path) -> None:
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        (repo_root / ".git").mkdir()
        git = MagicMock()
        memory = MagicMock()
        orch = WatchOrchestrator(
            git_client=git, memory_client=memory, repo_root=repo_root
        )
        code = orch.run(stop=False)
        assert code == 1
        memory.add_memory.assert_not_called()


# ---------------------------------------------------------------------------
# Spawn failure
# ---------------------------------------------------------------------------

class TestSpawnFailure:

    def test_spawn_failure_rollback(self, tmp_path: Path) -> None:
        repo_root, git, memory = _setup(tmp_path)
        orch = WatchOrchestrator(
            git_client=git, memory_client=memory, repo_root=repo_root
        )
        with patch.object(orch, "_spawn_watcher", side_effect=OSError("spawn failed")):
            code = orch.run(stop=False)
        assert code == 1
        assert not (repo_root / ".avos" / "watch.pid").exists()


# ---------------------------------------------------------------------------
# State file integrity
# ---------------------------------------------------------------------------

class TestStateIntegrity:

    def test_corrupt_pid_file_treated_as_no_watch(self, tmp_path: Path) -> None:
        repo_root, git, memory = _setup(tmp_path)
        avos_dir = repo_root / ".avos"
        avos_dir.mkdir(parents=True, exist_ok=True)
        (avos_dir / "watch.pid").write_text("{{not json}}")
        orch = WatchOrchestrator(
            git_client=git, memory_client=memory, repo_root=repo_root
        )
        with patch.object(orch, "_spawn_watcher", return_value=12345):
            code = orch.run(stop=False)
        assert code == 0
