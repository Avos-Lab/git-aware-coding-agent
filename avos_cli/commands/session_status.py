"""Session status command orchestrator.

Read-only command that reports whether a session is currently active.
Agents use this before calling session-start to avoid conflicts.

Exit codes:
    0: success (status reported)
    1: precondition failure (config missing)
"""

from __future__ import annotations

import os
from pathlib import Path

from avos_cli.config.manager import load_config
from avos_cli.config.state import read_json_safe
from avos_cli.exceptions import AvosError, ConfigurationNotInitializedError
from avos_cli.utils.logger import get_logger
from avos_cli.utils.output import print_error, print_info, print_json, render_kv_panel

_log = get_logger("commands.session_status")


class SessionStatusOrchestrator:
    """Orchestrates the `avos session-status` command.

    Read-only: checks .avos/session.json and .avos/watcher.pid to determine
    if a session is active.

    Args:
        repo_root: Path to the repository root.
    """

    def __init__(self, repo_root: Path) -> None:
        self._repo_root = repo_root
        self._avos_dir = repo_root / ".avos"

    def run(self, json_output: bool = False) -> int:
        """Execute the session status check.

        Args:
            json_output: If True, emit JSON output instead of human UI.

        Returns:
            Exit code: 0 success, 1 precondition failure.
        """
        try:
            load_config(self._repo_root)
        except ConfigurationNotInitializedError as e:
            if json_output:
                print_json(
                    success=False,
                    data=None,
                    error={
                        "code": "CONFIG_NOT_INITIALIZED",
                        "message": str(e),
                        "hint": "Run 'avos connect org/repo' first.",
                        "retryable": False,
                    },
                )
            else:
                print_error(f"[CONFIG_NOT_INITIALIZED] {e}")
            return 1
        except AvosError as e:
            if json_output:
                print_json(
                    success=False,
                    data=None,
                    error={
                        "code": e.code,
                        "message": str(e),
                        "hint": getattr(e, "hint", None),
                        "retryable": getattr(e, "retryable", False),
                    },
                )
            else:
                print_error(f"[{e.code}] {e}")
            return 1

        session_path = self._avos_dir / "session.json"
        pid_path = self._avos_dir / "watcher.pid"

        session_data = read_json_safe(session_path)

        if session_data is None:
            result = {
                "active": False,
                "session_id": None,
                "goal": None,
                "branch": None,
                "started_at": None,
                "agent": None,
                "watcher_alive": False,
            }
            if json_output:
                print_json(success=True, data=result, error=None)
            else:
                print_info("No active session.")
            return 0

        session_id = str(session_data.get("session_id", ""))
        goal = str(session_data.get("goal", ""))
        branch = str(session_data.get("branch", ""))
        started_at = str(session_data.get("start_time", ""))
        agent = session_data.get("developer")

        pid_data = read_json_safe(pid_path)
        watcher_alive = False
        if pid_data is not None:
            pid = int(pid_data.get("pid", -1))
            if pid > 0:
                watcher_alive = self._pid_alive(pid)

        result = {
            "active": True,
            "session_id": session_id,
            "goal": goal,
            "branch": branch,
            "started_at": started_at,
            "agent": agent if agent else None,
            "watcher_alive": watcher_alive,
        }

        if json_output:
            print_json(success=True, data=result, error=None)
        else:
            kv_pairs: list[tuple[str, str]] = [
                ("Session ID", session_id),
                ("Goal", goal),
                ("Branch", branch),
                ("Started", started_at),
            ]
            if agent:
                kv_pairs.append(("Agent", str(agent)))
            kv_pairs.append(("Watcher", "alive" if watcher_alive else "dead"))

            render_kv_panel("Active Session", kv_pairs, style="info")

        return 0

    @staticmethod
    def _pid_alive(pid: int) -> bool:
        """Check if a process with the given PID is alive."""
        try:
            os.kill(pid, 0)
            return True
        except (OSError, ProcessLookupError):
            return False
