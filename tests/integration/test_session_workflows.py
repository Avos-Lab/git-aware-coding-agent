"""Integration tests for AVOS-019: Session lifecycle end-to-end validation.

Exercises the full session workflow through orchestrators with mocked
external dependencies (Memory API, git), validating:
- Healthy lifecycle (start -> checkpoints -> end -> artifact stored -> cleanup)
- Dead watcher degraded completion
- Empty checkpoint minimal artifact
- Malformed checkpoint tolerance
- Store failure state preservation
- Stale session recovery
- Deterministic output across runs
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from avos_cli.commands.session_end import SessionEndOrchestrator
from avos_cli.commands.session_start import SessionStartOrchestrator


def _setup_repo(tmp_path: Path) -> Path:
    """Create a minimal repo structure with .avos/config.json."""
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    (repo / ".git").mkdir()
    avos = repo / ".avos"
    avos.mkdir()
    config = {
        "repo": "org/test",
        "memory_id": "repo:org/test",
        "memory_id_session": "repo:org/test-session",
        "api_url": "https://api.avos.ai",
        "api_key": "test-key",
        "schema_version": "2",
    }
    (avos / "config.json").write_text(json.dumps(config))
    return repo


def _make_start_orchestrator(repo_root: Path) -> tuple[SessionStartOrchestrator, MagicMock]:
    git_m = MagicMock()
    git_m.current_branch.return_value = "feature/session-test"
    git_m.is_worktree.return_value = False
    mem_m = MagicMock()
    orch = SessionStartOrchestrator(
        git_client=git_m,
        memory_client=mem_m,
        repo_root=repo_root,
    )
    return orch, mem_m


def _make_end_orchestrator(repo_root: Path) -> tuple[SessionEndOrchestrator, MagicMock]:
    mem_m = MagicMock()
    git_m = MagicMock()
    git_m.user_name.return_value = "Integration Test"
    git_m.user_email.return_value = "test@example.com"
    orch = SessionEndOrchestrator(
        memory_client=mem_m,
        llm_client=None,
        git_client=git_m,
        repo_root=repo_root,
    )
    return orch, mem_m


def _inject_checkpoints(avos_dir: Path, count: int = 3, session_id: str = "") -> None:
    """Write synthetic checkpoint lines."""
    lines = []
    for i in range(count):
        lines.append(json.dumps({
            "timestamp": f"2026-03-07T10:{i:02d}:30+00:00",
            "session_id": session_id,
            "branch": "feature/session-test",
            "files_modified": [f"src/module_{i}.py"],
            "diff_stats": {"added": 10 + i, "removed": i},
            "test_commands_detected": ["pytest"] if i == 0 else [],
            "errors_detected": ["ImportError"] if i == 1 else [],
        }))
    (avos_dir / "session_checkpoints.jsonl").write_text("\n".join(lines) + "\n")


class TestHealthyLifecycle:
    """Full start -> checkpoint -> end -> verify lifecycle."""

    def test_complete_lifecycle(self, tmp_path):
        repo = _setup_repo(tmp_path)
        avos = repo / ".avos"

        start_orch, _ = _make_start_orchestrator(repo)
        with patch("avos_cli.commands.session_start.subprocess") as mock_sub:
            mock_proc = MagicMock()
            mock_proc.pid = 54321
            mock_proc.poll.return_value = None
            mock_sub.Popen.return_value = mock_proc
            start_code = start_orch.run("Implement session memory")

        assert start_code == 0
        assert (avos / "session.json").exists()
        assert (avos / "watcher.pid").exists()

        session_data = json.loads((avos / "session.json").read_text())
        session_id = session_data["session_id"]

        _inject_checkpoints(avos, count=3, session_id=session_id)

        end_orch, end_mem = _make_end_orchestrator(repo)
        with patch.object(end_orch, "_stop_watcher"):
            end_code = end_orch.run()

        assert end_code == 0
        end_mem.add_memory.assert_called_once()

        call_kwargs = end_mem.add_memory.call_args
        content = call_kwargs.kwargs.get("content", "")
        assert "Implement session memory" in content
        assert "module_0" in content or "module_1" in content

        assert not (avos / "session.json").exists()
        assert not (avos / "watcher.pid").exists()
        assert not (avos / "session_checkpoints.jsonl").exists()
        assert (avos / "config.json").exists()


class TestDeadWatcherDegradedCompletion:
    """Session end succeeds with warning when watcher is dead."""

    def test_dead_watcher_degraded_success(self, tmp_path):
        repo = _setup_repo(tmp_path)
        avos = repo / ".avos"

        start_orch, _ = _make_start_orchestrator(repo)
        with patch("avos_cli.commands.session_start.subprocess") as mock_sub:
            mock_proc = MagicMock()
            mock_proc.pid = 54321
            mock_proc.poll.return_value = None
            mock_sub.Popen.return_value = mock_proc
            start_orch.run("Test dead watcher")

        session_data = json.loads((avos / "session.json").read_text())
        _inject_checkpoints(avos, count=1, session_id=session_data["session_id"])

        pid_data = json.loads((avos / "watcher.pid").read_text())
        pid_data["pid"] = 999999
        (avos / "watcher.pid").write_text(json.dumps(pid_data))

        end_orch, end_mem = _make_end_orchestrator(repo)
        end_code = end_orch.run()

        assert end_code == 0
        end_mem.add_memory.assert_called_once()
        assert not (avos / "session.json").exists()


class TestEmptyCheckpointMinimalArtifact:
    """Minimal artifact created when no checkpoints exist."""

    def test_empty_checkpoint_creates_artifact(self, tmp_path):
        repo = _setup_repo(tmp_path)
        avos = repo / ".avos"

        start_orch, _ = _make_start_orchestrator(repo)
        with patch("avos_cli.commands.session_start.subprocess") as mock_sub:
            mock_proc = MagicMock()
            mock_proc.pid = 54321
            mock_proc.poll.return_value = None
            mock_sub.Popen.return_value = mock_proc
            start_orch.run("Quick session")

        end_orch, end_mem = _make_end_orchestrator(repo)
        with patch.object(end_orch, "_stop_watcher"):
            end_code = end_orch.run()

        assert end_code == 0
        end_mem.add_memory.assert_called_once()
        content = end_mem.add_memory.call_args.kwargs.get("content", "")
        assert "Quick session" in content
        assert not (avos / "session.json").exists()


class TestMalformedCheckpointTolerance:
    """Malformed lines are skipped; valid ones are used."""

    def test_skips_bad_lines_uses_good(self, tmp_path):
        repo = _setup_repo(tmp_path)
        avos = repo / ".avos"

        start_orch, _ = _make_start_orchestrator(repo)
        with patch("avos_cli.commands.session_start.subprocess") as mock_sub:
            mock_proc = MagicMock()
            mock_proc.pid = 54321
            mock_proc.poll.return_value = None
            mock_sub.Popen.return_value = mock_proc
            start_orch.run("Malformed test")

        session_data = json.loads((avos / "session.json").read_text())
        sid = session_data["session_id"]

        valid = json.dumps({
            "timestamp": "2026-03-07T10:00:30+00:00",
            "session_id": sid,
            "branch": "feature/session-test",
            "files_modified": ["src/valid.py"],
            "diff_stats": {"added": 5, "removed": 1},
            "test_commands_detected": [],
            "errors_detected": [],
        })
        (avos / "session_checkpoints.jsonl").write_text(
            valid + "\nBAD_JSON_LINE\n" + valid + "\n"
        )

        end_orch, end_mem = _make_end_orchestrator(repo)
        with patch.object(end_orch, "_stop_watcher"):
            end_code = end_orch.run()

        assert end_code == 0
        content = end_mem.add_memory.call_args.kwargs.get("content", "")
        assert "valid.py" in content


class TestStoreFailurePreservesState:
    """Memory API failure preserves local state for recovery."""

    def test_preserves_files_on_api_error(self, tmp_path):
        repo = _setup_repo(tmp_path)
        avos = repo / ".avos"

        start_orch, _ = _make_start_orchestrator(repo)
        with patch("avos_cli.commands.session_start.subprocess") as mock_sub:
            mock_proc = MagicMock()
            mock_proc.pid = 54321
            mock_proc.poll.return_value = None
            mock_sub.Popen.return_value = mock_proc
            start_orch.run("Store failure test")

        session_data = json.loads((avos / "session.json").read_text())
        _inject_checkpoints(avos, count=1, session_id=session_data["session_id"])

        end_orch, end_mem = _make_end_orchestrator(repo)
        end_mem.add_memory.side_effect = Exception("API unavailable")

        with patch.object(end_orch, "_stop_watcher"):
            end_code = end_orch.run()

        assert end_code == 2
        assert (avos / "session.json").exists()
        assert (avos / "session_checkpoints.jsonl").exists()


class TestStaleSessionRecovery:
    """Start auto-cleans stale session and proceeds."""

    def test_cleans_stale_and_starts_fresh(self, tmp_path):
        repo = _setup_repo(tmp_path)
        avos = repo / ".avos"

        stale_session = {
            "session_id": "sess_stale",
            "goal": "stale goal",
            "start_time": "2026-03-06T10:00:00+00:00",
            "branch": "old-branch",
            "memory_id": "repo:org/test-session",
        }
        (avos / "session.json").write_text(json.dumps(stale_session))
        stale_pid = {"pid": 999999, "started_at": "2026-03-06T10:00:00+00:00", "session_id": "sess_stale"}
        (avos / "watcher.pid").write_text(json.dumps(stale_pid))

        start_orch, _ = _make_start_orchestrator(repo)
        with patch("avos_cli.commands.session_start.subprocess") as mock_sub:
            mock_proc = MagicMock()
            mock_proc.pid = 11111
            mock_proc.poll.return_value = None
            mock_sub.Popen.return_value = mock_proc
            code = start_orch.run("Fresh start after stale")

        assert code == 0
        session_data = json.loads((avos / "session.json").read_text())
        assert session_data["goal"] == "Fresh start after stale"
        assert session_data["session_id"] != "sess_stale"


class TestDeterministicOutput:
    """Same inputs produce same artifact across multiple runs."""

    def test_three_run_determinism(self, tmp_path):
        artifacts = []
        for run_idx in range(3):
            repo = _setup_repo(tmp_path / f"run_{run_idx}")
            avos = repo / ".avos"

            session = {
                "session_id": "sess_deterministic",
                "goal": "Determinism test",
                "start_time": "2026-03-07T10:00:00+00:00",
                "branch": "main",
                "memory_id": "repo:org/test-session",
            }
            (avos / "session.json").write_text(json.dumps(session))
            pid_data = {"pid": 999999, "started_at": "2026-03-07T10:00:00+00:00", "session_id": "sess_deterministic"}
            (avos / "watcher.pid").write_text(json.dumps(pid_data))

            checkpoints = []
            for i in range(2):
                checkpoints.append(json.dumps({
                    "timestamp": f"2026-03-07T10:0{i}:30+00:00",
                    "session_id": "sess_deterministic",
                    "branch": "main",
                    "files_modified": [f"src/file_{i}.py"],
                    "diff_stats": {"added": 10, "removed": 2},
                    "test_commands_detected": ["pytest"] if i == 0 else [],
                    "errors_detected": [],
                }))
            (avos / "session_checkpoints.jsonl").write_text("\n".join(checkpoints) + "\n")

            end_orch, end_mem = _make_end_orchestrator(repo)
            with patch.object(end_orch, "_stop_watcher"):
                end_orch.run()

            content = end_mem.add_memory.call_args.kwargs.get("content", "")
            artifacts.append(content)

        assert artifacts[0] == artifacts[1] == artifacts[2]
        assert len(artifacts[0]) > 0


class TestStateTransitionMatrix:
    """Verify state file transitions match the normative matrix."""

    def test_before_start_all_absent(self, tmp_path):
        repo = _setup_repo(tmp_path)
        avos = repo / ".avos"
        assert not (avos / "session.json").exists()
        assert not (avos / "watcher.pid").exists()
        assert not (avos / "session_checkpoints.jsonl").exists()

    def test_after_start_session_and_pid_present(self, tmp_path):
        repo = _setup_repo(tmp_path)
        avos = repo / ".avos"

        start_orch, _ = _make_start_orchestrator(repo)
        with patch("avos_cli.commands.session_start.subprocess") as mock_sub:
            mock_proc = MagicMock()
            mock_proc.pid = 12345
            mock_proc.poll.return_value = None
            mock_sub.Popen.return_value = mock_proc
            start_orch.run("Matrix test")

        assert (avos / "session.json").exists()
        assert (avos / "watcher.pid").exists()

    def test_after_successful_end_all_removed(self, tmp_path):
        repo = _setup_repo(tmp_path)
        avos = repo / ".avos"

        session = {
            "session_id": "sess_matrix",
            "goal": "Matrix end test",
            "start_time": "2026-03-07T10:00:00+00:00",
            "branch": "main",
            "memory_id": "repo:org/test-session",
        }
        (avos / "session.json").write_text(json.dumps(session))
        pid_data = {"pid": 999999, "started_at": "2026-03-07T10:00:00+00:00", "session_id": "sess_matrix"}
        (avos / "watcher.pid").write_text(json.dumps(pid_data))
        (avos / "session_checkpoints.jsonl").write_text("")

        end_orch, _ = _make_end_orchestrator(repo)
        with patch.object(end_orch, "_stop_watcher"):
            end_orch.run()

        assert not (avos / "session.json").exists()
        assert not (avos / "watcher.pid").exists()
        assert not (avos / "session_checkpoints.jsonl").exists()

    def test_store_failure_preserves_session_and_checkpoints(self, tmp_path):
        repo = _setup_repo(tmp_path)
        avos = repo / ".avos"

        session = {
            "session_id": "sess_fail",
            "goal": "Fail test",
            "start_time": "2026-03-07T10:00:00+00:00",
            "branch": "main",
            "memory_id": "repo:org/test-session",
        }
        (avos / "session.json").write_text(json.dumps(session))
        pid_data = {"pid": 999999, "started_at": "2026-03-07T10:00:00+00:00", "session_id": "sess_fail"}
        (avos / "watcher.pid").write_text(json.dumps(pid_data))
        cp = json.dumps({
            "timestamp": "2026-03-07T10:00:30+00:00",
            "session_id": "sess_fail",
            "branch": "main",
            "files_modified": ["a.py"],
            "diff_stats": {},
            "test_commands_detected": [],
            "errors_detected": [],
        })
        (avos / "session_checkpoints.jsonl").write_text(cp + "\n")

        end_orch, end_mem = _make_end_orchestrator(repo)
        end_mem.add_memory.side_effect = Exception("API down")

        with patch.object(end_orch, "_stop_watcher"):
            code = end_orch.run()

        assert code == 2
        assert (avos / "session.json").exists()
        assert (avos / "session_checkpoints.jsonl").exists()
        assert not (avos / "watcher.pid").exists()
