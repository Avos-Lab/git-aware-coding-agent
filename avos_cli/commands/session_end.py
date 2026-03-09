"""Session end command orchestrator (AVOS-018).

Stops the watcher, parses checkpoints, builds a session artifact,
stores it via the Memory API, and cleans up local state files.
Follows the existing orchestrator pattern: constructor DI, run() -> exit code.

Exit codes:
    0: success (including degraded completion with warnings)
    1: precondition failure (no active session)
    2: hard external failure (memory API unreachable)
"""

from __future__ import annotations

import json
import os
import signal
import time
from pathlib import Path

from avos_cli.artifacts.session_builder import SessionBuilder
from avos_cli.config.manager import load_config
from avos_cli.config.state import read_json_safe
from avos_cli.exceptions import AvosError, ConfigurationNotInitializedError
from avos_cli.models.artifacts import SessionArtifact
from avos_cli.models.config import SessionCheckpoint
from avos_cli.services.watcher import parse_checkpoints
from avos_cli.utils.logger import get_logger
from avos_cli.utils.output import (
    print_error,
    print_info,
    print_success,
    print_warning,
    render_kv_panel,
    render_table,
)

_log = get_logger("commands.session_end")

_WATCHER_STOP_TIMEOUT = 5


class SessionEndOrchestrator:
    """Orchestrates the `avos session-end` command.

    Pipeline: validate session -> stop watcher -> parse checkpoints ->
    build artifact -> store -> cleanup.

    Args:
        memory_client: Avos Memory API client.
        llm_client: Optional LLM client for narrative enrichment.
        repo_root: Path to the repository root.
    """

    def __init__(
        self,
        memory_client: object,
        llm_client: object | None,
        repo_root: Path,
    ) -> None:
        self._memory = memory_client
        self._llm = llm_client
        self._repo_root = repo_root
        self._avos_dir = repo_root / ".avos"
        self._session_builder = SessionBuilder()

    def run(self) -> int:
        """Execute the session end flow.

        Returns:
            Exit code: 0 success, 1 precondition, 2 external failure.
        """
        try:
            config = load_config(self._repo_root)
        except ConfigurationNotInitializedError as e:
            print_error(f"[CONFIG_NOT_INITIALIZED] {e}")
            return 1
        except AvosError as e:
            print_error(f"[{e.code}] {e}")
            return 1

        session_path = self._avos_dir / "session.json"
        session_data = read_json_safe(session_path)
        if session_data is None:
            print_error("[SESSION_NOT_FOUND] No active session. Run 'avos session-start' first.")
            return 1

        session_id = str(session_data.get("session_id", ""))
        goal = str(session_data.get("goal", ""))
        branch = str(session_data.get("branch", ""))
        memory_id = str(session_data.get("memory_id", config.memory_id))

        warnings_list: list[str] = []

        self._stop_watcher(session_id, warnings_list)

        checkpoint_path = self._avos_dir / "session_checkpoints.jsonl"
        checkpoints, malformed_count = parse_checkpoints(checkpoint_path)

        if malformed_count > 0:
            msg = f"CHECKPOINT_MALFORMED: {malformed_count} malformed checkpoint line(s) skipped."
            warnings_list.append(msg)
            print_warning(msg)

        if not checkpoints:
            msg = "CHECKPOINT_EMPTY: No checkpoint data captured. Creating minimal artifact."
            warnings_list.append(msg)
            print_warning(msg)

        artifact = self._build_artifact(session_id, goal, branch, checkpoints)
        artifact_text = self._session_builder.build(artifact)

        try:
            self._memory.add_memory(memory_id=memory_id, content=artifact_text)
        except Exception as e:
            _log.error("Failed to store session artifact: %s", e)
            print_error(f"[UPSTREAM_UNAVAILABLE] Could not store session artifact: {e}")
            self._cleanup_pid_only()
            print_warning(
                "STORE_FAILED: Session and checkpoint files preserved for recovery. "
                "Re-run 'avos session-end' when the API is available."
            )
            return 2

        residuals = self._cleanup_all()
        if residuals:
            msg = f"CLEANUP_PARTIAL: Could not remove: {', '.join(residuals)}"
            warnings_list.append(msg)
            print_warning(msg)

        self._print_summary(session_id, goal, checkpoints, warnings_list)
        return 0

    def _stop_watcher(self, session_id: str, warnings_list: list[str]) -> None:
        """Stop the watcher process if alive, with ownership verification.

        Verifies session_id matches before sending SIGTERM.
        Continues gracefully if watcher is already dead.
        """
        pid_path = self._avos_dir / "watcher.pid"
        pid_data = read_json_safe(pid_path)

        if pid_data is None:
            warnings_list.append("WATCHER_DEAD: No PID file found. Watcher may have crashed.")
            print_warning("WATCHER_DEAD: No PID file found. Continuing with available data.")
            return

        pid = int(pid_data.get("pid", -1))
        pid_session_id = str(pid_data.get("session_id", ""))

        if pid <= 0:
            _log.warning("Invalid PID value %d in PID file. Skipping process termination.", pid)
            warnings_list.append("WATCHER_DEAD: Invalid PID in file. Skipping process termination.")
            return

        if pid_session_id != session_id:
            _log.warning(
                "PID file session_id mismatch: expected %s, got %s. Skipping SIGTERM.",
                session_id, pid_session_id,
            )
            warnings_list.append(
                "WATCHER_DEAD: PID ownership mismatch. Skipping process termination."
            )
            return

        if not self._pid_alive(pid):
            warnings_list.append("WATCHER_DEAD: Watcher process not running.")
            print_warning("WATCHER_DEAD: Watcher already stopped. Using available checkpoints.")
            return

        try:
            os.kill(pid, signal.SIGTERM)
            _log.info("Sent SIGTERM to watcher PID %d", pid)
            self._wait_for_exit(pid)
        except (OSError, ProcessLookupError) as e:
            _log.warning("Could not stop watcher PID %d: %s", pid, e)
            warnings_list.append(f"WATCHER_DEAD: Could not stop watcher: {e}")

    def _wait_for_exit(self, pid: int) -> None:
        """Wait up to _WATCHER_STOP_TIMEOUT seconds for process to exit."""
        deadline = time.monotonic() + _WATCHER_STOP_TIMEOUT
        while time.monotonic() < deadline:
            if not self._pid_alive(pid):
                return
            time.sleep(0.2)
        _log.warning("Watcher PID %d did not exit within timeout", pid)

    def _build_artifact(
        self,
        session_id: str,
        goal: str,
        branch: str,
        checkpoints: list[SessionCheckpoint],
    ) -> SessionArtifact:
        """Aggregate checkpoints into a SessionArtifact.

        Deduplicates files, collects test commands and errors,
        builds a timeline from checkpoint timestamps.
        """
        all_files: set[str] = set()
        all_test_cmds: set[str] = set()
        all_errors: list[str] = []
        timeline: list[str] = []
        total_added = 0
        total_removed = 0

        for cp in checkpoints:
            all_files.update(cp.files_modified)
            all_test_cmds.update(cp.test_commands_detected)
            all_errors.extend(cp.errors_detected)
            total_added += cp.diff_stats.get("added", 0)
            total_removed += cp.diff_stats.get("removed", 0)

            if cp.files_modified:
                ts = cp.timestamp.isoformat() if hasattr(cp.timestamp, "isoformat") else str(cp.timestamp)
                timeline.append(
                    f"{ts}: Modified {len(cp.files_modified)} file(s) "
                    f"(+{cp.diff_stats.get('added', 0)}/-{cp.diff_stats.get('removed', 0)})"
                )

        decisions: list[str] = []
        if all_test_cmds:
            decisions.append(f"Test commands used: {', '.join(sorted(all_test_cmds))}")
        if total_added or total_removed:
            decisions.append(f"Total changes: +{total_added}/-{total_removed} lines")

        return SessionArtifact(
            session_id=session_id,
            goal=goal,
            files_modified=sorted(all_files),
            decisions=decisions,
            errors=all_errors[:20],
            resolution=None,
            timeline=timeline,
        )

    def _cleanup_all(self) -> list[str]:
        """Remove all session lifecycle files. Returns list of residual filenames."""
        residuals: list[str] = []
        for filename in ("session.json", "watcher.pid", "session_checkpoints.jsonl"):
            path = self._avos_dir / filename
            if path.exists():
                try:
                    path.unlink()
                except OSError as e:
                    _log.warning("Could not remove %s: %s", filename, e)
                    residuals.append(filename)
        return residuals

    def _cleanup_pid_only(self) -> None:
        """Remove only the PID file (used on store failure)."""
        pid_path = self._avos_dir / "watcher.pid"
        if pid_path.exists():
            try:
                pid_path.unlink()
            except OSError:
                pass

    def _print_summary(
        self,
        session_id: str,
        goal: str,
        checkpoints: list[SessionCheckpoint],
        warnings_list: list[str],
    ) -> None:
        """Print session end summary with Rich panel and timeline table."""
        all_files: set[str] = set()
        total_added = 0
        total_removed = 0
        for cp in checkpoints:
            all_files.update(cp.files_modified)
            total_added += cp.diff_stats.get("added", 0)
            total_removed += cp.diff_stats.get("removed", 0)

        render_kv_panel(
            f"Session Ended: {session_id}",
            [
                ("Goal", goal),
                ("Checkpoints", str(len(checkpoints))),
                ("Files touched", str(len(all_files))),
                ("Total changes", f"+{total_added} / -{total_removed}"),
            ],
            style="success",
        )

        if checkpoints:
            timeline_rows: list[list[str]] = []
            for cp in checkpoints:
                ts = cp.timestamp.isoformat() if hasattr(cp.timestamp, "isoformat") else str(cp.timestamp)
                added = cp.diff_stats.get("added", 0)
                removed = cp.diff_stats.get("removed", 0)
                timeline_rows.append([
                    ts,
                    str(len(cp.files_modified)),
                    f"+{added}/-{removed}",
                ])
            render_table(
                "Timeline",
                [("Time", "dim"), ("Files modified", ""), ("Changes", "")],
                timeline_rows,
            )

        if warnings_list:
            print_warning(f"Warnings: {len(warnings_list)}")
            for w in warnings_list:
                print_warning(f"  - {w}")

        print_success("Session artifact stored in memory.")

    @staticmethod
    def _pid_alive(pid: int) -> bool:
        """Check if a process with the given PID is alive."""
        try:
            os.kill(pid, 0)
            return True
        except (OSError, ProcessLookupError):
            return False
