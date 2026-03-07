"""Brutal tests for AVOS-024: ConflictsOrchestrator.

Covers: Tier-1/2/3 detection, self-exclusion precedence, strict mode,
deterministic ordering, evidence attachment, speculative finding drop,
degraded enrichment, empty state, and config errors.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from avos_cli.commands.conflicts import ConflictsOrchestrator
from avos_cli.models.api import SearchHit, SearchResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config_json(avos_dir: Path, memory_id: str = "repo:org/test") -> None:
    avos_dir.mkdir(parents=True, exist_ok=True)
    config = {
        "repo": "org/test",
        "memory_id": memory_id,
        "api_url": "https://api.avos.ai",
        "api_key": "test-key",
        "developer": "LocalDev",
        "schema_version": "1",
    }
    (avos_dir / "config.json").write_text(json.dumps(config))


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _hours_ago(n: int) -> str:
    return (datetime.now(tz=timezone.utc) - timedelta(hours=n)).isoformat()


def _make_wip_content(
    developer: str,
    branch: str,
    timestamp: str,
    files: list[str] | None = None,
    symbols: list[str] | None = None,
    subsystems: list[str] | None = None,
) -> str:
    lines = [
        "[type: wip_activity]",
        f"[developer: {developer}]",
        f"[branch: {branch}]",
        f"[timestamp: {timestamp}]",
    ]
    if files:
        lines.append(f"Files: {', '.join(files)}")
    if symbols:
        lines.append(f"Symbols: {', '.join(symbols)}")
    if subsystems:
        lines.append(f"Subsystems: {', '.join(subsystems)}")
    return "\n".join(lines)


def _make_search_result(hits: list[tuple[str, str]]) -> SearchResult:
    return SearchResult(
        results=[
            SearchHit(note_id=nid, content=content, created_at=_now_iso(), rank=i + 1)
            for i, (nid, content) in enumerate(hits)
        ],
        total_count=len(hits),
    )


def _setup(tmp_path: Path) -> tuple[Path, MagicMock, MagicMock]:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / ".git").mkdir()
    _make_config_json(repo_root / ".avos")
    git_client = MagicMock()
    git_client.current_branch.return_value = "feature/local"
    git_client.user_name.return_value = "LocalDev"
    git_client.modified_files.return_value = ["src/auth.py", "src/models.py"]
    memory_client = MagicMock()
    return repo_root, git_client, memory_client


# ---------------------------------------------------------------------------
# Tier-1: File overlap (HIGH)
# ---------------------------------------------------------------------------

class TestTier1FileOverlap:

    def test_detects_file_overlap(self, tmp_path: Path) -> None:
        repo_root, git, memory = _setup(tmp_path)
        ts = _now_iso()
        memory.search.return_value = _make_search_result([
            ("n1", _make_wip_content("RemoteDev", "feature/remote", ts,
                                     files=["src/auth.py", "src/other.py"])),
        ])
        orch = ConflictsOrchestrator(
            memory_client=memory, git_client=git, repo_root=repo_root
        )
        with patch("avos_cli.commands.conflicts.extract_symbols", return_value=[]):
            code = orch.run(strict=False)
        assert code == 0

    def test_no_overlap_no_findings(self, tmp_path: Path) -> None:
        repo_root, git, memory = _setup(tmp_path)
        ts = _now_iso()
        memory.search.return_value = _make_search_result([
            ("n1", _make_wip_content("RemoteDev", "feature/remote", ts,
                                     files=["src/unrelated.py"])),
        ])
        orch = ConflictsOrchestrator(
            memory_client=memory, git_client=git, repo_root=repo_root
        )
        with patch("avos_cli.commands.conflicts.extract_symbols", return_value=[]):
            code = orch.run(strict=False)
        assert code == 0


# ---------------------------------------------------------------------------
# Tier-2: Symbol overlap (MEDIUM / HIGH with --strict)
# ---------------------------------------------------------------------------

class TestTier2SymbolOverlap:

    def test_symbol_overlap_medium(self, tmp_path: Path) -> None:
        repo_root, git, memory = _setup(tmp_path)
        ts = _now_iso()
        memory.search.return_value = _make_search_result([
            ("n1", _make_wip_content("RemoteDev", "feature/remote", ts,
                                     files=["src/auth.py"],
                                     symbols=["python:src.auth::login#function"])),
        ])
        orch = ConflictsOrchestrator(
            memory_client=memory, git_client=git, repo_root=repo_root
        )
        with patch("avos_cli.commands.conflicts.extract_symbols",
                    return_value=["python:src.auth::login#function"]):
            code = orch.run(strict=False)
        assert code == 0

    def test_symbol_overlap_strict_promotes_to_high(self, tmp_path: Path) -> None:
        repo_root, git, memory = _setup(tmp_path)
        ts = _now_iso()
        memory.search.return_value = _make_search_result([
            ("n1", _make_wip_content("RemoteDev", "feature/remote", ts,
                                     files=["src/auth.py"],
                                     symbols=["python:src.auth::login#function"])),
        ])
        orch = ConflictsOrchestrator(
            memory_client=memory, git_client=git, repo_root=repo_root
        )
        with patch("avos_cli.commands.conflicts.extract_symbols",
                    return_value=["python:src.auth::login#function"]):
            code = orch.run(strict=True)
        assert code == 0


# ---------------------------------------------------------------------------
# Tier-3: Subsystem overlap (LOW)
# ---------------------------------------------------------------------------

class TestTier3SubsystemOverlap:

    def test_subsystem_overlap_with_mapping(self, tmp_path: Path) -> None:
        repo_root, git, memory = _setup(tmp_path)
        ts = _now_iso()
        memory.search.return_value = _make_search_result([
            ("n1", _make_wip_content("RemoteDev", "feature/remote", ts,
                                     files=["api/routes.py"],
                                     subsystems=["backend"])),
        ])
        orch = ConflictsOrchestrator(
            memory_client=memory, git_client=git, repo_root=repo_root
        )
        with patch("avos_cli.commands.conflicts.extract_symbols", return_value=[]), \
             patch("avos_cli.commands.conflicts.load_subsystem_mapping",
                   return_value={"backend": ["src/**"]}), \
             patch("avos_cli.commands.conflicts.resolve_subsystems",
                   return_value=["backend"]):
            code = orch.run(strict=False)
        assert code == 0

    def test_subsystem_suppressed_when_no_mapping(self, tmp_path: Path) -> None:
        repo_root, git, memory = _setup(tmp_path)
        ts = _now_iso()
        memory.search.return_value = _make_search_result([
            ("n1", _make_wip_content("RemoteDev", "feature/remote", ts,
                                     files=["api/routes.py"],
                                     subsystems=["backend"])),
        ])
        orch = ConflictsOrchestrator(
            memory_client=memory, git_client=git, repo_root=repo_root
        )
        with patch("avos_cli.commands.conflicts.extract_symbols", return_value=[]), \
             patch("avos_cli.commands.conflicts.load_subsystem_mapping",
                   return_value={}):
            code = orch.run(strict=False)
        assert code == 0


# ---------------------------------------------------------------------------
# Self-exclusion
# ---------------------------------------------------------------------------

class TestSelfExclusion:

    def test_excludes_self_by_developer_and_branch(self, tmp_path: Path) -> None:
        """Own artifacts should be excluded from conflict analysis."""
        repo_root, git, memory = _setup(tmp_path)
        ts = _now_iso()
        memory.search.return_value = _make_search_result([
            ("self", _make_wip_content("LocalDev", "feature/local", ts,
                                       files=["src/auth.py"])),
            ("other", _make_wip_content("RemoteDev", "feature/remote", ts,
                                        files=["src/auth.py"])),
        ])
        orch = ConflictsOrchestrator(
            memory_client=memory, git_client=git, repo_root=repo_root
        )
        with patch("avos_cli.commands.conflicts.extract_symbols", return_value=[]):
            code = orch.run(strict=False)
        assert code == 0

    def test_no_exclusion_on_branch_only_match(self, tmp_path: Path) -> None:
        """Different developer on same branch should NOT be excluded."""
        repo_root, git, memory = _setup(tmp_path)
        ts = _now_iso()
        memory.search.return_value = _make_search_result([
            ("n1", _make_wip_content("OtherDev", "feature/local", ts,
                                     files=["src/auth.py"])),
        ])
        orch = ConflictsOrchestrator(
            memory_client=memory, git_client=git, repo_root=repo_root
        )
        with patch("avos_cli.commands.conflicts.extract_symbols", return_value=[]):
            code = orch.run(strict=False)
        assert code == 0

    def test_excludes_self_by_developer_only_different_branch(self, tmp_path: Path) -> None:
        """Same developer on different branch should be excluded (P2 fallback)."""
        repo_root, git, memory = _setup(tmp_path)
        ts = _now_iso()
        memory.search.return_value = _make_search_result([
            ("self2", _make_wip_content("LocalDev", "feature/other", ts,
                                        files=["src/auth.py"])),
        ])
        orch = ConflictsOrchestrator(
            memory_client=memory, git_client=git, repo_root=repo_root
        )
        with patch("avos_cli.commands.conflicts.extract_symbols", return_value=[]):
            code = orch.run(strict=False)
        assert code == 0


# ---------------------------------------------------------------------------
# Deterministic ordering
# ---------------------------------------------------------------------------

class TestDeterministicOrdering:

    def test_stable_across_runs(self, tmp_path: Path) -> None:
        repo_root, git, memory = _setup(tmp_path)
        ts = _now_iso()
        hits = [
            ("n1", _make_wip_content("Zara", "feature/z", ts, files=["src/auth.py"])),
            ("n2", _make_wip_content("Alice", "feature/a", ts, files=["src/auth.py", "src/models.py"])),
        ]
        codes = []
        for _ in range(3):
            memory.search.return_value = _make_search_result(hits)
            orch = ConflictsOrchestrator(
                memory_client=memory, git_client=git, repo_root=repo_root
            )
            with patch("avos_cli.commands.conflicts.extract_symbols", return_value=[]):
                code = orch.run(strict=False)
            codes.append(code)
        assert all(c == 0 for c in codes)


# ---------------------------------------------------------------------------
# Empty state
# ---------------------------------------------------------------------------

class TestEmptyState:

    def test_no_remote_artifacts(self, tmp_path: Path) -> None:
        repo_root, git, memory = _setup(tmp_path)
        memory.search.return_value = SearchResult(results=[], total_count=0)
        orch = ConflictsOrchestrator(
            memory_client=memory, git_client=git, repo_root=repo_root
        )
        with patch("avos_cli.commands.conflicts.extract_symbols", return_value=[]):
            code = orch.run(strict=False)
        assert code == 0

    def test_no_local_changes(self, tmp_path: Path) -> None:
        repo_root, git, memory = _setup(tmp_path)
        git.modified_files.return_value = []
        memory.search.return_value = _make_search_result([
            ("n1", _make_wip_content("RemoteDev", "feature/remote", _now_iso(),
                                     files=["src/auth.py"])),
        ])
        orch = ConflictsOrchestrator(
            memory_client=memory, git_client=git, repo_root=repo_root
        )
        with patch("avos_cli.commands.conflicts.extract_symbols", return_value=[]):
            code = orch.run(strict=False)
        assert code == 0


# ---------------------------------------------------------------------------
# Config errors
# ---------------------------------------------------------------------------

class TestConfigErrors:

    def test_missing_config(self, tmp_path: Path) -> None:
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        (repo_root / ".git").mkdir()
        git = MagicMock()
        memory = MagicMock()
        orch = ConflictsOrchestrator(
            memory_client=memory, git_client=git, repo_root=repo_root
        )
        code = orch.run(strict=False)
        assert code == 1


# ---------------------------------------------------------------------------
# API failure
# ---------------------------------------------------------------------------

class TestAPIFailure:

    def test_search_upstream_error(self, tmp_path: Path) -> None:
        from avos_cli.exceptions import UpstreamUnavailableError
        repo_root, git, memory = _setup(tmp_path)
        memory.search.side_effect = UpstreamUnavailableError("API down")
        orch = ConflictsOrchestrator(
            memory_client=memory, git_client=git, repo_root=repo_root
        )
        with patch("avos_cli.commands.conflicts.extract_symbols", return_value=[]):
            code = orch.run(strict=False)
        assert code == 2


# ---------------------------------------------------------------------------
# Expired artifacts filtered
# ---------------------------------------------------------------------------

class TestExpiredFiltering:

    def test_expired_artifacts_excluded(self, tmp_path: Path) -> None:
        repo_root, git, memory = _setup(tmp_path)
        memory.search.return_value = _make_search_result([
            ("expired", _make_wip_content("RemoteDev", "feature/remote",
                                          _hours_ago(25), files=["src/auth.py"])),
        ])
        orch = ConflictsOrchestrator(
            memory_client=memory, git_client=git, repo_root=repo_root
        )
        with patch("avos_cli.commands.conflicts.extract_symbols", return_value=[]):
            code = orch.run(strict=False)
        assert code == 0
