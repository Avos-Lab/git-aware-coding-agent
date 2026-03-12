"""Integration tests for hook-based commit sync workflow.

Exercises the full hook workflow:
- Install hook -> push simulation -> verify commits synced
- Multiple pushes with deduplication
- Hook uninstall cleanup
- Cross-machine team sync simulation
"""

from __future__ import annotations

import json
import stat
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from avos_cli.commands.hook_install import (
    HookInstallOrchestrator,
    HookUninstallOrchestrator,
)
from avos_cli.commands.hook_sync import HookSyncOrchestrator
from avos_cli.config.hash_store import IngestHashStore
from avos_cli.models.api import NoteResponse


def _setup_repo(tmp_path: Path, repo_name: str = "repo") -> Path:
    """Create a minimal repo structure with .avos/config.json."""
    repo = tmp_path / repo_name
    repo.mkdir(parents=True)
    git_dir = repo / ".git"
    git_dir.mkdir()
    (git_dir / "hooks").mkdir()
    avos = repo / ".avos"
    avos.mkdir()
    config = {
        "repo": "myorg/myrepo",
        "memory_id": "repo:myorg/myrepo",
        "memory_id_session": "repo:myorg/myrepo-session",
        "api_url": "https://api.avos.ai",
        "api_key": "test-key",
        "schema_version": "2",
    }
    (avos / "config.json").write_text(json.dumps(config))
    return repo


def _make_mock_git_client(commits: list[dict] | None = None) -> MagicMock:
    """Create mock git client with configurable commits."""
    client = MagicMock()
    if commits is None:
        commits = [
            {"hash": "abc123", "message": "feat: add feature", "author": "dev", "date": "2026-03-01T10:00:00Z"},
            {"hash": "def456", "message": "fix: bug fix", "author": "dev", "date": "2026-03-01T11:00:00Z"},
        ]
    client.commit_log_range.return_value = commits
    return client


def _make_mock_memory_client() -> MagicMock:
    """Create mock memory client that tracks calls."""
    client = MagicMock()
    client.add_memory.return_value = NoteResponse(
        note_id="note-1", content="stored", created_at="2026-03-06T00:00:00Z"
    )
    return client


class TestInstallPushSyncWorkflow:
    """Full workflow: install -> push -> verify sync."""

    def test_complete_workflow(self, tmp_path):
        """Install hook, simulate push, verify commits synced."""
        repo = _setup_repo(tmp_path)
        
        git_client = MagicMock()
        install_orch = HookInstallOrchestrator(
            git_client=git_client,
            repo_root=repo,
        )
        install_code = install_orch.run()
        assert install_code == 0
        
        hook_path = repo / ".git" / "hooks" / "pre-push"
        assert hook_path.exists()
        assert hook_path.stat().st_mode & stat.S_IXUSR
        
        memory_client = _make_mock_memory_client()
        sync_git_client = _make_mock_git_client()
        hash_store = IngestHashStore(repo / ".avos")
        hash_store.load()
        
        sync_orch = HookSyncOrchestrator(
            memory_client=memory_client,
            git_client=sync_git_client,
            hash_store=hash_store,
            repo_root=repo,
        )
        sync_code = sync_orch.run("old_sha", "new_sha")
        
        assert sync_code == 0
        assert memory_client.add_memory.call_count == 2
        
        first_call = memory_client.add_memory.call_args_list[0]
        content = first_call.kwargs.get("content", "")
        assert "[type: commit]" in content
        assert "[repo: myorg/myrepo]" in content


class TestMultiplePushesWithDedup:
    """Multiple pushes correctly deduplicate commits."""

    def test_second_push_skips_existing(self, tmp_path):
        """Second push with same commits should skip all."""
        repo = _setup_repo(tmp_path)
        memory_client = _make_mock_memory_client()
        git_client = _make_mock_git_client()
        
        hash_store1 = IngestHashStore(repo / ".avos")
        hash_store1.load()
        
        sync_orch1 = HookSyncOrchestrator(
            memory_client=memory_client,
            git_client=git_client,
            hash_store=hash_store1,
            repo_root=repo,
        )
        sync_orch1.run("old", "new")
        
        assert memory_client.add_memory.call_count == 2
        memory_client.reset_mock()
        
        hash_store2 = IngestHashStore(repo / ".avos")
        hash_store2.load()
        
        sync_orch2 = HookSyncOrchestrator(
            memory_client=memory_client,
            git_client=git_client,
            hash_store=hash_store2,
            repo_root=repo,
        )
        sync_orch2.run("old", "new")
        
        assert memory_client.add_memory.call_count == 0

    def test_incremental_push_syncs_new_only(self, tmp_path):
        """Push with mix of old and new commits syncs only new."""
        repo = _setup_repo(tmp_path)
        memory_client = _make_mock_memory_client()
        
        initial_commits = [
            {"hash": "abc123", "message": "initial", "author": "dev", "date": "2026-03-01T10:00:00Z"},
        ]
        git_client = _make_mock_git_client(initial_commits)
        
        hash_store1 = IngestHashStore(repo / ".avos")
        hash_store1.load()
        sync_orch1 = HookSyncOrchestrator(
            memory_client=memory_client,
            git_client=git_client,
            hash_store=hash_store1,
            repo_root=repo,
        )
        sync_orch1.run("old", "new")
        assert memory_client.add_memory.call_count == 1
        memory_client.reset_mock()
        
        mixed_commits = [
            {"hash": "abc123", "message": "initial", "author": "dev", "date": "2026-03-01T10:00:00Z"},
            {"hash": "xyz789", "message": "new commit", "author": "dev", "date": "2026-03-02T10:00:00Z"},
        ]
        git_client.commit_log_range.return_value = mixed_commits
        
        hash_store2 = IngestHashStore(repo / ".avos")
        hash_store2.load()
        sync_orch2 = HookSyncOrchestrator(
            memory_client=memory_client,
            git_client=git_client,
            hash_store=hash_store2,
            repo_root=repo,
        )
        sync_orch2.run("old", "new2")
        
        assert memory_client.add_memory.call_count == 1
        content = memory_client.add_memory.call_args.kwargs.get("content", "")
        assert "xyz789" in content


class TestUninstallCleanup:
    """Hook uninstall properly cleans up."""

    def test_install_then_uninstall(self, tmp_path):
        """Install then uninstall should remove hook."""
        repo = _setup_repo(tmp_path)
        
        install_orch = HookInstallOrchestrator(
            git_client=MagicMock(),
            repo_root=repo,
        )
        install_orch.run()
        
        hook_path = repo / ".git" / "hooks" / "pre-push"
        assert hook_path.exists()
        
        uninstall_orch = HookUninstallOrchestrator(repo_root=repo)
        uninstall_code = uninstall_orch.run()
        
        assert uninstall_code == 0
        assert not hook_path.exists()


class TestTeamSyncSimulation:
    """Simulate multiple team members pushing to shared memory."""

    def test_two_developers_push_different_commits(self, tmp_path):
        """Two devs push different commits, both stored in memory."""
        repo_a = _setup_repo(tmp_path, "dev_a_repo")
        repo_b = _setup_repo(tmp_path, "dev_b_repo")
        
        shared_memory_calls = []
        
        def track_memory_call(**kwargs):
            shared_memory_calls.append(kwargs.get("content", ""))
            return NoteResponse(note_id="note", content="ok", created_at="2026-03-06T00:00:00Z")
        
        memory_client = MagicMock()
        memory_client.add_memory.side_effect = track_memory_call
        
        dev_a_commits = [
            {"hash": "aaa111", "message": "feat: login from dev A", "author": "Alice", "date": "2026-03-01T10:00:00Z"},
        ]
        git_client_a = _make_mock_git_client(dev_a_commits)
        hash_store_a = IngestHashStore(repo_a / ".avos")
        hash_store_a.load()
        
        sync_a = HookSyncOrchestrator(
            memory_client=memory_client,
            git_client=git_client_a,
            hash_store=hash_store_a,
            repo_root=repo_a,
        )
        sync_a.run("old", "new_a")
        
        dev_b_commits = [
            {"hash": "bbb222", "message": "fix: typo from dev B", "author": "Bob", "date": "2026-03-01T11:00:00Z"},
        ]
        git_client_b = _make_mock_git_client(dev_b_commits)
        hash_store_b = IngestHashStore(repo_b / ".avos")
        hash_store_b.load()
        
        sync_b = HookSyncOrchestrator(
            memory_client=memory_client,
            git_client=git_client_b,
            hash_store=hash_store_b,
            repo_root=repo_b,
        )
        sync_b.run("old", "new_b")
        
        assert len(shared_memory_calls) == 2
        all_content = "\n".join(shared_memory_calls)
        assert "aaa111" in all_content
        assert "bbb222" in all_content
        assert "Alice" in all_content
        assert "Bob" in all_content


class TestHookScriptIntegrity:
    """Verify hook script content is correct for shell execution."""

    def test_hook_handles_stdin_format(self, tmp_path):
        """Hook script correctly parses pre-push stdin format."""
        repo = _setup_repo(tmp_path)
        
        install_orch = HookInstallOrchestrator(
            git_client=MagicMock(),
            repo_root=repo,
        )
        install_orch.run()
        
        hook_path = repo / ".git" / "hooks" / "pre-push"
        content = hook_path.read_text()
        
        assert "while read local_ref local_sha remote_ref remote_sha" in content
        assert "avos hook-sync" in content
        assert "|| true" in content
        assert "exit 0" in content

    def test_hook_skips_delete_refs(self, tmp_path):
        """Hook script skips ref deletions (null local_sha)."""
        repo = _setup_repo(tmp_path)
        
        install_orch = HookInstallOrchestrator(
            git_client=MagicMock(),
            repo_root=repo,
        )
        install_orch.run()
        
        hook_path = repo / ".git" / "hooks" / "pre-push"
        content = hook_path.read_text()
        
        assert "0000000000000000000000000000000000000000" in content


class TestHashStoreConsistency:
    """Hash store remains consistent across operations."""

    def test_hash_store_persists_across_syncs(self, tmp_path):
        """Hash store correctly persists and loads."""
        repo = _setup_repo(tmp_path)
        memory_client = _make_mock_memory_client()
        git_client = _make_mock_git_client()
        
        hash_store1 = IngestHashStore(repo / ".avos")
        hash_store1.load()
        assert hash_store1.count() == 0
        
        sync_orch = HookSyncOrchestrator(
            memory_client=memory_client,
            git_client=git_client,
            hash_store=hash_store1,
            repo_root=repo,
        )
        sync_orch.run("old", "new")
        
        hash_store2 = IngestHashStore(repo / ".avos")
        hash_store2.load()
        assert hash_store2.count() == 2

    def test_hash_store_file_created(self, tmp_path):
        """Hash store file is created after sync."""
        repo = _setup_repo(tmp_path)
        memory_client = _make_mock_memory_client()
        git_client = _make_mock_git_client()
        
        hash_store = IngestHashStore(repo / ".avos")
        hash_store.load()
        
        sync_orch = HookSyncOrchestrator(
            memory_client=memory_client,
            git_client=git_client,
            hash_store=hash_store,
            repo_root=repo,
        )
        sync_orch.run("old", "new")
        
        assert (repo / ".avos" / "ingest_hashes.json").exists()


class TestErrorRecovery:
    """System recovers gracefully from errors."""

    def test_partial_sync_failure_continues(self, tmp_path):
        """If one commit fails, others still sync."""
        repo = _setup_repo(tmp_path)
        
        call_count = [0]
        def fail_first(**kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise Exception("Network error")
            return NoteResponse(note_id="ok", content="ok", created_at="2026-03-06T00:00:00Z")
        
        memory_client = MagicMock()
        memory_client.add_memory.side_effect = fail_first
        
        git_client = _make_mock_git_client()
        hash_store = IngestHashStore(repo / ".avos")
        hash_store.load()
        
        sync_orch = HookSyncOrchestrator(
            memory_client=memory_client,
            git_client=git_client,
            hash_store=hash_store,
            repo_root=repo,
        )
        code = sync_orch.run("old", "new")
        
        assert code == 0
        assert memory_client.add_memory.call_count == 2
        assert hash_store.count() == 1

    def test_network_failure_doesnt_block_push(self, tmp_path):
        """Network failure returns 0 to not block git push."""
        repo = _setup_repo(tmp_path)
        
        memory_client = MagicMock()
        memory_client.add_memory.side_effect = Exception("Network unavailable")
        
        git_client = _make_mock_git_client()
        hash_store = IngestHashStore(repo / ".avos")
        hash_store.load()
        
        sync_orch = HookSyncOrchestrator(
            memory_client=memory_client,
            git_client=git_client,
            hash_store=hash_store,
            repo_root=repo,
        )
        code = sync_orch.run("old", "new")
        
        assert code == 0
