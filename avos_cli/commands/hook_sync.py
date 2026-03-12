"""Hook sync command for automatic commit memory insertion on git push.

# =============================================================================
# IMPORTANT: INGEST PIPELINE BYPASS
# =============================================================================
# This module bypasses the avos ingest pipeline and directly calls add_memory().
#
# WHY: To enable real-time commit sync on git push without GitHub API polling.
#
# CONSTRAINT: This MUST use the exact same data schema as avos ingest:
#   - CommitArtifact model (avos_cli/models/artifacts.py)
#   - CommitBuilder format (avos_cli/artifacts/commit_builder.py)
#   - Hash store deduplication (avos_cli/config/hash_store.py)
#
# IF YOU CHANGE avos ingest commit handling, UPDATE THIS MODULE.
# See: avos_cli/commands/ingest.py::_ingest_commits()
# =============================================================================
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from avos_cli.artifacts.commit_builder import CommitBuilder
from avos_cli.config.hash_store import IngestHashStore
from avos_cli.config.manager import load_config
from avos_cli.exceptions import (
    AvosError,
    ConfigurationNotInitializedError,
)
from avos_cli.models.artifacts import CommitArtifact
from avos_cli.services.git_client import GitClient
from avos_cli.services.memory_client import AvosMemoryClient
from avos_cli.utils.logger import get_logger
from avos_cli.utils.output import print_error, print_info, print_success

_log = get_logger("commands.hook_sync")


@dataclass
class HookSyncResult:
    """Result of hook sync operation.

    Attributes:
        processed: Total commits attempted.
        stored: Commits successfully stored in Avos Memory.
        skipped: Commits skipped due to deduplication.
        failed: Commits that failed to store.
    """

    processed: int = 0
    stored: int = 0
    skipped: int = 0
    failed: int = 0


class HookSyncOrchestrator:
    """Orchestrates commit sync on git push via pre-push hook.

    # =========================================================================
    # INGEST BYPASS NOTICE
    # =========================================================================
    # This orchestrator bypasses the full avos ingest pipeline.
    # It directly inserts commits using the same schema as:
    #   avos_cli/commands/ingest.py::_ingest_commits()
    #
    # If the ingest commit schema changes, this module MUST be updated.
    # =========================================================================

    Args:
        memory_client: Avos Memory API client.
        git_client: Local git operations wrapper.
        hash_store: Content hash store for deduplication.
        repo_root: Path to the repository root.
    """

    def __init__(
        self,
        memory_client: AvosMemoryClient,
        git_client: GitClient,
        hash_store: IngestHashStore,
        repo_root: Path,
    ) -> None:
        self._memory = memory_client
        self._git = git_client
        self._hash_store = hash_store
        self._repo_root = repo_root
        self._commit_builder = CommitBuilder()

    def run(self, old_sha: str, new_sha: str) -> int:
        """Execute the hook sync flow for commits between two SHAs.

        This is called by the pre-push hook with the old and new SHA
        of the ref being pushed. It extracts commits in the range and
        inserts them into Avos Memory.

        Args:
            old_sha: Base commit SHA (what remote has). Empty for new branches.
            new_sha: Target commit SHA (what we're pushing).

        Returns:
            Exit code: 0 on success, 1 on precondition failure.
            Note: We always return 0 to avoid blocking git push.
        """
        try:
            config = load_config(self._repo_root)
        except ConfigurationNotInitializedError:
            _log.debug("No avos config found, skipping hook sync")
            return 0
        except AvosError as e:
            _log.warning("Failed to load avos config: %s", e)
            return 0

        repo_slug = config.repo
        memory_id = config.memory_id

        if not repo_slug or not memory_id:
            _log.debug("Missing repo or memory_id in config, skipping")
            return 0

        normalized_old = self._normalize_sha(old_sha)
        normalized_new = self._normalize_sha(new_sha)

        if not normalized_new:
            _log.debug("No new SHA provided, skipping")
            return 0

        result = self._sync_commits(normalized_old, normalized_new, repo_slug, memory_id)

        if result.stored > 0 or result.skipped > 0:
            self._hash_store.save()

        if result.stored > 0:
            print_success(
                f"[avos] Synced {result.stored} commit(s) to memory "
                f"({result.skipped} skipped, {result.failed} failed)"
            )
        elif result.processed > 0 and result.skipped == result.processed:
            print_info(f"[avos] All {result.skipped} commit(s) already in memory")

        return 0

    def _normalize_sha(self, sha: str) -> str:
        """Normalize SHA, treating null SHA as empty string.

        Args:
            sha: SHA string, possibly the null SHA (all zeros).

        Returns:
            Empty string if null SHA, otherwise the original SHA.
        """
        if not sha:
            return ""
        if sha == "0" * 40:
            return ""
        return sha.strip()

    def _sync_commits(
        self, old_sha: str, new_sha: str, repo_slug: str, memory_id: str
    ) -> HookSyncResult:
        """Sync commits in the given range to Avos Memory.

        # INGEST BYPASS: Uses same artifact schema as ingest._ingest_commits()

        Args:
            old_sha: Base SHA (exclusive). Empty for new branches.
            new_sha: Target SHA (inclusive).
            repo_slug: Repository identifier 'org/repo'.
            memory_id: Target memory ID.

        Returns:
            HookSyncResult with counts.
        """
        result = HookSyncResult()

        try:
            commits = self._git.commit_log_range(self._repo_root, old_sha, new_sha)
        except AvosError as e:
            _log.warning("Failed to get commit range: %s", e)
            return result

        if not commits:
            _log.debug("No commits in range %s..%s", old_sha[:8] if old_sha else "ROOT", new_sha[:8])
            return result

        for commit_data in commits:
            result.processed += 1
            try:
                self._sync_single_commit(commit_data, repo_slug, memory_id, result)
            except Exception as e:
                _log.warning("Failed to sync commit %s: %s", commit_data.get("hash", "?")[:8], e)
                result.failed += 1

        return result

    def _sync_single_commit(
        self,
        commit_data: dict[str, str],
        repo_slug: str,
        memory_id: str,
        result: HookSyncResult,
    ) -> None:
        """Sync a single commit to Avos Memory.

        # INGEST BYPASS: This follows the exact same pattern as
        # avos_cli/commands/ingest.py::_ingest_commits() lines 282-298

        Args:
            commit_data: Dict with hash, message, author, date.
            repo_slug: Repository identifier.
            memory_id: Target memory ID.
            result: Result object to update.
        """
        artifact = CommitArtifact(
            repo=repo_slug,
            hash=commit_data["hash"],
            message=commit_data["message"],
            author=commit_data["author"],
            date=commit_data["date"],
        )
        text = self._commit_builder.build(artifact)
        content_hash = self._commit_builder.content_hash(artifact)

        if self._hash_store.contains(content_hash):
            result.skipped += 1
            return

        self._memory.add_memory(memory_id=memory_id, content=text)
        self._hash_store.add(content_hash, "commit", commit_data["hash"])
        result.stored += 1
