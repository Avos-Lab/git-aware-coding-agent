"""Tests for Sprint 4 session models: WatcherPidState and SessionCheckpoint.

Covers creation, frozen immutability, validation, serialization round-trip,
missing fields, edge cases, and enum/exception completeness for new error codes.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from avos_cli.exceptions import (
    AvosError,
    CheckpointParseError,
    ErrorCode,
    SessionActiveError,
    SessionNotFoundError,
    WatcherLifecycleError,
)
from avos_cli.models.config import SessionCheckpoint, WatcherPidState


class TestWatcherPidState:
    """Validate WatcherPidState model behaviour."""

    def _make(self, **overrides):
        defaults = {
            "pid": 12345,
            "started_at": datetime(2026, 3, 7, 10, 0, 0, tzinfo=timezone.utc),
            "session_id": "sess_abc123",
        }
        defaults.update(overrides)
        return WatcherPidState(**defaults)

    def test_valid_creation(self):
        state = self._make()
        assert state.pid == 12345
        assert state.session_id == "sess_abc123"
        assert state.started_at.year == 2026

    def test_frozen_immutability(self):
        state = self._make()
        with pytest.raises(ValidationError):
            state.pid = 99999  # type: ignore[misc]

    def test_missing_pid_raises(self):
        with pytest.raises(ValidationError):
            WatcherPidState(
                started_at=datetime.now(tz=timezone.utc),
                session_id="sess_x",
            )

    def test_missing_session_id_raises(self):
        with pytest.raises(ValidationError):
            WatcherPidState(
                pid=1,
                started_at=datetime.now(tz=timezone.utc),
            )

    def test_missing_started_at_raises(self):
        with pytest.raises(ValidationError):
            WatcherPidState(pid=1, session_id="sess_x")

    def test_serialization_round_trip(self):
        state = self._make()
        data = state.model_dump(mode="json")
        restored = WatcherPidState(**data)
        assert restored.pid == state.pid
        assert restored.session_id == state.session_id

    def test_negative_pid_accepted(self):
        """PID is just an int; OS-level validation is not the model's job."""
        state = self._make(pid=-1)
        assert state.pid == -1

    def test_zero_pid_accepted(self):
        state = self._make(pid=0)
        assert state.pid == 0


class TestSessionCheckpoint:
    """Validate SessionCheckpoint model behaviour."""

    def _make(self, **overrides):
        defaults = {
            "timestamp": datetime(2026, 3, 7, 10, 0, 30, tzinfo=timezone.utc),
            "session_id": "sess_abc123",
            "branch": "main",
        }
        defaults.update(overrides)
        return SessionCheckpoint(**defaults)

    def test_valid_creation_minimal(self):
        cp = self._make()
        assert cp.session_id == "sess_abc123"
        assert cp.branch == "main"
        assert cp.files_modified == []
        assert cp.diff_stats == {}
        assert cp.test_commands_detected == []
        assert cp.errors_detected == []

    def test_valid_creation_full(self):
        cp = self._make(
            files_modified=["src/main.py", "tests/test_main.py"],
            diff_stats={"added": 10, "removed": 3},
            test_commands_detected=["pytest"],
            errors_detected=["ImportError"],
        )
        assert len(cp.files_modified) == 2
        assert cp.diff_stats["added"] == 10
        assert cp.test_commands_detected == ["pytest"]

    def test_frozen_immutability(self):
        cp = self._make()
        with pytest.raises(ValidationError):
            cp.branch = "other"  # type: ignore[misc]

    def test_missing_timestamp_raises(self):
        with pytest.raises(ValidationError):
            SessionCheckpoint(session_id="sess_x", branch="main")

    def test_missing_session_id_raises(self):
        with pytest.raises(ValidationError):
            SessionCheckpoint(
                timestamp=datetime.now(tz=timezone.utc),
                branch="main",
            )

    def test_missing_branch_raises(self):
        with pytest.raises(ValidationError):
            SessionCheckpoint(
                timestamp=datetime.now(tz=timezone.utc),
                session_id="sess_x",
            )

    def test_serialization_round_trip(self):
        cp = self._make(
            files_modified=["a.py"],
            diff_stats={"added": 5, "removed": 2},
        )
        data = cp.model_dump(mode="json")
        restored = SessionCheckpoint(**data)
        assert restored.files_modified == cp.files_modified
        assert restored.diff_stats == cp.diff_stats

    def test_empty_files_list_default(self):
        cp = self._make()
        assert cp.files_modified == []

    def test_empty_diff_stats_default(self):
        cp = self._make()
        assert cp.diff_stats == {}


class TestSessionErrorCodes:
    """Validate new Sprint 4 error codes exist in the ErrorCode enum."""

    @pytest.mark.parametrize(
        "code",
        [
            "SESSION_ACTIVE_CONFLICT",
            "SESSION_NOT_FOUND",
            "WATCHER_SPAWN_FAILED",
            "WATCHER_STOP_FAILED",
            "CHECKPOINT_PARSE_ERROR",
        ],
    )
    def test_error_code_exists(self, code):
        assert hasattr(ErrorCode, code)
        assert ErrorCode(code) == getattr(ErrorCode, code)


class TestSessionExceptions:
    """Validate new Sprint 4 exception classes."""

    def test_session_active_error_inherits_avos_error(self):
        assert issubclass(SessionActiveError, AvosError)

    def test_session_active_error_defaults(self):
        exc = SessionActiveError()
        assert exc.code == ErrorCode.SESSION_ACTIVE_CONFLICT
        assert exc.hint is not None
        assert "session" in exc.hint.lower() or "end" in exc.hint.lower()

    def test_session_active_error_custom_message(self):
        exc = SessionActiveError("custom msg")
        assert str(exc) == "custom msg"

    def test_session_not_found_error_inherits_avos_error(self):
        assert issubclass(SessionNotFoundError, AvosError)

    def test_session_not_found_error_defaults(self):
        exc = SessionNotFoundError()
        assert exc.code == ErrorCode.SESSION_NOT_FOUND
        assert exc.hint is not None

    def test_session_not_found_error_custom_message(self):
        exc = SessionNotFoundError("no session here")
        assert str(exc) == "no session here"

    def test_watcher_lifecycle_error_inherits_avos_error(self):
        assert issubclass(WatcherLifecycleError, AvosError)

    def test_watcher_lifecycle_error_spawn(self):
        exc = WatcherLifecycleError("spawn failed", failure_type="spawn")
        assert exc.code == ErrorCode.WATCHER_SPAWN_FAILED
        assert exc.failure_type == "spawn"

    def test_watcher_lifecycle_error_stop(self):
        exc = WatcherLifecycleError("stop failed", failure_type="stop")
        assert exc.code == ErrorCode.WATCHER_STOP_FAILED
        assert exc.failure_type == "stop"

    def test_watcher_lifecycle_error_default_type(self):
        exc = WatcherLifecycleError("generic failure")
        assert exc.code == ErrorCode.WATCHER_SPAWN_FAILED
        assert exc.failure_type == "spawn"

    def test_checkpoint_parse_error_inherits_avos_error(self):
        assert issubclass(CheckpointParseError, AvosError)

    def test_checkpoint_parse_error_defaults(self):
        exc = CheckpointParseError("bad line")
        assert exc.code == ErrorCode.CHECKPOINT_PARSE_ERROR
        assert exc.hint is not None

    def test_all_session_exceptions_not_retryable(self):
        exceptions = [
            SessionActiveError(),
            SessionNotFoundError(),
            WatcherLifecycleError("fail"),
            CheckpointParseError("bad"),
        ]
        for exc in exceptions:
            assert exc.retryable is False


class TestModelReExports:
    """Verify new models are re-exported from avos_cli.models."""

    def test_watcher_pid_state_importable(self):
        from avos_cli.models import WatcherPidState as Imported

        assert Imported is WatcherPidState

    def test_session_checkpoint_importable(self):
        from avos_cli.models import SessionCheckpoint as Imported

        assert Imported is SessionCheckpoint
