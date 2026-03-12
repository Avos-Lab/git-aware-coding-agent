"""Background watcher service for session checkpoint capture (AVOS-016).

Runs as a separate OS process spawned by session-start. Observes file
changes in the repository and periodically writes metadata-only checkpoint
records to .avos/session_checkpoints.jsonl.

Public API:
    run_watcher     -- main entry point for the spawned process
    parse_checkpoints -- tolerant JSONL reader used by session-end

Security contract:
    - Only repository-relative paths are recorded (no absolute paths)
    - Path traversal (.. components) is rejected
    - Command detection captures names only, never arguments
    - No raw source code is ever captured
"""

from __future__ import annotations

import json
import signal
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from avos_cli.models.config import SessionCheckpoint
from avos_cli.utils.logger import get_logger

_log = get_logger("services.watcher")

try:
    import psutil  # type: ignore[import-untyped]
except ImportError:
    psutil = None

_TEST_CMD_PATTERNS = frozenset({
    "pytest", "python -m pytest", "unittest", "python -m unittest",
    "npm test", "npx jest", "jest", "mocha", "cargo test", "go test",
    "make test", "tox",
})


def run_watcher(
    repo_root: Path,
    session_id: str,
    branch: str,
    checkpoint_path: Path,
    interval: float = 30.0,
    _shutdown_event: threading.Event | None = None,
) -> None:
    """Main watcher loop. Intended to run in a spawned subprocess.

    Observes filesystem changes, aggregates them per interval, and appends
    checkpoint records to the JSONL file. Exits cleanly on SIGTERM or when
    the shutdown event is set.

    Args:
        repo_root: Repository root directory to watch.
        session_id: Owning session identifier.
        branch: Git branch at session start.
        checkpoint_path: Path to the JSONL checkpoint file.
        interval: Seconds between checkpoint writes.
        _shutdown_event: Optional event for testability (replaces signal).
    """
    shutdown = _shutdown_event or threading.Event()
    changed_paths: set[str] = set()
    lock = threading.Lock()

    if _shutdown_event is None:
        _setup_signal_handlers(shutdown)

    observer = _create_observer(repo_root, changed_paths, lock)
    if observer is not None:
        observer.start()

    try:
        while not shutdown.is_set():
            shutdown.wait(timeout=interval)

            with lock:
                snapshot = set(changed_paths)
                changed_paths.clear()

            normalized: list[str] = []
            for p in sorted(snapshot):
                norm = _normalize_path(p, repo_root)
                if norm is not None:
                    normalized.append(norm)

            test_cmds = _detect_test_commands()
            _write_checkpoint(
                checkpoint_path=checkpoint_path,
                session_id=session_id,
                branch=branch,
                files=normalized,
                diff_stats={},
                test_cmds=test_cmds,
                errors=[],
            )
    finally:
        if observer is not None:
            observer.stop()
            observer.join(timeout=3)
        _log.info("Watcher stopped for session %s", session_id)


def _setup_signal_handlers(shutdown_event: threading.Event) -> None:
    """Register SIGTERM handler for graceful shutdown."""
    def _handler(signum: int, frame: Any) -> None:
        _log.info("Received signal %d, initiating graceful shutdown", signum)
        shutdown_event.set()

    signal.signal(signal.SIGTERM, _handler)
    signal.signal(signal.SIGINT, _handler)


def _create_observer(
    repo_root: Path,
    changed_paths: set[str],
    lock: threading.Lock,
) -> Any | None:
    """Create a filesystem observer. Returns None if watchdog unavailable.

    Tries watchdog event-based observer first, falls back gracefully.
    """
    try:
        from watchdog.events import FileSystemEventHandler
        from watchdog.observers import Observer

        class _Handler(FileSystemEventHandler):
            def on_any_event(self, event: Any) -> None:
                if event.is_directory:
                    return
                src = getattr(event, "src_path", None)
                if src and ".avos" not in src:
                    with lock:
                        changed_paths.add(src)

        observer = Observer()
        observer.schedule(_Handler(), str(repo_root), recursive=True)
        _log.info("Using watchdog event-based observer")
        return observer
    except (ImportError, OSError) as exc:
        _log.warning("Watchdog unavailable (%s), running without observer", exc)
        return None


def _write_checkpoint(
    checkpoint_path: Path,
    session_id: str,
    branch: str,
    files: list[str],
    diff_stats: dict[str, int],
    test_cmds: list[str],
    errors: list[str],
) -> None:
    """Append a single checkpoint record as one JSONL line.

    Uses append mode with explicit flush for crash safety.
    """
    record = {
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        "session_id": session_id,
        "branch": branch,
        "files_modified": files,
        "diff_stats": diff_stats,
        "test_commands_detected": test_cmds,
        "errors_detected": errors,
    }
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    with open(checkpoint_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, separators=(",", ":")) + "\n")
        f.flush()


def _normalize_path(path_str: str, repo_root: Path) -> str | None:
    """Normalize a filesystem path to a repository-relative POSIX string.

    Returns None if the path escapes the repository root (traversal attack)
    or cannot be made relative.

    Args:
        path_str: Absolute or relative path string.
        repo_root: Repository root directory.

    Returns:
        POSIX-style relative path string, or None if rejected.
    """
    try:
        resolved = Path(path_str).resolve()
        repo_resolved = repo_root.resolve()
        relative = resolved.relative_to(repo_resolved)
        posix = relative.as_posix()
        if ".." in posix.split("/"):
            return None
        return posix
    except (ValueError, OSError):
        return None


def _detect_test_commands() -> list[str]:
    """Detect running test commands from the process list.

    Returns command names only (never arguments) for security.
    Uses psutil if available; returns empty list otherwise.
    """
    if psutil is None:
        return []

    detected: set[str] = set()
    try:
        for proc in psutil.process_iter(["cmdline"]):
            try:
                cmdline = proc.info.get("cmdline") or []
                if not cmdline:
                    continue
                cmd_str = " ".join(cmdline[:3]).lower()
                for pattern in _TEST_CMD_PATTERNS:
                    if pattern in cmd_str:
                        detected.add(pattern)
                        break
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    except Exception:
        _log.debug("Process scan failed", exc_info=True)

    return sorted(detected)


def parse_checkpoints(checkpoint_path: Path) -> tuple[list[SessionCheckpoint], int]:
    """Parse checkpoint JSONL file with malformed-line tolerance.

    Each line is parsed independently. Invalid lines are skipped and
    counted as warnings. Blank lines are ignored silently.

    Args:
        checkpoint_path: Path to the JSONL checkpoint file.

    Returns:
        Tuple of (valid checkpoints list, malformed line count).
    """
    if not checkpoint_path.exists():
        return [], 0

    checkpoints: list[SessionCheckpoint] = []
    malformed_count = 0

    try:
        content = checkpoint_path.read_text(encoding="utf-8")
    except OSError as exc:
        _log.warning("Cannot read checkpoint file: %s", exc)
        return [], 0

    for line_num, line in enumerate(content.splitlines(), 1):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            data = json.loads(stripped)
            cp = SessionCheckpoint(**data)
            checkpoints.append(cp)
        except (json.JSONDecodeError, Exception) as exc:
            _log.warning("Skipping malformed checkpoint line %d: %s", line_num, exc)
            malformed_count += 1

    return checkpoints, malformed_count


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="AVOS session watcher")
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--branch", required=True)
    parser.add_argument("--checkpoint-path", required=True)
    parser.add_argument("--interval", type=float, default=30.0)
    args = parser.parse_args()

    run_watcher(
        repo_root=Path(args.repo_root),
        session_id=args.session_id,
        branch=args.branch,
        checkpoint_path=Path(args.checkpoint_path),
        interval=args.interval,
    )
