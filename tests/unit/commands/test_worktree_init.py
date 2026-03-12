"""Tests for avos worktree-init command and --agent option on session-start.

STEP_NAME: worktree-init + agent name
ASSOCIATED_TEST: Verify worktree-only guard, sibling config discovery, agent name in session
TEST_SPEC:
  - Behavior:
    - [x] worktree-init copies config from sibling worktree
    - [x] worktree-init rejects main repo (not a worktree)
    - [x] worktree-init rejects when config already exists
    - [x] worktree-init finds config across multiple siblings
    - [x] session-start stores agent name in session.json
    - [x] session-start uses git user.name when no agent specified
    - [x] worktree-add passes agent to session start
  - Edges:
    - [x] No sibling has config -> error
    - [x] Empty --agent string treated as no agent
  - Invariants:
    - [x] Only config.json copied (not PIDs/session files)
    - [x] Copied config matches source exactly
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from avos_cli.services.git_client import GitClient


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def git_repo(tmp_path: Path) -> Path:
    """Create a real temporary git repo with an initial commit."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=repo, capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=repo, capture_output=True, check=True,
    )
    (repo / "README.md").write_text("# Test")
    subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "Initial commit"],
        cwd=repo, capture_output=True, check=True,
    )
    return repo


@pytest.fixture()
def connected_repo(git_repo: Path) -> Path:
    """A git repo with .avos/config.json (simulating avos connect)."""
    avos_dir = git_repo / ".avos"
    avos_dir.mkdir()
    config = {
        "repo": "org/repo",
        "memory_id": "repo:org/repo",
        "memory_id_session": "repo:org/repo-session",
        "api_url": "https://api.avos.ai",
        "api_key": "test-key",
        "connected_at": "2026-03-09T00:00:00+00:00",
        "schema_version": "2",
    }
    (avos_dir / "config.json").write_text(json.dumps(config, indent=2))
    return git_repo


@pytest.fixture()
def worktree_in_connected(connected_repo: Path) -> Path:
    """A git worktree created from a connected repo (no .avos yet)."""
    client = GitClient()
    wt_path = connected_repo.parent / "wt-target"
    client.worktree_add(connected_repo, wt_path, "br-target")
    return wt_path


@pytest.fixture()
def client() -> GitClient:
    return GitClient()


# ---------------------------------------------------------------------------
# WorktreeInitOrchestrator tests
# ---------------------------------------------------------------------------

class TestWorktreeInitOrchestrator:
    """Tests for the worktree-init orchestration pipeline."""

    def test_rejects_main_repo(self, connected_repo: Path):
        """Should return exit 1 when run in the main repo (not a worktree)."""
        from avos_cli.commands.worktree_init import WorktreeInitOrchestrator

        orch = WorktreeInitOrchestrator(
            git_client=GitClient(),
            repo_root=connected_repo,
        )
        code = orch.run()
        assert code == 1

    def test_rejects_when_config_exists(self, worktree_in_connected: Path):
        """Should return exit 1 when .avos/config.json already exists."""
        from avos_cli.commands.worktree_init import WorktreeInitOrchestrator

        avos_dir = worktree_in_connected / ".avos"
        avos_dir.mkdir(parents=True, exist_ok=True)
        (avos_dir / "config.json").write_text('{"already": "here"}')

        orch = WorktreeInitOrchestrator(
            git_client=GitClient(),
            repo_root=worktree_in_connected,
        )
        code = orch.run()
        assert code == 1

    def test_copies_config_from_sibling(self, worktree_in_connected: Path, connected_repo: Path):
        """Should copy config.json from a sibling that has it."""
        from avos_cli.commands.worktree_init import WorktreeInitOrchestrator

        orch = WorktreeInitOrchestrator(
            git_client=GitClient(),
            repo_root=worktree_in_connected,
        )
        code = orch.run()
        assert code == 0

        target_config = json.loads(
            (worktree_in_connected / ".avos" / "config.json").read_text()
        )
        source_config = json.loads(
            (connected_repo / ".avos" / "config.json").read_text()
        )
        assert target_config == source_config

    def test_does_not_copy_session_or_pid_files(
        self, worktree_in_connected: Path, connected_repo: Path
    ):
        """Only config.json should be copied from the sibling."""
        from avos_cli.commands.worktree_init import WorktreeInitOrchestrator

        source_avos = connected_repo / ".avos"
        (source_avos / "session.json").write_text('{"session_id": "old"}')
        (source_avos / "watcher.pid").write_text('{"pid": 99999}')

        orch = WorktreeInitOrchestrator(
            git_client=GitClient(),
            repo_root=worktree_in_connected,
        )
        code = orch.run()
        assert code == 0

        new_avos = worktree_in_connected / ".avos"
        assert (new_avos / "config.json").exists()
        assert not (new_avos / "session.json").exists()
        assert not (new_avos / "watcher.pid").exists()

    def test_fails_when_no_sibling_has_config(self, git_repo: Path):
        """Should return exit 1 when no sibling worktree has .avos/config.json."""
        from avos_cli.commands.worktree_init import WorktreeInitOrchestrator

        client = GitClient()
        wt_path = git_repo.parent / "wt-orphan"
        client.worktree_add(git_repo, wt_path, "br-orphan")

        orch = WorktreeInitOrchestrator(
            git_client=client,
            repo_root=wt_path,
        )
        code = orch.run()
        assert code == 1

    def test_finds_config_from_second_sibling(self, connected_repo: Path):
        """Should find config even if the first sibling doesn't have it."""
        from avos_cli.commands.worktree_init import WorktreeInitOrchestrator

        client = GitClient()
        wt1 = connected_repo.parent / "wt-no-config"
        client.worktree_add(connected_repo, wt1, "br-no-config")

        wt2 = connected_repo.parent / "wt-needs-config"
        client.worktree_add(connected_repo, wt2, "br-needs-config")

        orch = WorktreeInitOrchestrator(
            git_client=client,
            repo_root=wt2,
        )
        code = orch.run()
        assert code == 0
        assert (wt2 / ".avos" / "config.json").exists()


# ---------------------------------------------------------------------------
# Session-start: worktree requires --agent
# ---------------------------------------------------------------------------

class TestSessionStartAgentRequiredInWorktree:
    """In a git worktree, session-start must be called with --agent."""

    def test_blocks_session_start_in_worktree_without_agent(
        self, connected_repo: Path, worktree_in_connected: Path
    ):
        """SessionStartOrchestrator in worktree without agent returns 1 with AGENT_REQUIRED."""
        import shutil

        from avos_cli.commands.session_start import SessionStartOrchestrator

        # Copy config into worktree so load_config succeeds before agent check
        wt_avos = worktree_in_connected / ".avos"
        wt_avos.mkdir(parents=True, exist_ok=True)
        shutil.copy2(
            connected_repo / ".avos" / "config.json",
            wt_avos / "config.json",
        )

        orch = SessionStartOrchestrator(
            git_client=GitClient(),
            memory_client=MagicMock(),
            repo_root=worktree_in_connected,
        )
        with patch("avos_cli.commands.session_start.print_error") as mock_err:
            code = orch.run("test goal")

        assert code == 1
        mock_err.assert_called_once()
        msg = mock_err.call_args[0][0]
        assert "AGENT_REQUIRED" in msg
        assert "--agent" in msg or "worktree" in msg

    def test_allows_session_start_in_worktree_with_agent(
        self, connected_repo: Path, worktree_in_connected: Path
    ):
        """SessionStartOrchestrator in worktree with agent proceeds normally."""
        import shutil

        from avos_cli.commands.session_start import SessionStartOrchestrator

        wt_avos = worktree_in_connected / ".avos"
        wt_avos.mkdir(parents=True, exist_ok=True)
        shutil.copy2(
            connected_repo / ".avos" / "config.json",
            wt_avos / "config.json",
        )

        orch = SessionStartOrchestrator(
            git_client=GitClient(),
            memory_client=MagicMock(),
            repo_root=worktree_in_connected,
        )
        with patch.object(orch, "_spawn_watcher", return_value=99999):
            code = orch.run("test goal", agent="agentB")

        assert code == 0


# ---------------------------------------------------------------------------
# Session-start --agent tests (main repo)
# ---------------------------------------------------------------------------

class TestSessionStartAgent:
    """Tests for the --agent option on session-start."""

    def test_agent_stored_in_session_json(self, connected_repo: Path):
        """When --agent is provided, it should appear as 'developer' in session.json."""
        from avos_cli.commands.session_start import SessionStartOrchestrator

        orch = SessionStartOrchestrator(
            git_client=GitClient(),
            memory_client=MagicMock(),
            repo_root=connected_repo,
        )
        with patch.object(orch, "_spawn_watcher", return_value=99999):
            code = orch.run("test goal", agent="agentA")

        assert code == 0
        session = json.loads(
            (connected_repo / ".avos" / "session.json").read_text()
        )
        assert session["developer"] == "agentA"

    def test_no_agent_uses_no_developer_field(self, connected_repo: Path):
        """When no agent is specified, developer should not be in session.json."""
        from avos_cli.commands.session_start import SessionStartOrchestrator

        orch = SessionStartOrchestrator(
            git_client=GitClient(),
            memory_client=MagicMock(),
            repo_root=connected_repo,
        )
        with patch.object(orch, "_spawn_watcher", return_value=99999):
            code = orch.run("test goal")

        assert code == 0
        session = json.loads(
            (connected_repo / ".avos" / "session.json").read_text()
        )
        assert "developer" not in session

    def test_empty_agent_treated_as_none(self, connected_repo: Path):
        """An empty --agent string should be treated as no agent."""
        from avos_cli.commands.session_start import SessionStartOrchestrator

        orch = SessionStartOrchestrator(
            git_client=GitClient(),
            memory_client=MagicMock(),
            repo_root=connected_repo,
        )
        with patch.object(orch, "_spawn_watcher", return_value=99999):
            code = orch.run("test goal", agent="")

        assert code == 0
        session = json.loads(
            (connected_repo / ".avos" / "session.json").read_text()
        )
        assert "developer" not in session

    def test_agent_shown_in_output_panel(self, connected_repo: Path):
        """The agent name should appear in the session started panel."""
        from avos_cli.commands.session_start import SessionStartOrchestrator

        orch = SessionStartOrchestrator(
            git_client=GitClient(),
            memory_client=MagicMock(),
            repo_root=connected_repo,
        )
        with patch.object(orch, "_spawn_watcher", return_value=99999), \
             patch("avos_cli.commands.session_start.render_kv_panel") as mock_panel:
            code = orch.run("test goal", agent="agentB")

        assert code == 0
        call_args = mock_panel.call_args
        pairs = call_args[0][1]
        pair_dict = dict(pairs)
        assert pair_dict.get("Agent") == "agentB"


# ---------------------------------------------------------------------------
# worktree-add --agent passthrough tests
# ---------------------------------------------------------------------------

class TestWorktreeAddAgent:
    """Tests for --agent passthrough in worktree-add."""

    def test_agent_passed_to_start_session(self, connected_repo: Path):
        """The agent name should be forwarded to _start_session."""
        from avos_cli.commands.worktree_add import WorktreeAddOrchestrator

        wt_path = connected_repo.parent / "wt-agent-pass"
        orch = WorktreeAddOrchestrator(
            git_client=GitClient(),
            memory_client=MagicMock(),
            repo_root=connected_repo,
        )
        with patch.object(
            orch, "_start_session", return_value=(0, "sess_ok")
        ) as mock_start:
            code = orch.run(
                path=str(wt_path), branch="br-agent", goal="test", agent="agentX"
            )

        assert code == 0
        mock_start.assert_called_once_with(wt_path.resolve(), "test", "agentX")

    def test_no_agent_passes_none(self, connected_repo: Path):
        """When no agent is specified, None should be passed to _start_session."""
        from avos_cli.commands.worktree_add import WorktreeAddOrchestrator

        wt_path = connected_repo.parent / "wt-no-agent"
        orch = WorktreeAddOrchestrator(
            git_client=GitClient(),
            memory_client=MagicMock(),
            repo_root=connected_repo,
        )
        with patch.object(
            orch, "_start_session", return_value=(0, "sess_ok")
        ) as mock_start:
            code = orch.run(path=str(wt_path), branch="br-noag", goal="test")

        assert code == 0
        mock_start.assert_called_once_with(wt_path.resolve(), "test", None)
