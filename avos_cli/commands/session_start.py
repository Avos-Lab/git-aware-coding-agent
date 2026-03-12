"""Session start command orchestrator (AVOS-017).

Validates preconditions, creates session state, spawns the watcher
background process, and persists PID metadata. Follows the existing
orchestrator pattern: constructor DI, run() -> exit code.

Exit codes:
    0: success
    1: precondition failure (config missing, active session, spawn error)
    2: hard external failure
"""

from __future__ import annotations

import json
import os
import secrets
import subprocess
import sys
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

from avos_cli.config.manager import load_config
from avos_cli.config.state import atomic_write, read_json_safe
from avos_cli.exceptions import AvosError, ConfigurationNotInitializedError
from avos_cli.services.git_client import GitClient
from avos_cli.services.memory_client import AvosMemoryClient
from avos_cli.utils.logger import get_logger
from avos_cli.utils.output import print_error, print_info, print_json, print_success, print_warning, render_kv_panel

_log = get_logger("commands.session_start")

_MAX_GOAL_LENGTH = 1000
_STALE_THRESHOLD_SECONDS = 3600


class SessionStartOrchestrator:
    """Orchestrates the `avos session-start` command.

    Pipeline: validate config -> check active session -> sanitize goal ->
    create session state -> spawn watcher -> persist PID.

    Args:
        git_client: Local git operations wrapper.
        memory_client: Avos Memory API client.
        repo_root: Path to the repository root.
    """

    def __init__(
        self,
        git_client: GitClient,
        memory_client: AvosMemoryClient,
        repo_root: Path,
    ) -> None:
        self._git = git_client
        self._memory = memory_client
        self._repo_root = repo_root
        self._avos_dir = repo_root / ".avos"

    def run(self, goal: str, agent: str | None = None, json_output: bool = False) -> int:
        """Execute the session start flow.

        Args:
            goal: Developer-provided session goal description.
            agent: Optional custom agent/developer name. When provided,
                overrides git user.name for this session's identity in
                team views and WIP artifacts.
            json_output: If True, emit JSON output instead of human UI.

        Returns:
            Exit code: 0 success, 1 precondition, 2 external failure.
        """
        self._json_output = json_output

        try:
            config = load_config(self._repo_root)
        except ConfigurationNotInitializedError as e:
            self._emit_error("CONFIG_NOT_INITIALIZED", str(e), hint="Run 'avos connect org/repo' first.")
            return 1
        except AvosError as e:
            self._emit_error(e.code, str(e))
            return 1

        memory_id = config.memory_id_session
        effective_agent = (agent or "").strip() or None

        if self._git.is_worktree(self._repo_root) and not effective_agent:
            self._emit_error(
                "AGENT_REQUIRED",
                "In a git worktree, --agent is required to distinguish this session.",
                hint="Example: avos session-start --agent agentA \"your goal\"",
            )
            return 1

        guard_result = self._check_active_session()
        if guard_result == "blocked":
            self._emit_error(
                "SESSION_ACTIVE_CONFLICT",
                "A session is already active.",
                hint="Run 'avos session-end' first.",
            )
            return 1
        if guard_result == "cleaned":
            if not json_output:
                print_warning("Cleaned stale session state. Starting fresh.")

        sanitized_goal = self._sanitize_goal(goal)
        session_id = f"sess_{secrets.token_hex(8)}"

        try:
            branch = self._git.current_branch(self._repo_root)
        except AvosError as e:
            self._emit_error(e.code, str(e))
            return 1

        start_time = datetime.now(tz=timezone.utc).isoformat()
        session_state: dict[str, object] = {
            "session_id": session_id,
            "goal": sanitized_goal,
            "start_time": start_time,
            "branch": branch,
            "memory_id": memory_id,
        }
        if effective_agent:
            session_state["developer"] = effective_agent

        self._avos_dir.mkdir(parents=True, exist_ok=True)
        atomic_write(
            self._avos_dir / "session.json",
            json.dumps(session_state, indent=2),
        )

        try:
            watcher_pid = self._spawn_watcher(session_id, branch)
        except Exception as e:
            _log.error("Watcher spawn failed: %s", e)
            self._emit_error("WATCHER_SPAWN_FAILED", f"Could not start watcher: {e}")
            self._rollback_session_state()
            return 1

        pid_state = {
            "pid": watcher_pid,
            "started_at": datetime.now(tz=timezone.utc).isoformat(),
            "session_id": session_id,
        }
        atomic_write(
            self._avos_dir / "watcher.pid",
            json.dumps(pid_state, indent=2),
        )

        if json_output:
            print_json(
                success=True,
                data={
                    "session_id": session_id,
                    "goal": sanitized_goal,
                    "branch": branch,
                    "agent": effective_agent,
                    "started_at": start_time,
                },
                error=None,
            )
        else:
            panel_pairs: list[tuple[str, str]] = [
                ("Goal", sanitized_goal),
                ("Branch", branch),
            ]
            if effective_agent:
                panel_pairs.append(("Agent", effective_agent))
            panel_pairs.append(("Next", "avos session-end"))

            render_kv_panel(
                f"Session Started: {session_id}",
                panel_pairs,
                style="success",
            )
        return 0

    def _emit_error(
        self, code: str, message: str, hint: str | None = None, retryable: bool = False
    ) -> None:
        """Emit error in JSON or human format based on mode."""
        if self._json_output:
            print_json(
                success=False,
                data=None,
                error={"code": code, "message": message, "hint": hint, "retryable": retryable},
            )
        else:
            print_error(f"[{code}] {message}")

    def _check_active_session(self) -> str:
        """Check for existing active session.

        Returns:
            'clear' if no session exists,
            'blocked' if a live session is running,
            'cleaned' if stale state was removed.
        """
        session_path = self._avos_dir / "session.json"
        if not session_path.exists():
            return "clear"

        pid_path = self._avos_dir / "watcher.pid"
        pid_data = read_json_safe(pid_path)

        if pid_data is not None:
            pid = int(pid_data.get("pid", -1))
            if pid > 0 and self._pid_alive(pid):
                return "blocked"

        self._cleanup_stale_state()
        return "cleaned"

    def _cleanup_stale_state(self) -> None:
        """Remove stale session files from a previous incomplete session."""
        for filename in ("session.json", "watcher.pid", "session_checkpoints.jsonl"):
            path = self._avos_dir / filename
            if path.exists():
                try:
                    path.unlink()
                    _log.info("Removed stale file: %s", filename)
                except OSError as e:
                    _log.warning("Could not remove stale file %s: %s", filename, e)

    def _sanitize_goal(self, goal: str) -> str:
        """Sanitize user-provided goal text.

        Strips control characters and limits length to prevent injection
        and storage abuse.
        """
        cleaned = "".join(
            ch for ch in goal
            if unicodedata.category(ch)[0] != "C" or ch in ("\n", "\t")
        )
        return cleaned.strip()[:_MAX_GOAL_LENGTH]

    def _spawn_watcher(self, session_id: str, branch: str) -> int:
        """Spawn the watcher as a detached background process.

        Returns the PID of the spawned process.
        Raises OSError if spawn fails or process exits immediately.
        """
        checkpoint_path = self._avos_dir / "session_checkpoints.jsonl"

        proc = subprocess.Popen(
            [
                sys.executable, "-m", "avos_cli.services.watcher",
                "--repo-root", str(self._repo_root),
                "--session-id", session_id,
                "--branch", branch,
                "--checkpoint-path", str(checkpoint_path),
            ],
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        time.sleep(0.1)
        if proc.poll() is not None:
            raise OSError(
                f"Watcher process exited immediately with code {proc.returncode}"
            )

        _log.info("Watcher spawned with PID %d", proc.pid)
        return proc.pid

    def _rollback_session_state(self) -> None:
        """Remove session state files on spawn failure."""
        for filename in ("session.json", "watcher.pid"):
            path = self._avos_dir / filename
            if path.exists():
                try:
                    path.unlink()
                except OSError:
                    pass

    @staticmethod
    def _pid_alive(pid: int) -> bool:
        """Check if a process with the given PID is alive."""
        try:
            os.kill(pid, 0)
            return True
        except (OSError, ProcessLookupError):
            return False
