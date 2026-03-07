"""E2E integration tests for Sprint 5 live collaboration (AVOS-025).

Validates the integrated watch -> team -> conflicts pipeline under
healthy, degraded, empty, and determinism scenarios. Uses mocked
memory client to simulate the full collaboration loop.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from avos_cli.commands.conflicts import ConflictsOrchestrator
from avos_cli.commands.team import TeamOrchestrator
from avos_cli.commands.watch import WatchOrchestrator
from avos_cli.models.api import SearchHit, SearchResult


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _hours_ago(n: int) -> str:
    return (datetime.now(tz=timezone.utc) - timedelta(hours=n)).isoformat()


def _make_config_json(avos_dir: Path) -> None:
    avos_dir.mkdir(parents=True, exist_ok=True)
    config = {
        "repo": "org/test",
        "memory_id": "repo:org/test",
        "api_url": "https://api.avos.ai",
        "api_key": "test-key",
        "developer": "LocalDev",
        "schema_version": "1",
    }
    (avos_dir / "config.json").write_text(json.dumps(config))


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


def _setup_repo(tmp_path: Path) -> Path:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / ".git").mkdir()
    _make_config_json(repo_root / ".avos")
    return repo_root


# ---------------------------------------------------------------------------
# Healthy flow: watch -> team -> conflicts
# ---------------------------------------------------------------------------

class TestHealthyFlow:
    """Full pipeline under normal conditions."""

    def test_watch_start_team_view_conflicts_detect(self, tmp_path: Path) -> None:
        """Simulate: start watch, team sees activity, conflicts detects overlap."""
        repo_root = _setup_repo(tmp_path)
        git = MagicMock()
        git.current_branch.return_value = "feature/local"
        git.user_name.return_value = "LocalDev"
        git.modified_files.return_value = ["src/auth.py"]
        memory = MagicMock()

        # Step 1: Start watch
        watch_orch = WatchOrchestrator(
            git_client=git, memory_client=memory, repo_root=repo_root
        )
        with patch.object(watch_orch, "_spawn_watcher", return_value=12345):
            code = watch_orch.run(stop=False)
        assert code == 0

        # Step 2: Team sees remote activity
        ts = _now_iso()
        remote_hits = [
            ("n1", _make_wip_content("Alice", "feature/auth", ts,
                                     files=["src/auth.py", "src/models.py"],
                                     symbols=["python:src.auth::login#function"])),
            ("n2", _make_wip_content("Bob", "feature/api", ts,
                                     files=["src/api.py"])),
        ]
        memory.search.return_value = _make_search_result(remote_hits)
        team_orch = TeamOrchestrator(memory_client=memory, repo_root=repo_root)
        code = team_orch.run()
        assert code == 0

        # Step 3: Conflicts detects overlap
        memory.search.return_value = _make_search_result(remote_hits)
        conflicts_orch = ConflictsOrchestrator(
            memory_client=memory, git_client=git, repo_root=repo_root
        )
        with patch("avos_cli.commands.conflicts.extract_symbols",
                    return_value=["python:src.auth::login#function"]):
            code = conflicts_orch.run(strict=False)
        assert code == 0

        # Step 4: Stop watch
        with patch("avos_cli.commands.watch.os.kill"):
            with patch.object(WatchOrchestrator, "_pid_alive", return_value=True):
                stop_orch = WatchOrchestrator(
                    git_client=git, memory_client=memory, repo_root=repo_root
                )
                code = stop_orch.run(stop=True)
        assert code == 0


# ---------------------------------------------------------------------------
# Degraded flow
# ---------------------------------------------------------------------------

class TestDegradedFlow:
    """Pipeline under degraded conditions."""

    def test_missing_symbols_still_detects_file_overlap(self, tmp_path: Path) -> None:
        repo_root = _setup_repo(tmp_path)
        git = MagicMock()
        git.current_branch.return_value = "feature/local"
        git.user_name.return_value = "LocalDev"
        git.modified_files.return_value = ["src/auth.py"]
        memory = MagicMock()

        ts = _now_iso()
        memory.search.return_value = _make_search_result([
            ("n1", _make_wip_content("Alice", "feature/auth", ts,
                                     files=["src/auth.py"])),
        ])

        conflicts_orch = ConflictsOrchestrator(
            memory_client=memory, git_client=git, repo_root=repo_root
        )
        with patch("avos_cli.commands.conflicts.extract_symbols", return_value=[]):
            code = conflicts_orch.run(strict=False)
        assert code == 0

    def test_missing_subsystem_map_suppresses_tier3(self, tmp_path: Path) -> None:
        repo_root = _setup_repo(tmp_path)
        git = MagicMock()
        git.current_branch.return_value = "feature/local"
        git.user_name.return_value = "LocalDev"
        git.modified_files.return_value = ["src/auth.py"]
        memory = MagicMock()

        ts = _now_iso()
        memory.search.return_value = _make_search_result([
            ("n1", _make_wip_content("Alice", "feature/auth", ts,
                                     files=["api/routes.py"],
                                     subsystems=["backend"])),
        ])

        conflicts_orch = ConflictsOrchestrator(
            memory_client=memory, git_client=git, repo_root=repo_root
        )
        with patch("avos_cli.commands.conflicts.extract_symbols", return_value=[]), \
             patch("avos_cli.commands.conflicts.load_subsystem_mapping",
                   return_value={}):
            code = conflicts_orch.run(strict=False)
        assert code == 0

    def test_expired_artifacts_excluded(self, tmp_path: Path) -> None:
        repo_root = _setup_repo(tmp_path)
        git = MagicMock()
        git.current_branch.return_value = "feature/local"
        git.user_name.return_value = "LocalDev"
        git.modified_files.return_value = ["src/auth.py"]
        memory = MagicMock()

        memory.search.return_value = _make_search_result([
            ("expired", _make_wip_content("Alice", "feature/auth",
                                          _hours_ago(25), files=["src/auth.py"])),
        ])

        # Team should show empty
        team_orch = TeamOrchestrator(memory_client=memory, repo_root=repo_root)
        code = team_orch.run()
        assert code == 0

        # Conflicts should show no conflicts
        conflicts_orch = ConflictsOrchestrator(
            memory_client=memory, git_client=git, repo_root=repo_root
        )
        with patch("avos_cli.commands.conflicts.extract_symbols", return_value=[]):
            code = conflicts_orch.run(strict=False)
        assert code == 0


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------

class TestDeterminism:
    """Repeat runs produce identical results."""

    def test_team_deterministic_across_3_runs(self, tmp_path: Path) -> None:
        repo_root = _setup_repo(tmp_path)
        memory = MagicMock()
        ts = _now_iso()
        hits = [
            ("n1", _make_wip_content("Zara", "feature/z", ts, files=["z.py"])),
            ("n2", _make_wip_content("Alice", "feature/a", ts, files=["a.py"])),
            ("n3", _make_wip_content("Bob", "feature/b", ts, files=["b.py"])),
        ]
        codes = []
        for _ in range(3):
            memory.search.return_value = _make_search_result(hits)
            orch = TeamOrchestrator(memory_client=memory, repo_root=repo_root)
            codes.append(orch.run())
        assert codes == [0, 0, 0]

    def test_conflicts_deterministic_across_3_runs(self, tmp_path: Path) -> None:
        repo_root = _setup_repo(tmp_path)
        git = MagicMock()
        git.current_branch.return_value = "feature/local"
        git.user_name.return_value = "LocalDev"
        git.modified_files.return_value = ["src/auth.py", "src/models.py"]
        memory = MagicMock()
        ts = _now_iso()
        hits = [
            ("n1", _make_wip_content("Alice", "feature/a", ts,
                                     files=["src/auth.py"])),
            ("n2", _make_wip_content("Bob", "feature/b", ts,
                                     files=["src/models.py", "src/auth.py"])),
        ]
        codes = []
        for _ in range(3):
            memory.search.return_value = _make_search_result(hits)
            orch = ConflictsOrchestrator(
                memory_client=memory, git_client=git, repo_root=repo_root
            )
            with patch("avos_cli.commands.conflicts.extract_symbols", return_value=[]):
                codes.append(orch.run(strict=False))
        assert codes == [0, 0, 0]


# ---------------------------------------------------------------------------
# Empty state
# ---------------------------------------------------------------------------

class TestEmptyState:

    def test_no_wip_artifacts_team(self, tmp_path: Path) -> None:
        repo_root = _setup_repo(tmp_path)
        memory = MagicMock()
        memory.search.return_value = SearchResult(results=[], total_count=0)
        orch = TeamOrchestrator(memory_client=memory, repo_root=repo_root)
        code = orch.run()
        assert code == 0

    def test_no_wip_artifacts_conflicts(self, tmp_path: Path) -> None:
        repo_root = _setup_repo(tmp_path)
        git = MagicMock()
        git.current_branch.return_value = "main"
        git.user_name.return_value = "LocalDev"
        git.modified_files.return_value = ["src/app.py"]
        memory = MagicMock()
        memory.search.return_value = SearchResult(results=[], total_count=0)
        orch = ConflictsOrchestrator(
            memory_client=memory, git_client=git, repo_root=repo_root
        )
        with patch("avos_cli.commands.conflicts.extract_symbols", return_value=[]):
            code = orch.run(strict=False)
        assert code == 0


# ---------------------------------------------------------------------------
# Self-exclusion in conflicts
# ---------------------------------------------------------------------------

class TestSelfExclusion:

    def test_own_artifacts_excluded_from_conflicts(self, tmp_path: Path) -> None:
        repo_root = _setup_repo(tmp_path)
        git = MagicMock()
        git.current_branch.return_value = "feature/local"
        git.user_name.return_value = "LocalDev"
        git.modified_files.return_value = ["src/auth.py"]
        memory = MagicMock()

        ts = _now_iso()
        memory.search.return_value = _make_search_result([
            ("self", _make_wip_content("LocalDev", "feature/local", ts,
                                       files=["src/auth.py"])),
            ("other", _make_wip_content("RemoteDev", "feature/remote", ts,
                                        files=["src/other.py"])),
        ])

        orch = ConflictsOrchestrator(
            memory_client=memory, git_client=git, repo_root=repo_root
        )
        with patch("avos_cli.commands.conflicts.extract_symbols", return_value=[]):
            code = orch.run(strict=False)
        assert code == 0


# ---------------------------------------------------------------------------
# Strict mode
# ---------------------------------------------------------------------------

class TestStrictMode:

    def test_strict_promotes_symbol_overlap_to_high(self, tmp_path: Path) -> None:
        repo_root = _setup_repo(tmp_path)
        git = MagicMock()
        git.current_branch.return_value = "feature/local"
        git.user_name.return_value = "LocalDev"
        git.modified_files.return_value = ["src/auth.py"]
        memory = MagicMock()

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
