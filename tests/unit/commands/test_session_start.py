"""Tests for AVOS-017: SessionStartOrchestrator.

Covers happy path, active-session guard, stale cleanup, goal sanitization,
watcher spawn failure rollback, and config precondition failures.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from avos_cli.commands.session_start import SessionStartOrchestrator
from avos_cli.exceptions import ConfigurationNotInitializedError


def _make_config_json(
    avos_dir: Path,
    memory_id: str = "repo:org/test",
    memory_id_session: str = "repo:org/test-session",
) -> None:
    """Write a minimal valid config.json for tests."""
    avos_dir.mkdir(parents=True, exist_ok=True)
    config = {
        "repo": "org/test",
        "memory_id": memory_id,
        "memory_id_session": memory_id_session,
        "api_url": "https://api.avos.ai",
        "api_key": "test-key",
        "schema_version": "2",
    }
    (avos_dir / "config.json").write_text(json.dumps(config))


def _make_session_json(avos_dir: Path, session_id: str = "sess_old", pid: int = 99999) -> None:
    """Write a session.json and watcher.pid to simulate active session."""
    avos_dir.mkdir(parents=True, exist_ok=True)
    session = {
        "session_id": session_id,
        "goal": "old goal",
        "start_time": "2026-03-07T10:00:00+00:00",
        "branch": "main",
        "memory_id": "repo:org/test-session",
    }
    (avos_dir / "session.json").write_text(json.dumps(session))
    pid_data = {
        "pid": pid,
        "started_at": "2026-03-07T10:00:00+00:00",
        "session_id": session_id,
    }
    (avos_dir / "watcher.pid").write_text(json.dumps(pid_data))


class TestHappyPath:
    """Session start succeeds under normal conditions."""

    def test_creates_session_and_spawns_watcher(self, tmp_path):
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        (repo_root / ".git").mkdir()
        avos_dir = repo_root / ".avos"
        _make_config_json(avos_dir)

        git_client = MagicMock()
        git_client.is_worktree.return_value = False
        git_client.current_branch.return_value = "feature/test"
        memory_client = MagicMock()

        orchestrator = SessionStartOrchestrator(
            git_client=git_client,
            memory_client=memory_client,
            repo_root=repo_root,
        )

        with patch("avos_cli.commands.session_start.subprocess") as mock_sub:
            mock_process = MagicMock()
            mock_process.pid = 12345
            mock_process.poll.return_value = None
            mock_sub.Popen.return_value = mock_process

            code = orchestrator.run("Implement feature X")

        assert code == 0
        assert (avos_dir / "session.json").exists()
        assert (avos_dir / "watcher.pid").exists()

        session_data = json.loads((avos_dir / "session.json").read_text())
        assert session_data["goal"] == "Implement feature X"
        assert session_data["branch"] == "feature/test"
        assert session_data["session_id"].startswith("sess_")
        assert session_data["memory_id"] == "repo:org/test-session"

        pid_data = json.loads((avos_dir / "watcher.pid").read_text())
        assert pid_data["pid"] == 12345
        assert pid_data["session_id"] == session_data["session_id"]

    def test_session_id_format(self, tmp_path):
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        (repo_root / ".git").mkdir()
        _make_config_json(repo_root / ".avos")

        git_client = MagicMock()
        git_client.is_worktree.return_value = False
        git_client.current_branch.return_value = "main"

        orchestrator = SessionStartOrchestrator(
            git_client=git_client,
            memory_client=MagicMock(),
            repo_root=repo_root,
        )

        with patch("avos_cli.commands.session_start.subprocess") as mock_sub:
            mock_process = MagicMock()
            mock_process.pid = 1
            mock_process.poll.return_value = None
            mock_sub.Popen.return_value = mock_process
            orchestrator.run("test")

        session_data = json.loads((repo_root / ".avos" / "session.json").read_text())
        sid = session_data["session_id"]
        assert sid.startswith("sess_")
        assert len(sid) == 5 + 16  # "sess_" + 16 hex chars


class TestActiveSessionGuard:
    """Blocks start when a live session is already running."""

    def test_blocks_when_watcher_alive(self, tmp_path):
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        (repo_root / ".git").mkdir()
        avos_dir = repo_root / ".avos"
        _make_config_json(avos_dir)
        _make_session_json(avos_dir, pid=os.getpid())

        git_client = MagicMock()
        git_client.is_worktree.return_value = False
        orchestrator = SessionStartOrchestrator(
            git_client=git_client,
            memory_client=MagicMock(),
            repo_root=repo_root,
        )

        code = orchestrator.run("new goal")
        assert code == 1


class TestStaleSessionCleanup:
    """Auto-cleans stale sessions and continues."""

    def test_cleans_stale_session_with_dead_pid(self, tmp_path):
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        (repo_root / ".git").mkdir()
        avos_dir = repo_root / ".avos"
        _make_config_json(avos_dir)
        _make_session_json(avos_dir, pid=999999)

        git_client = MagicMock()
        git_client.is_worktree.return_value = False
        git_client.current_branch.return_value = "main"

        orchestrator = SessionStartOrchestrator(
            git_client=git_client,
            memory_client=MagicMock(),
            repo_root=repo_root,
        )

        with patch("avos_cli.commands.session_start.subprocess") as mock_sub:
            mock_process = MagicMock()
            mock_process.pid = 12345
            mock_process.poll.return_value = None
            mock_sub.Popen.return_value = mock_process

            code = orchestrator.run("new goal after stale")

        assert code == 0
        session_data = json.loads((avos_dir / "session.json").read_text())
        assert session_data["goal"] == "new goal after stale"


class TestGoalSanitization:
    """Goal text is sanitized before storage."""

    def test_strips_control_characters(self, tmp_path):
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        (repo_root / ".git").mkdir()
        _make_config_json(repo_root / ".avos")

        git_client = MagicMock()
        git_client.is_worktree.return_value = False
        git_client.current_branch.return_value = "main"

        orchestrator = SessionStartOrchestrator(
            git_client=git_client,
            memory_client=MagicMock(),
            repo_root=repo_root,
        )

        with patch("avos_cli.commands.session_start.subprocess") as mock_sub:
            mock_process = MagicMock()
            mock_process.pid = 1
            mock_process.poll.return_value = None
            mock_sub.Popen.return_value = mock_process
            orchestrator.run("Fix\x00 the\x01 bug\x07")

        session_data = json.loads((repo_root / ".avos" / "session.json").read_text())
        assert "\x00" not in session_data["goal"]
        assert "\x01" not in session_data["goal"]
        assert "\x07" not in session_data["goal"]
        assert "Fix" in session_data["goal"]

    def test_truncates_long_goal(self, tmp_path):
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        (repo_root / ".git").mkdir()
        _make_config_json(repo_root / ".avos")

        git_client = MagicMock()
        git_client.is_worktree.return_value = False
        git_client.current_branch.return_value = "main"

        orchestrator = SessionStartOrchestrator(
            git_client=git_client,
            memory_client=MagicMock(),
            repo_root=repo_root,
        )

        long_goal = "A" * 2000

        with patch("avos_cli.commands.session_start.subprocess") as mock_sub:
            mock_process = MagicMock()
            mock_process.pid = 1
            mock_process.poll.return_value = None
            mock_sub.Popen.return_value = mock_process
            orchestrator.run(long_goal)

        session_data = json.loads((repo_root / ".avos" / "session.json").read_text())
        assert len(session_data["goal"]) <= 1000


class TestWatcherSpawnFailure:
    """Rollback when watcher fails to spawn."""

    def test_rollback_on_spawn_error(self, tmp_path):
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        (repo_root / ".git").mkdir()
        _make_config_json(repo_root / ".avos")

        git_client = MagicMock()
        git_client.is_worktree.return_value = False
        git_client.current_branch.return_value = "main"

        orchestrator = SessionStartOrchestrator(
            git_client=git_client,
            memory_client=MagicMock(),
            repo_root=repo_root,
        )

        with patch("avos_cli.commands.session_start.subprocess") as mock_sub:
            mock_sub.Popen.side_effect = OSError("spawn failed")
            code = orchestrator.run("test goal")

        assert code == 1
        assert not (repo_root / ".avos" / "session.json").exists()
        assert not (repo_root / ".avos" / "watcher.pid").exists()

    def test_rollback_on_immediate_exit(self, tmp_path):
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        (repo_root / ".git").mkdir()
        _make_config_json(repo_root / ".avos")

        git_client = MagicMock()
        git_client.is_worktree.return_value = False
        git_client.current_branch.return_value = "main"

        orchestrator = SessionStartOrchestrator(
            git_client=git_client,
            memory_client=MagicMock(),
            repo_root=repo_root,
        )

        with patch("avos_cli.commands.session_start.subprocess") as mock_sub:
            mock_process = MagicMock()
            mock_process.pid = 1
            mock_process.poll.return_value = 1  # already exited
            mock_sub.Popen.return_value = mock_process
            code = orchestrator.run("test goal")

        assert code == 1
        assert not (repo_root / ".avos" / "session.json").exists()


class TestConfigPreconditions:
    """Fails cleanly when config is missing."""

    def test_missing_config_returns_1(self, tmp_path):
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        (repo_root / ".git").mkdir()

        orchestrator = SessionStartOrchestrator(
            git_client=MagicMock(),
            memory_client=MagicMock(),
            repo_root=repo_root,
        )

        code = orchestrator.run("test goal")
        assert code == 1
