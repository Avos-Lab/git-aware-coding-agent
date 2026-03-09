"""Watch command orchestrator (AVOS-022).

Manages the lifecycle of a background WIP publisher process:
start (with duplicate prevention), stop (with bounded wait),
and stale PID cleanup.

Exit codes:
    0: success
    1: precondition failure (config missing, already running, not found)
    2: hard external failure
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from avos_cli.config.manager import load_config
from avos_cli.config.state import atomic_write, read_json_safe
from avos_cli.exceptions import AvosError, ConfigurationNotInitializedError
from avos_cli.utils.logger import get_logger
from avos_cli.utils.output import print_error, print_info, print_success, print_warning, render_kv_panel

_log = get_logger("commands.watch")

_STOP_WAIT_SECONDS = 5


class WatchOrchestrator:
    """Orchestrates the `avos watch` command.

    Pipeline:
        start: validate config -> check active watch -> spawn watcher -> write PID
        stop:  read PID -> verify alive -> SIGTERM -> wait -> cleanup

    Args:
        git_client: Local git operations wrapper.
        memory_client: Avos Memory API client.
        repo_root: Path to the repository root.
    """

    def __init__(
        self,
        git_client: object,
        memory_client: object,
        repo_root: Path,
    ) -> None:
        self._git = git_client
        self._memory = memory_client
        self._repo_root = repo_root
        self._avos_dir = repo_root / ".avos"

    def run(self, stop: bool = False) -> int:
        """Execute the watch command flow.

        Args:
            stop: If True, stop an active watch process.

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

        if stop:
            return self._handle_stop()
        return self._handle_start(config)

    def _handle_stop(self) -> int:
        """Stop an active watch process.

        Returns:
            0 on success, 1 if no active watch found.
        """
        pid_path = self._avos_dir / "watch.pid"
        pid_data = read_json_safe(pid_path)

        if pid_data is None:
            print_error("[WATCH_NOT_FOUND] No active watch process found.")
            return 1

        pid = int(pid_data.get("pid", -1))
        if pid <= 0 or not self._pid_alive(pid):
            self._cleanup_watch_state()
            print_error(
                "[WATCH_NOT_FOUND] No active watch process found (stale PID cleaned)."
            )
            return 1

        try:
            os.kill(pid, signal.SIGTERM)
            _log.info("Sent SIGTERM to watch process %d", pid)
        except OSError as e:
            _log.warning("Failed to send SIGTERM to %d: %s", pid, e)

        deadline = time.monotonic() + _STOP_WAIT_SECONDS
        while time.monotonic() < deadline:
            if not self._pid_alive(pid):
                break
            time.sleep(0.1)

        self._cleanup_watch_state()
        print_success("Watch stopped.")
        return 0

    def _handle_start(self, config: object) -> int:
        """Start a new watch process.

        Args:
            config: Loaded repo configuration.

        Returns:
            0 on success, 1 on precondition failure.
        """
        guard = self._check_active_watch()
        if guard == "blocked":
            print_error(
                "[WATCH_ACTIVE_CONFLICT] A watch process is already active. "
                "Run 'avos watch --stop' first."
            )
            return 1
        if guard == "cleaned":
            print_warning("Cleaned stale watch state. Starting fresh.")

        try:
            watcher_pid = self._spawn_watcher()
        except Exception as e:
            _log.error("Watch spawn failed: %s", e)
            print_error(f"[WATCHER_SPAWN_FAILED] Could not start watch: {e}")
            self._cleanup_watch_state()
            return 1

        pid_state = {
            "pid": watcher_pid,
            "started_at": datetime.now(tz=timezone.utc).isoformat(),
            "repo_root": str(self._repo_root),
        }
        self._avos_dir.mkdir(parents=True, exist_ok=True)
        atomic_write(
            self._avos_dir / "watch.pid",
            json.dumps(pid_state, indent=2),
        )

        render_kv_panel(
            f"Watch Started (PID {watcher_pid})",
            [
                ("Status", "Publishing WIP activity to team memory"),
                ("Stop", "avos watch --stop"),
            ],
            style="success",
        )
        return 0

    def _check_active_watch(self) -> str:
        """Check for an existing active watch process.

        Returns:
            'clear' if no watch exists,
            'blocked' if a live watch is running,
            'cleaned' if stale state was removed.
        """
        pid_path = self._avos_dir / "watch.pid"
        pid_data = read_json_safe(pid_path)

        if pid_data is None:
            if pid_path.exists():
                self._cleanup_watch_state()
                return "cleaned"
            return "clear"

        pid = int(pid_data.get("pid", -1))
        if pid > 0 and self._pid_alive(pid):
            return "blocked"

        self._cleanup_watch_state()
        return "cleaned"

    def _cleanup_watch_state(self) -> None:
        """Remove watch state files."""
        for filename in ("watch.pid", "watch_state.json"):
            path = self._avos_dir / filename
            if path.exists():
                try:
                    path.unlink()
                    _log.info("Removed watch file: %s", filename)
                except OSError as e:
                    _log.warning("Could not remove %s: %s", filename, e)

    def _spawn_watcher(self) -> int:
        """Spawn the watch watcher as a detached background process.

        Returns the PID of the spawned process.
        Raises OSError if spawn fails or process exits immediately.
        """
        proc = subprocess.Popen(
            [
                sys.executable, "-m", "avos_cli.services.watch_watcher",
                "--repo-root", str(self._repo_root),
            ],
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        time.sleep(0.1)
        if proc.poll() is not None:
            raise OSError(
                f"Watch process exited immediately with code {proc.returncode}"
            )

        _log.info("Watch watcher spawned with PID %d", proc.pid)
        return proc.pid

    @staticmethod
    def _pid_alive(pid: int) -> bool:
        """Check if a process with the given PID is alive."""
        try:
            os.kill(pid, 0)
            return True
        except (OSError, ProcessLookupError):
            return False
