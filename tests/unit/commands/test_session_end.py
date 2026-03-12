"""Tests for AVOS-018: SessionEndOrchestrator.

Covers happy path, dead watcher degraded success, empty checkpoints,
malformed checkpoint lines, memory API failure, no active session,
PID ownership mismatch, and cleanup behaviour.
"""

from __future__ import annotations

import json
import os
import signal
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from avos_cli.commands.session_end import SessionEndOrchestrator


def _make_config_json(avos_dir: Path) -> None:
    avos_dir.mkdir(parents=True, exist_ok=True)
    config = {
        "repo": "org/test",
        "memory_id": "repo:org/test",
        "memory_id_session": "repo:org/test-session",
        "api_url": "https://api.avos.ai",
        "api_key": "test-key",
        "schema_version": "2",
    }
    (avos_dir / "config.json").write_text(json.dumps(config))


def _make_session_state(avos_dir: Path, session_id: str = "sess_abc123") -> None:
    avos_dir.mkdir(parents=True, exist_ok=True)
    session = {
        "session_id": session_id,
        "goal": "Implement feature X",
        "start_time": "2026-03-07T10:00:00+00:00",
        "branch": "feature/test",
        "memory_id": "repo:org/test-session",
    }
    (avos_dir / "session.json").write_text(json.dumps(session))


def _make_pid_file(avos_dir: Path, pid: int, session_id: str = "sess_abc123") -> None:
    pid_data = {
        "pid": pid,
        "started_at": "2026-03-07T10:00:00+00:00",
        "session_id": session_id,
    }
    (avos_dir / "watcher.pid").write_text(json.dumps(pid_data))


def _make_checkpoints(avos_dir: Path, count: int = 2, session_id: str = "sess_abc123") -> None:
    lines = []
    for i in range(count):
        lines.append(json.dumps({
            "timestamp": f"2026-03-07T10:0{i}:30+00:00",
            "session_id": session_id,
            "branch": "feature/test",
            "files_modified": [f"src/file_{i}.py"],
            "diff_stats": {"added": 5 + i, "removed": i},
            "test_commands_detected": ["pytest"] if i == 0 else [],
            "errors_detected": [],
        }))
    (avos_dir / "session_checkpoints.jsonl").write_text("\n".join(lines) + "\n")


def _make_orchestrator(repo_root: Path, llm_client=None, git_client=None) -> SessionEndOrchestrator:
    if git_client is None:
        git_client = MagicMock()
        git_client.user_name.return_value = "Test User"
        git_client.user_email.return_value = "test@example.com"
    return SessionEndOrchestrator(
        memory_client=MagicMock(),
        llm_client=llm_client,
        git_client=git_client,
        repo_root=repo_root,
    )


class TestHappyPath:
    """Session end succeeds with watcher alive, valid checkpoints."""

    def test_full_lifecycle(self, tmp_path):
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        (repo_root / ".git").mkdir()
        avos_dir = repo_root / ".avos"
        _make_config_json(avos_dir)
        _make_session_state(avos_dir)
        _make_pid_file(avos_dir, pid=999999)
        _make_checkpoints(avos_dir, count=3)

        orchestrator = _make_orchestrator(repo_root)

        with patch.object(orchestrator, "_stop_watcher") as mock_stop:
            code = orchestrator.run()

        assert code == 0
        orchestrator._memory.add_memory.assert_called_once()
        call_kwargs = orchestrator._memory.add_memory.call_args
        assert "repo:org/test" in str(call_kwargs)

        assert not (avos_dir / "session.json").exists()
        assert not (avos_dir / "watcher.pid").exists()
        assert not (avos_dir / "session_checkpoints.jsonl").exists()

    def test_artifact_contains_goal_and_files(self, tmp_path):
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        (repo_root / ".git").mkdir()
        avos_dir = repo_root / ".avos"
        _make_config_json(avos_dir)
        _make_session_state(avos_dir)
        _make_pid_file(avos_dir, pid=999999)
        _make_checkpoints(avos_dir, count=2)

        orchestrator = _make_orchestrator(repo_root)

        with patch.object(orchestrator, "_stop_watcher"):
            code = orchestrator.run()

        assert code == 0
        content_arg = orchestrator._memory.add_memory.call_args[1].get(
            "content", orchestrator._memory.add_memory.call_args[0][0]
            if orchestrator._memory.add_memory.call_args[0] else ""
        )
        if not content_arg:
            content_arg = str(orchestrator._memory.add_memory.call_args)
        assert "Implement feature X" in content_arg or "feature" in content_arg.lower()
        assert "[author:" in content_arg


class TestDeadWatcher:
    """Degraded success when watcher is already dead."""

    def test_continues_with_warning(self, tmp_path):
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        (repo_root / ".git").mkdir()
        avos_dir = repo_root / ".avos"
        _make_config_json(avos_dir)
        _make_session_state(avos_dir)
        _make_pid_file(avos_dir, pid=999999)
        _make_checkpoints(avos_dir, count=1)

        orchestrator = _make_orchestrator(repo_root)
        code = orchestrator.run()

        assert code == 0
        orchestrator._memory.add_memory.assert_called_once()
        assert not (avos_dir / "session.json").exists()


class TestEmptyCheckpoints:
    """Minimal artifact when no checkpoints exist."""

    def test_creates_minimal_artifact(self, tmp_path):
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        (repo_root / ".git").mkdir()
        avos_dir = repo_root / ".avos"
        _make_config_json(avos_dir)
        _make_session_state(avos_dir)
        _make_pid_file(avos_dir, pid=999999)

        orchestrator = _make_orchestrator(repo_root)

        with patch.object(orchestrator, "_stop_watcher"):
            code = orchestrator.run()

        assert code == 0
        orchestrator._memory.add_memory.assert_called_once()
        assert not (avos_dir / "session.json").exists()


class TestMalformedCheckpoints:
    """Skips malformed lines and continues."""

    def test_skips_bad_lines_with_warning(self, tmp_path):
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        (repo_root / ".git").mkdir()
        avos_dir = repo_root / ".avos"
        _make_config_json(avos_dir)
        _make_session_state(avos_dir)
        _make_pid_file(avos_dir, pid=999999)

        valid_line = json.dumps({
            "timestamp": "2026-03-07T10:00:30+00:00",
            "session_id": "sess_abc123",
            "branch": "feature/test",
            "files_modified": ["a.py"],
            "diff_stats": {},
            "test_commands_detected": [],
            "errors_detected": [],
        })
        (avos_dir / "session_checkpoints.jsonl").write_text(
            valid_line + "\nBAD_JSON\n" + valid_line + "\n"
        )

        orchestrator = _make_orchestrator(repo_root)

        with patch.object(orchestrator, "_stop_watcher"):
            code = orchestrator.run()

        assert code == 0
        orchestrator._memory.add_memory.assert_called_once()


class TestMemoryAPIFailure:
    """Exit 2 and preserve local state on store failure."""

    def test_preserves_state_on_store_failure(self, tmp_path):
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        (repo_root / ".git").mkdir()
        avos_dir = repo_root / ".avos"
        _make_config_json(avos_dir)
        _make_session_state(avos_dir)
        _make_pid_file(avos_dir, pid=999999)
        _make_checkpoints(avos_dir, count=1)

        orchestrator = _make_orchestrator(repo_root)
        orchestrator._memory.add_memory.side_effect = Exception("API unavailable")

        with patch.object(orchestrator, "_stop_watcher"):
            code = orchestrator.run()

        assert code == 2
        assert (avos_dir / "session.json").exists()
        assert (avos_dir / "session_checkpoints.jsonl").exists()


class TestNoActiveSession:
    """Exit 1 when no session is active."""

    def test_returns_1_when_no_session(self, tmp_path):
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        (repo_root / ".git").mkdir()
        _make_config_json(repo_root / ".avos")

        orchestrator = _make_orchestrator(repo_root)
        code = orchestrator.run()

        assert code == 1


class TestPidOwnershipMismatch:
    """Skips SIGTERM when PID file session_id doesn't match."""

    def test_skips_kill_on_mismatch(self, tmp_path):
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        (repo_root / ".git").mkdir()
        avos_dir = repo_root / ".avos"
        _make_config_json(avos_dir)
        _make_session_state(avos_dir, session_id="sess_abc123")
        _make_pid_file(avos_dir, pid=os.getpid(), session_id="sess_DIFFERENT")
        _make_checkpoints(avos_dir, count=1, session_id="sess_abc123")

        orchestrator = _make_orchestrator(repo_root)

        with patch("os.kill") as mock_kill:
            code = orchestrator.run()

        mock_kill.assert_not_called()
        assert code == 0


class TestCleanupBehaviour:
    """Verify cleanup removes all lifecycle files on success."""

    def test_removes_all_state_files(self, tmp_path):
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        (repo_root / ".git").mkdir()
        avos_dir = repo_root / ".avos"
        _make_config_json(avos_dir)
        _make_session_state(avos_dir)
        _make_pid_file(avos_dir, pid=999999)
        _make_checkpoints(avos_dir, count=1)

        orchestrator = _make_orchestrator(repo_root)

        with patch.object(orchestrator, "_stop_watcher"):
            code = orchestrator.run()

        assert code == 0
        assert not (avos_dir / "session.json").exists()
        assert not (avos_dir / "watcher.pid").exists()
        assert not (avos_dir / "session_checkpoints.jsonl").exists()
        assert (avos_dir / "config.json").exists()
