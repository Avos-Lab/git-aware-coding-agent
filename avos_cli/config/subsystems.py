"""Subsystem mapping loader for Tier-3 conflict enrichment (AVOS-021).

Reads optional .avos/subsystems.yml and resolves file paths to
subsystem tags. Missing or malformed mappings degrade safely to
an empty subsystem set without blocking command execution.

Public API:
    load_subsystem_mapping -- read and validate subsystems.yml
    resolve_subsystems     -- match a file path against loaded mapping
"""

from __future__ import annotations

from fnmatch import fnmatch
from pathlib import Path

from avos_cli.utils.logger import get_logger

_log = get_logger("config.subsystems")

_SUBSYSTEM_FILE = "subsystems.yml"


def load_subsystem_mapping(avos_dir: Path) -> dict[str, list[str]]:
    """Load subsystem mapping from .avos/subsystems.yml.

    Returns a dict of subsystem_name -> list of glob patterns.
    Missing, empty, or malformed files degrade to an empty dict.

    Args:
        avos_dir: Path to the .avos directory.

    Returns:
        Validated mapping dict, or empty dict on any failure.
    """
    path = avos_dir / _SUBSYSTEM_FILE
    if not path.is_file():
        return {}

    try:
        import yaml
    except ImportError:
        _log.warning("PyYAML not installed; subsystem mapping unavailable")
        return {}

    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        _log.warning("Cannot read subsystem mapping: %s", exc)
        return {}

    try:
        raw = yaml.safe_load(content)
    except yaml.YAMLError as exc:
        _log.warning("Malformed subsystems.yml: %s", exc)
        return {}

    if not isinstance(raw, dict):
        _log.warning("subsystems.yml top-level must be a dict, got %s", type(raw).__name__)
        return {}

    return _validate_mapping(raw)


def _validate_mapping(raw: dict) -> dict[str, list[str]]:
    """Validate and filter mapping entries.

    Keeps only entries where key is a string and value is a list of strings.

    Args:
        raw: Parsed YAML dict.

    Returns:
        Cleaned mapping with only valid entries.
    """
    result: dict[str, list[str]] = {}
    for key, value in raw.items():
        if not isinstance(key, str):
            _log.debug("Skipping non-string subsystem key: %r", key)
            continue
        if not isinstance(value, list):
            _log.debug("Skipping subsystem %r: value is not a list", key)
            continue
        patterns = [p for p in value if isinstance(p, str)]
        if patterns:
            result[key] = patterns
    return result


def resolve_subsystems(
    file_path: str,
    mapping: dict[str, list[str]],
) -> list[str]:
    """Resolve a file path to matching subsystem names.

    Uses fnmatch glob matching against each subsystem's patterns.
    Returns a sorted list for deterministic output.

    Args:
        file_path: Repository-relative file path string.
        mapping: Subsystem name -> glob patterns mapping.

    Returns:
        Sorted list of matching subsystem names.
    """
    if not file_path or not mapping:
        return []

    matched: list[str] = []
    for subsystem, patterns in mapping.items():
        for pattern in patterns:
            if _glob_match(file_path, pattern):
                matched.append(subsystem)
                break

    return sorted(matched)


def _glob_match(file_path: str, pattern: str) -> bool:
    """Match a file path against a glob pattern with ** support.

    fnmatch doesn't natively handle ** for recursive matching,
    so we handle it by checking path segments.

    Args:
        file_path: Repository-relative file path.
        pattern: Glob pattern (may contain ** for recursive match).

    Returns:
        True if the file path matches the pattern.
    """
    if "**" in pattern:
        prefix = pattern.split("**")[0].rstrip("/")
        if not prefix:
            return True
        return file_path.startswith(prefix + "/") or file_path == prefix

    return fnmatch(file_path, pattern)
