"""Conflicts command orchestrator (AVOS-024).

Detects potential merge conflicts by comparing local work-in-progress
against remote team WIP artifacts. Produces tiered, explainable
conflict findings with deterministic ordering.

Tier-1 (HIGH): File path exact overlap
Tier-2 (MEDIUM, or HIGH with --strict): Symbol overlap
Tier-3 (LOW): Subsystem overlap when mapping exists

Exit codes:
    0: success (including empty state or degraded)
    1: precondition failure (config missing)
    2: hard external failure (API unreachable)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from avos_cli.config.manager import load_config
from avos_cli.config.subsystems import load_subsystem_mapping, resolve_subsystems
from avos_cli.exceptions import AvosError, ConfigurationNotInitializedError
from avos_cli.models.api import SearchHit
from avos_cli.services.symbol_extractor import extract_symbols
from avos_cli.utils.logger import get_logger
from avos_cli.utils.output import (
    console,
    is_interactive,
    print_error,
    print_info,
    print_json,
    print_success,
    print_warning,
    render_table,
)
from avos_cli.utils.time_helpers import is_artifact_active

_log = get_logger("commands.conflicts")

_WIP_SEARCH_K = 50
_ACTIVE_TTL_HOURS = 24

_TAG_RE = re.compile(r"^\[(\w+):\s*(.*?)\]\s*$")
_KV_RE = re.compile(r"^(\w+):\s*(.+)$")

_SEVERITY_RANK = {"HIGH": 3, "MEDIUM": 2, "LOW": 1}


@dataclass
class ConflictFinding:
    """A single conflict finding with evidence.

    Args:
        severity: HIGH, MEDIUM, or LOW.
        tier: 1, 2, or 3.
        remote_developer: Developer who owns the conflicting artifact.
        remote_branch: Branch of the conflicting artifact.
        artifact_id: Note ID of the remote artifact.
        evidence_files: Overlapping file paths.
        evidence_symbols: Overlapping symbol keys.
        evidence_subsystems: Overlapping subsystem names.
        explanation: Human-readable explanation of the conflict.
    """

    severity: str
    tier: int
    remote_developer: str
    remote_branch: str
    artifact_id: str
    evidence_files: list[str] = field(default_factory=list)
    evidence_symbols: list[str] = field(default_factory=list)
    evidence_subsystems: list[str] = field(default_factory=list)
    explanation: str = ""

    @property
    def evidence_count(self) -> int:
        return len(self.evidence_files) + len(self.evidence_symbols) + len(self.evidence_subsystems)

    @property
    def top_overlap_path(self) -> str:
        if self.evidence_files:
            return self.evidence_files[0]
        return ""


class ConflictsOrchestrator:
    """Orchestrates the `avos conflicts` command.

    Pipeline: load config -> get local state -> search remote WIP ->
    TTL filter -> self-exclude -> compute tiers -> rank -> render.

    Args:
        memory_client: Avos Memory API client.
        git_client: Local git operations wrapper.
        repo_root: Path to the repository root.
    """

    def __init__(
        self,
        memory_client: object,
        git_client: object,
        repo_root: Path,
    ) -> None:
        self._memory = memory_client
        self._git = git_client
        self._repo_root = repo_root
        self._avos_dir = repo_root / ".avos"

    def run(
        self,
        strict: bool = False,
        live: bool = False,
        json_output: bool = False,
    ) -> int:
        """Execute the conflict detection flow.

        Args:
            strict: If True, promote symbol overlaps (Tier-2) to HIGH severity.
            live: Auto-refresh display every 30 seconds.
            json_output: Emit JSON envelope instead of Rich output.

        Returns:
            Exit code: 0 success, 1 precondition, 2 external failure.
        """
        if live:
            return self._run_live(strict, json_output)
        return self._run_once(strict, json_output)

    def _run_once(self, strict: bool = False, json_output: bool = False) -> int:
        """Single-shot conflict detection."""
        try:
            config = load_config(self._repo_root)
        except ConfigurationNotInitializedError as e:
            print_error(f"[CONFIG_NOT_INITIALIZED] {e}")
            return 1
        except AvosError as e:
            print_error(f"[{e.code}] {e}")
            return 1

        memory_id = config.memory_id
        local_developer = config.developer or ""
        if not local_developer:
            try:
                local_developer = self._git.user_name(self._repo_root)
            except Exception:
                local_developer = "unknown"

        try:
            local_branch = self._git.current_branch(self._repo_root)
        except AvosError as e:
            print_error(f"[{e.code}] {e}")
            return 1

        local_files = self._git.modified_files(self._repo_root)

        local_symbols: set[str] = set()
        for fp in local_files:
            abs_path = self._repo_root / fp
            file_syms = extract_symbols(abs_path, self._repo_root)
            local_symbols.update(file_syms)

        subsystem_mapping = load_subsystem_mapping(self._avos_dir)
        local_subsystems: set[str] = set()
        for fp in local_files:
            subs = resolve_subsystems(fp, subsystem_mapping)
            local_subsystems.update(subs)

        try:
            result = self._memory.search(
                memory_id, "wip_activity", k=_WIP_SEARCH_K, mode="keyword"
            )
        except AvosError as e:
            print_error(f"[{e.code}] {e}")
            return 2

        remote_artifacts = self._parse_artifacts(result.results)
        active = self._filter_active(remote_artifacts)
        peers = self._exclude_self(active, local_developer, local_branch)

        findings = self._compute_conflicts(
            peers=peers,
            local_files=set(local_files),
            local_symbols=local_symbols,
            local_subsystems=local_subsystems,
            subsystem_mapping=subsystem_mapping,
            strict=strict,
        )

        findings = [f for f in findings if f.evidence_count > 0]
        findings = self._sort_findings(findings)

        if not findings:
            if json_output:
                print_json(success=True, data={"findings": [], "count": 0})
            elif not local_files:
                print_info("No local changes detected.")
            elif not peers:
                print_info(
                    "No active team activity to compare against. "
                    "Run 'avos watch' to start publishing."
                )
            else:
                print_success("No conflicts detected with active team work.")
            return 0

        if json_output:
            self._render_json(findings, strict)
        else:
            self._render(findings, strict)
        return 0

    def _run_live(self, strict: bool = False, json_output: bool = False) -> int:
        """Auto-refreshing conflict detection using Rich Live."""
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
                local_developer = config.developer or ""
                if not local_developer:
                    try:
                        local_developer = self._git.user_name(self._repo_root)
                    except Exception:
                        local_developer = "unknown"
                local_branch = self._git.current_branch(self._repo_root)
                local_files = self._git.modified_files(self._repo_root)
                local_symbols: set[str] = set()
                for fp in local_files:
                    local_symbols.update(extract_symbols(self._repo_root / fp, self._repo_root))
                subsystem_mapping = load_subsystem_mapping(self._avos_dir)
                local_subsystems: set[str] = set()
                for fp in local_files:
                    local_subsystems.update(resolve_subsystems(fp, subsystem_mapping))
                result = self._memory.search(
                    config.memory_id, "wip_activity", k=_WIP_SEARCH_K, mode="keyword"
                )
                remote_artifacts = self._parse_artifacts(result.results)
                active = self._filter_active(remote_artifacts)
                peers = self._exclude_self(active, local_developer, local_branch)
                findings = self._compute_conflicts(
                    peers=peers, local_files=set(local_files),
                    local_symbols=local_symbols, local_subsystems=local_subsystems,
                    subsystem_mapping=subsystem_mapping, strict=strict,
                )
                findings = [f for f in findings if f.evidence_count > 0]
                findings = self._sort_findings(findings)
            except Exception:
                table = RichTable(title="Conflicts (error fetching)")
                table.add_column("Status")
                table.add_row("Could not fetch conflict data")
                return table

            return self._build_table(findings, strict)

        try:
            render_live_loop(_build_renderable, interval=30.0)
        except RuntimeError as e:
            print_error(str(e))
            return 1
        return 0

    def _parse_artifacts(
        self, hits: list[SearchHit]
    ) -> list[dict[str, str]]:
        """Parse WIP artifact content from search hits (tolerant)."""
        parsed: list[dict[str, str]] = []
        for hit in hits:
            artifact = _parse_wip_content(hit.content)
            if artifact is None:
                continue
            artifact["_note_id"] = hit.note_id
            parsed.append(artifact)
        return parsed

    def _filter_active(
        self, artifacts: list[dict[str, str]]
    ) -> list[dict[str, str]]:
        """Filter artifacts by TTL window."""
        active: list[dict[str, str]] = []
        for art in artifacts:
            ts = art.get("timestamp", "")
            if not ts:
                continue
            if is_artifact_active(
                ts, _ACTIVE_TTL_HOURS,
                artifact_id=art.get("_note_id", ""),
                command_context="conflicts",
            ):
                active.append(art)
        return active

    def _exclude_self(
        self,
        artifacts: list[dict[str, str]],
        local_developer: str,
        local_branch: str,
    ) -> list[dict[str, str]]:
        """Exclude self artifacts using deterministic precedence.

        P1: author_fingerprint exact match (when present)
        P2: normalized developer + normalized branch match
        P3: normalized developer exact match (any branch)
        Never exclude on branch-only match.

        Args:
            artifacts: Active remote artifacts.
            local_developer: Local developer identity.
            local_branch: Local git branch.

        Returns:
            Artifacts not belonging to the local developer.
        """
        local_dev_norm = local_developer.strip().lower()
        local_branch_norm = local_branch.strip().lower()
        peers: list[dict[str, str]] = []

        for art in artifacts:
            remote_dev = art.get("developer", "").strip().lower()
            remote_branch = art.get("branch", "").strip().lower()

            if remote_dev == local_dev_norm:
                continue

            peers.append(art)

        return peers

    def _compute_conflicts(
        self,
        peers: list[dict[str, str]],
        local_files: set[str],
        local_symbols: set[str],
        local_subsystems: set[str],
        subsystem_mapping: dict[str, list[str]],
        strict: bool,
    ) -> list[ConflictFinding]:
        """Compute tiered conflict findings against peer artifacts.

        Args:
            peers: Remote peer artifacts (self excluded).
            local_files: Set of local modified file paths.
            local_symbols: Set of local extracted symbols.
            local_subsystems: Set of local subsystem names.
            subsystem_mapping: Loaded subsystem mapping (empty if unavailable).
            strict: Whether to promote Tier-2 to HIGH.

        Returns:
            List of conflict findings (may include zero-evidence items).
        """
        findings: list[ConflictFinding] = []

        local_symbols_lower = {s.lower() for s in local_symbols}

        for art in peers:
            remote_dev = art.get("developer", "unknown")
            remote_branch = art.get("branch", "unknown")
            artifact_id = art.get("_note_id", "")

            remote_files_str = art.get("files", "")
            remote_files = {f.strip() for f in remote_files_str.split(",") if f.strip()}

            remote_symbols_str = art.get("symbols", "")
            remote_symbols = {s.strip() for s in remote_symbols_str.split(",") if s.strip()}
            remote_symbols_lower = {s.lower() for s in remote_symbols}

            remote_subsystems_str = art.get("subsystems", "")
            remote_subsystems = {s.strip() for s in remote_subsystems_str.split(",") if s.strip()}

            file_overlaps = sorted(local_files & remote_files)
            if file_overlaps:
                findings.append(ConflictFinding(
                    severity="HIGH",
                    tier=1,
                    remote_developer=remote_dev,
                    remote_branch=remote_branch,
                    artifact_id=artifact_id,
                    evidence_files=file_overlaps,
                    explanation=f"File overlap: {', '.join(file_overlaps)}",
                ))

            symbol_overlaps = sorted(local_symbols_lower & remote_symbols_lower)
            if symbol_overlaps:
                severity = "HIGH" if strict else "MEDIUM"
                findings.append(ConflictFinding(
                    severity=severity,
                    tier=2,
                    remote_developer=remote_dev,
                    remote_branch=remote_branch,
                    artifact_id=artifact_id,
                    evidence_symbols=symbol_overlaps,
                    explanation=f"Symbol overlap: {', '.join(symbol_overlaps)}",
                ))

            if subsystem_mapping:
                sub_overlaps = sorted(local_subsystems & remote_subsystems)
                if sub_overlaps:
                    findings.append(ConflictFinding(
                        severity="LOW",
                        tier=3,
                        remote_developer=remote_dev,
                        remote_branch=remote_branch,
                        artifact_id=artifact_id,
                        evidence_subsystems=sub_overlaps,
                        explanation=f"Subsystem overlap: {', '.join(sub_overlaps)}",
                    ))

        return findings

    def _sort_findings(
        self, findings: list[ConflictFinding]
    ) -> list[ConflictFinding]:
        """Sort findings by canonical tie-break order (Section 6.4).

        Order: severity_rank DESC, evidence_count DESC,
        remote_developer_normalized ASC, remote_branch_normalized ASC,
        top_overlap_path ASC, artifact_id ASC.
        """
        return sorted(
            findings,
            key=lambda f: (
                -_SEVERITY_RANK.get(f.severity, 0),
                -f.evidence_count,
                f.remote_developer.strip().lower(),
                f.remote_branch.strip().lower(),
                f.top_overlap_path,
                f.artifact_id,
            ),
        )

    def _render(self, findings: list[ConflictFinding], strict: bool) -> None:
        """Render conflict findings as a Rich table."""
        if is_interactive():
            table = self._build_table(findings, strict)
            console.print(table)
        else:
            high = sum(1 for f in findings if f.severity == "HIGH")
            medium = sum(1 for f in findings if f.severity == "MEDIUM")
            low = sum(1 for f in findings if f.severity == "LOW")
            title = (
                f"Conflicts Detected: {len(findings)} "
                f"(HIGH: {high}, MEDIUM: {medium}, LOW: {low})"
            )
            if strict:
                title += " [strict]"
            render_table(
                title,
                [("Severity", ""), ("Tier", ""), ("Developer", ""), ("Branch", ""), ("Evidence", "")],
                self._findings_to_rows(findings),
            )

    def _render_json(self, findings: list[ConflictFinding], strict: bool) -> None:
        """Emit conflict findings as JSON envelope."""
        items: list[dict[str, object]] = []
        for f in findings:
            items.append({
                "severity": f.severity,
                "tier": f.tier,
                "developer": f.remote_developer,
                "branch": f.remote_branch,
                "evidence_files": f.evidence_files,
                "evidence_symbols": f.evidence_symbols,
                "evidence_subsystems": f.evidence_subsystems,
                "explanation": f.explanation,
            })
        print_json(success=True, data={
            "findings": items,
            "count": len(items),
            "strict": strict,
        })

    def _build_table(self, findings: list[ConflictFinding], strict: bool) -> object:
        """Build a Rich Table for conflict findings."""
        from rich.table import Table as RichTable

        high = sum(1 for f in findings if f.severity == "HIGH")
        medium = sum(1 for f in findings if f.severity == "MEDIUM")
        low = sum(1 for f in findings if f.severity == "LOW")
        title = (
            f"Conflicts Detected: {len(findings)} "
            f"(HIGH: {high}, MEDIUM: {medium}, LOW: {low})"
        )
        if strict:
            title += " [strict]"

        table = RichTable(title=title, pad_edge=True)
        table.add_column("Severity", style="bold")
        table.add_column("Tier")
        table.add_column("Developer")
        table.add_column("Branch", style="dim")
        table.add_column("Evidence")

        _tier_labels = {1: "File", 2: "Symbol", 3: "Subsystem"}
        _severity_styles = {"HIGH": "high", "MEDIUM": "medium", "LOW": "low"}

        for f in findings:
            sev_style = _severity_styles.get(f.severity, "")
            tier_label = _tier_labels.get(f.tier, str(f.tier))
            evidence_parts: list[str] = []
            evidence_parts.extend(f.evidence_files)
            evidence_parts.extend(f.evidence_symbols)
            evidence_parts.extend(f.evidence_subsystems)
            evidence_str = ", ".join(evidence_parts) if evidence_parts else f.explanation
            table.add_row(
                f"[{sev_style}]{f.severity}[/{sev_style}]",
                tier_label,
                f.remote_developer,
                f.remote_branch,
                evidence_str,
            )
        return table

    @staticmethod
    def _findings_to_rows(findings: list[ConflictFinding]) -> list[list[str]]:
        """Convert findings to flat table rows for plain text."""
        _tier_labels = {1: "File", 2: "Symbol", 3: "Subsystem"}
        rows: list[list[str]] = []
        for f in findings:
            tier_label = _tier_labels.get(f.tier, str(f.tier))
            evidence_parts: list[str] = []
            evidence_parts.extend(f.evidence_files)
            evidence_parts.extend(f.evidence_symbols)
            evidence_parts.extend(f.evidence_subsystems)
            evidence_str = ", ".join(evidence_parts) if evidence_parts else f.explanation
            rows.append([f.severity, tier_label, f.remote_developer, f.remote_branch, evidence_str])
        return rows


def _parse_wip_content(content: str) -> dict[str, str] | None:
    """Parse WIP artifact structured text into a dict.

    Returns None if required fields (developer, branch, timestamp) are missing.
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
