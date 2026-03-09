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
from avos_cli.utils.output import (
    console,
    is_interactive,
    print_error,
    print_info,
    print_json,
    render_table,
    render_tree,
)
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

    def run(
        self,
        detail: bool = False,
        live: bool = False,
        json_output: bool = False,
    ) -> int:
        """Execute the team activity view flow.

        Args:
            detail: Show tree view with files and symbols per developer.
            live: Auto-refresh display every 30 seconds.
            json_output: Emit JSON envelope instead of Rich output.

        Returns:
            Exit code: 0 success, 1 precondition, 2 external failure.
        """
        if live:
            return self._run_live(detail, json_output)

        return self._run_once(detail, json_output)

    def _run_once(self, detail: bool = False, json_output: bool = False) -> int:
        """Single-shot team view."""
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
            if json_output:
                print_json(success=True, data={"members": [], "count": 0})
            else:
                print_info(
                    "No active team activity. Run 'avos watch' to start publishing."
                )
            return 0

        grouped = self._group_by_developer(active)

        if json_output:
            self._render_json(grouped)
        elif detail:
            self._render_detail(grouped)
        else:
            self._render(grouped)
        return 0

    def _run_live(self, detail: bool = False, json_output: bool = False) -> int:
        """Auto-refreshing team view using Rich Live."""
        if json_output:
            print_error("Live mode is not compatible with --json output.")
            return 1
        if not is_interactive():
            print_error("Live mode requires an interactive terminal.")
            return 1

        from avos_cli.utils.output import render_live_loop

        def _build_renderable() -> object:
            from rich.table import Table as RichTable
            try:
                config = load_config(self._repo_root)
                result = self._memory.search(
                    config.memory_id, "wip_activity", k=_WIP_SEARCH_K, mode="keyword"
                )
                artifacts = self._parse_artifacts(result.results)
                active = self._filter_active(artifacts)
                grouped = self._group_by_developer(active)
            except Exception:
                table = RichTable(title="Active Development (error fetching)")
                table.add_column("Status")
                table.add_row("Could not fetch team data")
                return table

            if not grouped:
                table = RichTable(title="Active Development (0 members)")
                table.add_column("Status")
                table.add_row("No active team activity")
                return table

            return self._build_table(grouped) if not detail else self._build_tree(grouped)

        try:
            render_live_loop(_build_renderable, interval=30.0)
        except RuntimeError as e:
            print_error(str(e))
            return 1
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
        """Render team activity as a Rich table.

        Args:
            grouped: Sorted (developer, entries) tuples.
        """
        if is_interactive():
            table = self._build_table(grouped)
            console.print(table)
        else:
            render_table(
                f"Active Development ({len(grouped)} members)",
                [("Developer", ""), ("Branch", ""), ("Files", ""), ("Updated", "")],
                self._grouped_to_rows(grouped),
            )

    def _render_detail(
        self, grouped: list[tuple[str, list[dict[str, str]]]]
    ) -> None:
        """Render team activity as a Rich tree with files and symbols.

        Args:
            grouped: Sorted (developer, entries) tuples.
        """
        if is_interactive():
            tree = self._build_tree(grouped)
            console.print(tree)
        else:
            children: list[tuple[str, list[str]]] = []
            for dev, entries in grouped:
                display_name = entries[0].get("developer", dev) if entries else dev
                for art in entries:
                    branch = art.get("branch", "?")
                    files_str = art.get("files", "")
                    symbols_str = art.get("symbols", "")
                    files_list = [f.strip() for f in files_str.split(",") if f.strip()]
                    symbols_list = [s.strip() for s in symbols_str.split(",") if s.strip()]
                    leaves: list[str] = []
                    for fp in files_list:
                        leaves.append(fp)
                    for sym in symbols_list:
                        leaves.append(f"  {sym}")
                    children.append((f"{display_name} ({branch})", leaves))
            render_tree("Active Development", children)

    def _render_json(
        self, grouped: list[tuple[str, list[dict[str, str]]]]
    ) -> None:
        """Emit team data as JSON envelope."""
        members: list[dict[str, object]] = []
        for dev, entries in grouped:
            display_name = entries[0].get("developer", dev) if entries else dev
            activities: list[dict[str, object]] = []
            for art in entries:
                files_str = art.get("files", "")
                files_list = [f.strip() for f in files_str.split(",") if f.strip()]
                symbols_str = art.get("symbols", "")
                symbols_list = [s.strip() for s in symbols_str.split(",") if s.strip()]
                activities.append({
                    "branch": art.get("branch", ""),
                    "timestamp": art.get("timestamp", ""),
                    "files": files_list,
                    "symbols": symbols_list,
                })
            members.append({"developer": display_name, "activities": activities})
        print_json(success=True, data={"members": members, "count": len(members)})

    def _build_table(
        self, grouped: list[tuple[str, list[dict[str, str]]]]
    ) -> object:
        """Build a Rich Table object for team activity."""
        from rich.table import Table as RichTable

        member_count = len(grouped)
        table = RichTable(title=f"Active Development ({member_count} members)", pad_edge=True)
        table.add_column("Developer", style="bold")
        table.add_column("Branch", style="info")
        table.add_column("Files")
        table.add_column("Updated", style="dim")

        for row in self._grouped_to_rows(grouped):
            table.add_row(*row)
        return table

    def _build_tree(
        self, grouped: list[tuple[str, list[dict[str, str]]]]
    ) -> object:
        """Build a Rich Tree object for detailed team activity."""
        from rich.tree import Tree as RichTree

        member_count = len(grouped)
        tree = RichTree(f"[bold]Active Development ({member_count} members)[/bold]")
        for dev, entries in grouped:
            display_name = entries[0].get("developer", dev) if entries else dev
            for art in entries:
                branch = art.get("branch", "?")
                dev_branch = tree.add(f"[bold]{display_name}[/bold] [dim]({branch})[/dim]")
                files_str = art.get("files", "")
                files_list = [f.strip() for f in files_str.split(",") if f.strip()]
                symbols_str = art.get("symbols", "")
                symbols_list = [s.strip() for s in symbols_str.split(",") if s.strip()]
                for fp in files_list:
                    file_node = dev_branch.add(f"[info]{fp}[/info]")
                    fp_module = fp.replace("/", ".").replace(".py", "")
                    for sym in symbols_list:
                        if fp_module in sym or fp in sym:
                            file_node.add(f"[dim]{sym}[/dim]")
                if not files_list:
                    dev_branch.add("[dim](no files tracked)[/dim]")
        return tree

    @staticmethod
    def _grouped_to_rows(
        grouped: list[tuple[str, list[dict[str, str]]]]
    ) -> list[list[str]]:
        """Convert grouped artifacts to flat table rows."""
        rows: list[list[str]] = []
        for dev, entries in grouped:
            display_name = entries[0].get("developer", dev) if entries else dev
            for art in entries:
                branch = art.get("branch", "?")
                ts = art.get("timestamp", "?")
                files_str = art.get("files", "")
                files_list = [f.strip() for f in files_str.split(",") if f.strip()]
                files_display = ", ".join(files_list) if files_list else "(none)"
                rows.append([display_name, branch, files_display, ts])
        return rows


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
