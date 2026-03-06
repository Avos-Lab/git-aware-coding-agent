"""Atomic file I/O and corruption handling for .avos state files.

Provides safe write (temp + fsync + rename) and safe read (with
corruption detection and quarantine) for JSON state files.
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
import time
from pathlib import Path

from avos_cli.utils.logger import get_logger

_log = get_logger("config.state")


def atomic_write(path: Path, content: str, permissions: int = 0o600) -> None:
    """Write content to a file atomically using temp+fsync+rename.

    Args:
        path: Target file path.
        content: String content to write.
        permissions: File permission mode (default 0o600 for secrets).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        dir=str(path.parent),
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    try:
        os.write(fd, content.encode("utf-8"))
        os.fsync(fd)
        os.close(fd)
        os.chmod(tmp_path, permissions)
        os.replace(tmp_path, str(path))
    except BaseException:
        os.close(fd) if not _is_fd_closed(fd) else None
        with contextlib.suppress(OSError):
            os.unlink(tmp_path)
        raise


def _is_fd_closed(fd: int) -> bool:
    """Check if a file descriptor is already closed."""
    try:
        os.fstat(fd)
        return False
    except OSError:
        return True


def read_json_safe(path: Path) -> dict[str, object] | None:
    """Read and parse a JSON file, quarantining corrupt files.

    If the file doesn't exist, returns None.
    If the file contains invalid JSON, it is renamed to
    `<name>.corrupt.<timestamp>` and None is returned.

    Args:
        path: Path to the JSON file.

    Returns:
        Parsed dict or None if missing/corrupt.
    """
    if not path.exists():
        return None

    try:
        content = path.read_text(encoding="utf-8")
        data: dict[str, object] = json.loads(content)
        return data
    except (json.JSONDecodeError, UnicodeDecodeError):
        _quarantine(path)
        return None


def _quarantine(path: Path) -> None:
    """Move a corrupt file to a .corrupt.<timestamp> backup."""
    ts = int(time.time())
    corrupt_path = path.with_suffix(f"{path.suffix}.corrupt.{ts}")
    try:
        path.rename(corrupt_path)
        _log.warning("Quarantined corrupt file: %s -> %s", path, corrupt_path)
    except OSError as e:
        _log.error("Failed to quarantine corrupt file %s: %s", path, e)
