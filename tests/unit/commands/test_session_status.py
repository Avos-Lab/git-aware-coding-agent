"""Tests for SessionStatusOrchestrator.

Covers: no active session, active session with live watcher,
active session with dead watcher, JSON output mode, and config errors.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from avos_cli.commands.session_status import SessionStatusOrchestrator


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


def _make_session_json(
    avos_dir: Path,
    session_id: str = "sess_abc123",
    goal: str = "Test goal",
    branch: str = "main",
    pid: int = 99999,
    agent: str | None = None,
) -> None:
    """Write a session.json and watcher.pid to simulate active session."""
    avos_dir.mkdir(parents=True, exist_ok=True)
    session = {
        "session_id": session_id,
        "goal": goal,
        "start_time": "2026-03-07T10:00:00+00:00",
        "branch": branch,
        "memory_id": "repo:org/test-session",
    }
    if agent:
        session["developer"] = agent
    (avos_dir / "session.json").write_text(json.dumps(session))
    pid_data = {
        "pid": pid,
        "started_at": "2026-03-07T10:00:00+00:00",
        "session_id": session_id,
    }
    (avos_dir / "watcher.pid").write_text(json.dumps(pid_data))


class TestNoActiveSession:
    """Status when no session is active."""

    def test_returns_inactive_status(self, tmp_path):
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        (repo_root / ".git").mkdir()
        avos_dir = repo_root / ".avos"
        _make_config_json(avos_dir)

        orchestrator = SessionStatusOrchestrator(repo_root=repo_root)
        code = orchestrator.run(json_output=False)

        assert code == 0

    def test_json_output_inactive(self, tmp_path, capsys):
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        (repo_root / ".git").mkdir()
        avos_dir = repo_root / ".avos"
        _make_config_json(avos_dir)

        orchestrator = SessionStatusOrchestrator(repo_root=repo_root)
        code = orchestrator.run(json_output=True)

        assert code == 0
        captured = capsys.readouterr()
        result = json.loads(captured.out)
        assert result["success"] is True
        assert result["data"]["active"] is False
        assert result["data"]["session_id"] is None
        assert result["data"]["watcher_alive"] is False


class TestActiveSessionLiveWatcher:
    """Status when session is active with a live watcher process."""

    def test_returns_active_with_watcher_alive(self, tmp_path):
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        (repo_root / ".git").mkdir()
        avos_dir = repo_root / ".avos"
        _make_config_json(avos_dir)
        _make_session_json(avos_dir, pid=os.getpid())

        orchestrator = SessionStatusOrchestrator(repo_root=repo_root)
        code = orchestrator.run(json_output=False)

        assert code == 0

    def test_json_output_active_watcher_alive(self, tmp_path, capsys):
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        (repo_root / ".git").mkdir()
        avos_dir = repo_root / ".avos"
        _make_config_json(avos_dir)
        _make_session_json(
            avos_dir,
            session_id="sess_test123",
            goal="Implement feature",
            branch="feature/x",
            pid=os.getpid(),
            agent="agentA",
        )

        orchestrator = SessionStatusOrchestrator(repo_root=repo_root)
        code = orchestrator.run(json_output=True)

        assert code == 0
        captured = capsys.readouterr()
        result = json.loads(captured.out)
        assert result["success"] is True
        assert result["data"]["active"] is True
        assert result["data"]["session_id"] == "sess_test123"
        assert result["data"]["goal"] == "Implement feature"
        assert result["data"]["branch"] == "feature/x"
        assert result["data"]["agent"] == "agentA"
        assert result["data"]["watcher_alive"] is True


class TestActiveSessionDeadWatcher:
    """Status when session exists but watcher is dead."""

    def test_returns_active_with_watcher_dead(self, tmp_path, capsys):
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        (repo_root / ".git").mkdir()
        avos_dir = repo_root / ".avos"
        _make_config_json(avos_dir)
        _make_session_json(avos_dir, pid=999999)

        orchestrator = SessionStatusOrchestrator(repo_root=repo_root)
        code = orchestrator.run(json_output=True)

        assert code == 0
        captured = capsys.readouterr()
        result = json.loads(captured.out)
        assert result["success"] is True
        assert result["data"]["active"] is True
        assert result["data"]["watcher_alive"] is False


class TestConfigErrors:
    """Handles missing config gracefully."""

    def test_missing_config_returns_error(self, tmp_path):
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        (repo_root / ".git").mkdir()

        orchestrator = SessionStatusOrchestrator(repo_root=repo_root)
        code = orchestrator.run(json_output=False)

        assert code == 1

    def test_missing_config_json_output(self, tmp_path, capsys):
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        (repo_root / ".git").mkdir()

        orchestrator = SessionStatusOrchestrator(repo_root=repo_root)
        code = orchestrator.run(json_output=True)

        assert code == 1
        captured = capsys.readouterr()
        result = json.loads(captured.out)
        assert result["success"] is False
        assert result["error"]["code"] == "CONFIG_NOT_INITIALIZED"


class TestSessionWithoutPidFile:
    """Session.json exists but watcher.pid is missing."""

    def test_session_without_pid_file(self, tmp_path, capsys):
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        (repo_root / ".git").mkdir()
        avos_dir = repo_root / ".avos"
        _make_config_json(avos_dir)

        session = {
            "session_id": "sess_orphan",
            "goal": "Orphan session",
            "start_time": "2026-03-07T10:00:00+00:00",
            "branch": "main",
            "memory_id": "repo:org/test-session",
        }
        (avos_dir / "session.json").write_text(json.dumps(session))

        orchestrator = SessionStatusOrchestrator(repo_root=repo_root)
        code = orchestrator.run(json_output=True)

        assert code == 0
        captured = capsys.readouterr()
        result = json.loads(captured.out)
        assert result["success"] is True
        assert result["data"]["active"] is True
        assert result["data"]["session_id"] == "sess_orphan"
        assert result["data"]["watcher_alive"] is False
