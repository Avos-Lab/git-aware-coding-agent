"""Background WIP publisher for `avos watch` (AVOS-022).

Runs as a separate OS process spawned by the watch command. Observes
file changes, applies significance filtering, enriches with symbols
and subsystems, builds WIP artifacts, and publishes to Avos Memory.

Reuses observer/signal infrastructure from the session watcher.

Security contract:
    - Only repository-relative paths are recorded (no absolute paths)
    - Path traversal is rejected
    - No raw source code is ever captured
    - Metadata-only WIP payloads
"""

from __future__ import annotations

import json
import os
import random
import signal
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from avos_cli.utils.logger import get_logger

_log = get_logger("services.watch_watcher")

_PUBLISH_INTERVAL_SEC = 300.0
_RETRY_MAX = 3
_RETRY_BACKOFF = [2, 4, 8]
_RETRY_JITTER_PERCENT = 0.20
_RETRY_BUDGET_SEC = 20
_LOCK_TIMEOUT_SEC = 2


def run_watch_watcher(
    repo_root: Path,
    publish_interval: float = _PUBLISH_INTERVAL_SEC,
    _shutdown_event: threading.Event | None = None,
) -> None:
    """Main watch watcher loop for WIP publishing.

    Observes filesystem changes, applies significance filtering,
    enriches with symbols/subsystems, and publishes WIP artifacts.

    Args:
        repo_root: Repository root directory.
        publish_interval: Seconds between publish cycles.
        _shutdown_event: Optional event for testability.
    """
    from avos_cli.artifacts.wip_builder import WIPBuilder
    from avos_cli.config.manager import load_config
    from avos_cli.config.state import atomic_write, read_json_safe
    from avos_cli.config.subsystems import load_subsystem_mapping, resolve_subsystems
    from avos_cli.models.artifacts import WIPArtifact
    from avos_cli.services.git_client import GitClient
    from avos_cli.services.memory_client import AvosMemoryClient
    from avos_cli.services.symbol_extractor import extract_symbols

    shutdown = _shutdown_event or threading.Event()
    changed_paths: set[str] = set()
    lock = threading.Lock()

    if _shutdown_event is None:
        _setup_signal_handlers(shutdown)

    try:
        config = load_config(repo_root)
    except Exception as exc:
        _log.error("Cannot load config: %s", exc)
        return

    api_key = config.api_key.get_secret_value()
    api_url = config.api_url
    memory_id = config.memory_id
    developer = config.developer or ""

    if not developer:
        try:
            git = GitClient()
            developer = git.user_name(repo_root)
        except Exception:
            developer = "unknown"

    try:
        git = GitClient()
        branch = git.current_branch(repo_root)
    except Exception:
        branch = "unknown"

    try:
        memory_client = AvosMemoryClient(api_key=api_key, api_url=api_url)
    except Exception as exc:
        _log.error("Cannot create memory client: %s", exc)
        return

    avos_dir = repo_root / ".avos"
    subsystem_mapping = load_subsystem_mapping(avos_dir)
    wip_builder = WIPBuilder()

    observer = _create_observer(repo_root, changed_paths, lock)
    if observer is not None:
        observer.start()

    try:
        while not shutdown.is_set():
            shutdown.wait(timeout=publish_interval)

            with lock:
                snapshot = set(changed_paths)
                changed_paths.clear()

            normalized = _normalize_paths(snapshot, repo_root)
            if not normalized:
                continue

            symbols: list[str] = []
            modules: set[str] = set()
            subsystems: set[str] = set()
            for fp in normalized:
                abs_path = repo_root / fp
                file_symbols = extract_symbols(abs_path, repo_root)
                symbols.extend(file_symbols)
                mod = _derive_module(fp)
                if mod:
                    modules.add(mod)
                file_subs = resolve_subsystems(fp, subsystem_mapping)
                for s in file_subs:
                    subsystems.add(s)

            try:
                git = GitClient()
                diff_stats = git.diff_stats(repo_root)
            except Exception:
                diff_stats = ""

            artifact = WIPArtifact(
                developer=developer,
                branch=branch,
                timestamp=datetime.now(tz=timezone.utc).isoformat(),
                intent=f"Working on {branch}",
                files_touched=sorted(normalized),
                diff_stats=diff_stats or None,
                symbols_touched=sorted(set(symbols)),
                modules_touched=sorted(modules),
                subsystems_touched=sorted(subsystems),
            )

            content = wip_builder.build(artifact)
            _publish_with_retry(memory_client, memory_id, content)

            _update_watch_state(avos_dir, developer, branch, normalized)

    finally:
        if observer is not None:
            observer.stop()
            observer.join(timeout=3)
        _log.info("Watch watcher stopped")


def _setup_signal_handlers(shutdown_event: threading.Event) -> None:
    """Register SIGTERM/SIGINT handlers for graceful shutdown."""
    def _handler(signum: int, frame: Any) -> None:
        _log.info("Received signal %d, shutting down watch watcher", signum)
        shutdown_event.set()

    signal.signal(signal.SIGTERM, _handler)
    signal.signal(signal.SIGINT, _handler)


def _create_observer(
    repo_root: Path,
    changed_paths: set[str],
    lock: threading.Lock,
) -> Any | None:
    """Create a filesystem observer (reuses session watcher pattern)."""
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
        return observer
    except (ImportError, OSError) as exc:
        _log.warning("Watchdog unavailable (%s), running without observer", exc)
        return None


def _normalize_paths(paths: set[str], repo_root: Path) -> list[str]:
    """Normalize paths to repo-relative POSIX strings, rejecting traversal."""
    result: list[str] = []
    repo_resolved = repo_root.resolve()
    for p in sorted(paths):
        try:
            resolved = Path(p).resolve()
            relative = resolved.relative_to(repo_resolved)
            posix = relative.as_posix()
            if ".." in posix.split("/"):
                continue
            result.append(posix)
        except (ValueError, OSError):
            continue
    return result


def _derive_module(file_path: str) -> str:
    """Derive a module name from a file path."""
    parts = file_path.replace("\\", "/").split("/")
    if parts and "." in parts[-1]:
        parts[-1] = parts[-1].rsplit(".", 1)[0]
    return ".".join(parts) if parts else ""


def _publish_with_retry(
    memory_client: Any,
    memory_id: str,
    content: str,
) -> bool:
    """Publish WIP content with retry policy (1+3, backoff [2,4,8]s, jitter +/-20%).

    Args:
        memory_client: Avos Memory API client.
        memory_id: Target memory identifier.
        content: WIP artifact text.

    Returns:
        True if published successfully, False on exhaustion.
    """
    start = time.monotonic()
    for attempt in range(_RETRY_MAX + 1):
        if time.monotonic() - start > _RETRY_BUDGET_SEC:
            _log.warning("Publish retry budget exhausted")
            return False
        try:
            memory_client.add_memory(memory_id, content=content)
            return True
        except Exception as exc:
            _log.warning("Publish attempt %d failed: %s", attempt + 1, exc)
            if attempt < _RETRY_MAX:
                backoff = _RETRY_BACKOFF[attempt] if attempt < len(_RETRY_BACKOFF) else _RETRY_BACKOFF[-1]
                jitter = backoff * _RETRY_JITTER_PERCENT * (2 * random.random() - 1)
                wait = max(0.1, backoff + jitter)
                time.sleep(wait)
    return False


def _update_watch_state(
    avos_dir: Path,
    developer: str,
    branch: str,
    files: list[str],
) -> None:
    """Update .avos/watch_state.json atomically."""
    from avos_cli.config.state import atomic_write
    state = {
        "developer": developer,
        "branch": branch,
        "last_publish_time": datetime.now(tz=timezone.utc).isoformat(),
        "files_tracked": files,
    }
    try:
        atomic_write(
            avos_dir / "watch_state.json",
            json.dumps(state, indent=2),
        )
    except Exception as exc:
        _log.warning("Failed to update watch state: %s", exc)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="AVOS watch watcher")
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--interval", type=float, default=_PUBLISH_INTERVAL_SEC)
    args = parser.parse_args()

    run_watch_watcher(
        repo_root=Path(args.repo_root),
        publish_interval=args.interval,
    )
