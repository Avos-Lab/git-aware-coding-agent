"""Team activity command orchestrator (AVOS-023).

Retrieves active WIP artifacts from Avos Memory, filters by TTL,
groups by developer, and renders a deterministic team awareness view.

Exit codes:
    0: success (including empty state or degraded)
    1: precondition failure (config missing)
    2: hard external failure (API unreachable)
"""

from __future__ import annotations

import re
from pathlib import Path

from avos_cli.config.manager import load_config
from avos_cli.exceptions import AvosError, ConfigurationNotInitializedError
from avos_cli.models.api import SearchHit
from avos_cli.utils.logger import get_logger
from avos_cli.utils.output import print_error, print_info, print_success, print_warning
from avos_cli.utils.time_helpers import is_artifact_active

_log = get_logger("commands.team")

_WIP_SEARCH_K = 50
_ACTIVE_TTL_HOURS = 24

_TAG_RE = re.compile(r"^\[(\w+):\s*(.*?)\]\s*$")
_KV_RE = re.compile(r"^(\w+):\s*(.+)$")


class TeamOrchestrator:
    """Orchestrates the `avos team` command.

    Pipeline: load config -> search WIP artifacts -> TTL filter ->
    group by developer -> deterministic sort -> render output.

    Args:
        memory_client: Avos Memory API client.
        repo_root: Path to the repository root.
    """

    def __init__(self, memory_client: object, repo_root: Path) -> None:
        self._memory = memory_client
        self._repo_root = repo_root
        self._avos_dir = repo_root / ".avos"

    def run(self) -> int:
        """Execute the team activity view flow.

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

        memory_id = config.memory_id

        try:
            result = self._memory.search(
                memory_id, "wip_activity", k=_WIP_SEARCH_K, mode="keyword"
            )
        except AvosError as e:
            if e.retryable:
                print_error(f"[{e.code}] {e}")
                return 2
            print_error(f"[{e.code}] {e}")
            return 2

        artifacts = self._parse_artifacts(result.results)
        active = self._filter_active(artifacts)

        if not active:
            print_info(
                "No active team activity. Run 'avos watch' to start publishing."
            )
            return 0

        grouped = self._group_by_developer(active)
        self._render(grouped)
        return 0

    def _parse_artifacts(
        self, hits: list[SearchHit]
    ) -> list[dict[str, str]]:
        """Parse WIP artifact content from search hits.

        Tolerant parsing: malformed entries are skipped with a warning.

        Args:
            hits: Search result hits from memory.

        Returns:
            List of parsed artifact dicts with at least developer/branch/timestamp.
        """
        parsed: list[dict[str, str]] = []
        for hit in hits:
            artifact = _parse_wip_content(hit.content)
            if artifact is None:
                _log.debug("Skipping unparseable artifact %s", hit.note_id)
                continue
            artifact["_note_id"] = hit.note_id
            parsed.append(artifact)
        return parsed

    def _filter_active(
        self, artifacts: list[dict[str, str]]
    ) -> list[dict[str, str]]:
        """Filter artifacts by TTL window.

        Args:
            artifacts: Parsed artifact dicts.

        Returns:
            Only artifacts within the active TTL window.
        """
        active: list[dict[str, str]] = []
        for art in artifacts:
            ts = art.get("timestamp", "")
            if not ts:
                continue
            if is_artifact_active(
                ts,
                _ACTIVE_TTL_HOURS,
                artifact_id=art.get("_note_id", ""),
                command_context="team",
            ):
                active.append(art)
        return active

    def _group_by_developer(
        self, artifacts: list[dict[str, str]]
    ) -> list[tuple[str, list[dict[str, str]]]]:
        """Group artifacts by normalized developer name.

        Sorting: groups by developer_normalized ASC,
        entries within by timestamp DESC, branch_normalized ASC, artifact_id ASC.

        Args:
            artifacts: Active artifact dicts.

        Returns:
            Sorted list of (developer, entries) tuples.
        """
        groups: dict[str, list[dict[str, str]]] = {}
        for art in artifacts:
            dev = art.get("developer", "unknown").strip().lower()
            groups.setdefault(dev, []).append(art)

        for entries in groups.values():
            entries.sort(
                key=lambda a: (
                    a.get("timestamp", "") or "",
                    a.get("branch", "").strip().lower(),
                    a.get("_note_id", ""),
                ),
            )
            entries.reverse()
            entries.sort(
                key=lambda a: (
                    -(ord(a.get("timestamp", " ")[0]) if a.get("timestamp") else 0),
                ),
            )
            entries.sort(
                key=lambda a: (
                    a.get("branch", "").strip().lower(),
                    a.get("_note_id", ""),
                ),
            )
            entries.sort(key=lambda a: a.get("timestamp", ""), reverse=True)

        sorted_groups = sorted(groups.items(), key=lambda g: g[0])
        return sorted_groups

    def _render(
        self, grouped: list[tuple[str, list[dict[str, str]]]]
    ) -> None:
        """Render team activity output.

        Args:
            grouped: Sorted (developer, entries) tuples.
        """
        print_success(f"Active team members: {len(grouped)}")
        for dev, entries in grouped:
            display_name = entries[0].get("developer", dev) if entries else dev
            print_info(f"\n  {display_name}:")
            for art in entries:
                branch = art.get("branch", "?")
                ts = art.get("timestamp", "?")
                files_str = art.get("files", "")
                files_list = [f.strip() for f in files_str.split(",") if f.strip()] if files_str else []
                file_count = len(files_list)
                print_info(f"    [{branch}] {file_count} file(s) @ {ts}")


def _parse_wip_content(content: str) -> dict[str, str] | None:
    """Parse WIP artifact structured text into a dict.

    Expected format from WIPBuilder:
        [type: wip_activity]
        [developer: Alice]
        [branch: feature/auth]
        [timestamp: 2026-03-07T10:00:00+00:00]
        Files: src/auth.py, src/models.py
        ...

    Returns None if required fields (developer, branch, timestamp) are missing.

    Args:
        content: Raw artifact text content.

    Returns:
        Dict with parsed fields, or None if unparseable.
    """
    data: dict[str, str] = {}
    for line in content.splitlines():
        line = line.strip()
        if not line:
            continue
        tag_match = _TAG_RE.match(line)
        if tag_match:
            key, value = tag_match.group(1), tag_match.group(2)
            data[key.lower()] = value
            continue
        kv_match = _KV_RE.match(line)
        if kv_match:
            key, value = kv_match.group(1), kv_match.group(2)
            data[key.lower()] = value

    required = ("developer", "branch", "timestamp")
    if not all(data.get(k) for k in required):
        return None

    return data
