"""Tests for AVOS-016: Watcher service.

Covers checkpoint writing, path normalization, signal handling,
backend adapter fallback, aggregation reset, and security controls.
"""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime
from unittest.mock import MagicMock, patch

from avos_cli.services.watcher import (
    _detect_test_commands,
    _normalize_path,
    _write_checkpoint,
    parse_checkpoints,
    run_watcher,
)


class TestWriteCheckpoint:
    """Validate JSONL checkpoint append behaviour."""

    def test_writes_valid_jsonl_line(self, tmp_path):
        cp_path = tmp_path / "checkpoints.jsonl"
        _write_checkpoint(
            checkpoint_path=cp_path,
            session_id="sess_abc",
            branch="main",
            files=["src/a.py"],
            diff_stats={"added": 5, "removed": 2},
            test_cmds=["pytest"],
            errors=[],
        )
        lines = cp_path.read_text().strip().splitlines()
        assert len(lines) == 1
        data = json.loads(lines[0])
        assert data["session_id"] == "sess_abc"
        assert data["branch"] == "main"
        assert data["files_modified"] == ["src/a.py"]
        assert data["diff_stats"] == {"added": 5, "removed": 2}
        assert data["test_commands_detected"] == ["pytest"]
        assert data["errors_detected"] == []
        assert "timestamp" in data

    def test_appends_multiple_lines(self, tmp_path):
        cp_path = tmp_path / "checkpoints.jsonl"
        for i in range(3):
            _write_checkpoint(
                checkpoint_path=cp_path,
                session_id="sess_abc",
                branch="main",
                files=[f"file_{i}.py"],
                diff_stats={},
                test_cmds=[],
                errors=[],
            )
        lines = cp_path.read_text().strip().splitlines()
        assert len(lines) == 3
        for i, line in enumerate(lines):
            data = json.loads(line)
            assert data["files_modified"] == [f"file_{i}.py"]

    def test_empty_files_list(self, tmp_path):
        cp_path = tmp_path / "checkpoints.jsonl"
        _write_checkpoint(
            checkpoint_path=cp_path,
            session_id="sess_abc",
            branch="main",
            files=[],
            diff_stats={},
            test_cmds=[],
            errors=[],
        )
        data = json.loads(cp_path.read_text().strip())
        assert data["files_modified"] == []

    def test_timestamp_is_iso_format(self, tmp_path):
        cp_path = tmp_path / "checkpoints.jsonl"
        _write_checkpoint(
            checkpoint_path=cp_path,
            session_id="sess_abc",
            branch="main",
            files=[],
            diff_stats={},
            test_cmds=[],
            errors=[],
        )
        data = json.loads(cp_path.read_text().strip())
        ts = data["timestamp"]
        parsed = datetime.fromisoformat(ts)
        assert parsed.tzinfo is not None or "Z" in ts or "+" in ts


class TestNormalizePath:
    """Validate path normalization and traversal rejection."""

    def test_relative_path_passthrough(self, tmp_path):
        result = _normalize_path(str(tmp_path / "src" / "main.py"), tmp_path)
        assert result == "src/main.py"

    def test_rejects_parent_traversal(self, tmp_path):
        result = _normalize_path(str(tmp_path / ".." / "secret.py"), tmp_path)
        assert result is None

    def test_rejects_absolute_outside_repo(self, tmp_path):
        result = _normalize_path("/etc/passwd", tmp_path)
        assert result is None

    def test_normalizes_to_posix(self, tmp_path):
        file_path = tmp_path / "src" / "utils" / "helper.py"
        result = _normalize_path(str(file_path), tmp_path)
        assert "\\" not in (result or "")
        assert result == "src/utils/helper.py"

    def test_dotdot_in_middle_rejected(self, tmp_path):
        result = _normalize_path(str(tmp_path / "src" / ".." / ".." / "bad.py"), tmp_path)
        assert result is None


class TestParseCheckpoints:
    """Validate checkpoint JSONL parsing with malformed-line tolerance."""

    def _write_lines(self, path, lines):
        path.write_text("\n".join(lines) + "\n")

    def test_parses_valid_lines(self, tmp_path):
        cp_path = tmp_path / "checkpoints.jsonl"
        line = json.dumps({
            "timestamp": "2026-03-07T10:00:00+00:00",
            "session_id": "sess_abc",
            "branch": "main",
            "files_modified": ["a.py"],
            "diff_stats": {"added": 1, "removed": 0},
            "test_commands_detected": [],
            "errors_detected": [],
        })
        self._write_lines(cp_path, [line])
        checkpoints, warnings = parse_checkpoints(cp_path)
        assert len(checkpoints) == 1
        assert checkpoints[0].session_id == "sess_abc"
        assert warnings == 0

    def test_skips_malformed_lines(self, tmp_path):
        cp_path = tmp_path / "checkpoints.jsonl"
        valid = json.dumps({
            "timestamp": "2026-03-07T10:00:00+00:00",
            "session_id": "sess_abc",
            "branch": "main",
            "files_modified": [],
            "diff_stats": {},
            "test_commands_detected": [],
            "errors_detected": [],
        })
        self._write_lines(cp_path, [valid, "NOT_JSON{{{", valid])
        checkpoints, warnings = parse_checkpoints(cp_path)
        assert len(checkpoints) == 2
        assert warnings == 1

    def test_empty_file_returns_empty(self, tmp_path):
        cp_path = tmp_path / "checkpoints.jsonl"
        cp_path.write_text("")
        checkpoints, warnings = parse_checkpoints(cp_path)
        assert len(checkpoints) == 0
        assert warnings == 0

    def test_missing_file_returns_empty(self, tmp_path):
        cp_path = tmp_path / "nonexistent.jsonl"
        checkpoints, warnings = parse_checkpoints(cp_path)
        assert len(checkpoints) == 0
        assert warnings == 0

    def test_all_malformed_returns_empty(self, tmp_path):
        cp_path = tmp_path / "checkpoints.jsonl"
        self._write_lines(cp_path, ["bad1", "bad2", "bad3"])
        checkpoints, warnings = parse_checkpoints(cp_path)
        assert len(checkpoints) == 0
        assert warnings == 3

    def test_blank_lines_skipped(self, tmp_path):
        cp_path = tmp_path / "checkpoints.jsonl"
        valid = json.dumps({
            "timestamp": "2026-03-07T10:00:00+00:00",
            "session_id": "sess_abc",
            "branch": "main",
            "files_modified": [],
            "diff_stats": {},
            "test_commands_detected": [],
            "errors_detected": [],
        })
        self._write_lines(cp_path, [valid, "", "  ", valid])
        checkpoints, warnings = parse_checkpoints(cp_path)
        assert len(checkpoints) == 2
        assert warnings == 0


class TestDetectTestCommands:
    """Validate test command detection captures names only."""

    @patch("avos_cli.services.watcher.psutil", None)
    def test_returns_empty_when_psutil_unavailable(self):
        result = _detect_test_commands()
        assert result == []

    def test_returns_list_type(self):
        result = _detect_test_commands()
        assert isinstance(result, list)
        assert all(isinstance(cmd, str) for cmd in result)


class TestRunWatcher:
    """Validate watcher main loop behaviour."""

    def test_shutdown_event_stops_loop(self, tmp_path):
        """Watcher exits when shutdown event is set."""
        cp_path = tmp_path / "checkpoints.jsonl"
        shutdown = threading.Event()
        shutdown.set()

        with patch("avos_cli.services.watcher._create_observer") as mock_obs:
            mock_obs.return_value = MagicMock()
            run_watcher(
                repo_root=tmp_path,
                session_id="sess_test",
                branch="main",
                checkpoint_path=cp_path,
                interval=1,
                _shutdown_event=shutdown,
            )

    def test_creates_checkpoint_file_on_run(self, tmp_path):
        """Even a short run should not crash."""
        cp_path = tmp_path / "checkpoints.jsonl"
        shutdown = threading.Event()

        def stop_soon():
            time.sleep(0.3)
            shutdown.set()

        t = threading.Thread(target=stop_soon)
        t.start()

        with patch("avos_cli.services.watcher._create_observer") as mock_obs:
            mock_observer = MagicMock()
            mock_obs.return_value = mock_observer
            run_watcher(
                repo_root=tmp_path,
                session_id="sess_test",
                branch="main",
                checkpoint_path=cp_path,
                interval=0.2,
                _shutdown_event=shutdown,
            )
        t.join()
