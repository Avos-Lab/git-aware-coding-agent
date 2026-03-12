"""Single-PR ingest command orchestrator.

Implements `avos ingest-pr org/repo PR_NUMBER` to ingest a specific PR
after it has been pushed/merged. Reuses the existing PR artifact builder
and hash store for deduplication.

Exit codes:
    0: success (stored or skipped)
    1: precondition failure (config missing, invalid args)
    2: hard external failure (GitHub API, Memory API)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from avos_cli.artifacts.pr_builder import PRThreadBuilder
from avos_cli.config.hash_store import IngestHashStore
from avos_cli.config.manager import load_config
from avos_cli.exceptions import AvosError, ConfigurationNotInitializedError
from avos_cli.models.artifacts import PRArtifact
from avos_cli.services.github_client import GitHubClient
from avos_cli.services.memory_client import AvosMemoryClient
from avos_cli.utils.logger import get_logger
from avos_cli.utils.output import (
    print_error,
    print_info,
    print_json,
    print_success,
    render_kv_panel,
)

_log = get_logger("commands.ingest_pr")


class IngestPROrchestrator:
    """Orchestrates the `avos ingest-pr` command.

    Fetches a single PR by number, builds its artifact, checks for
    duplicates via content hash, and stores in Avos Memory.

    Args:
        memory_client: Avos Memory API client.
        github_client: GitHub REST API client.
        hash_store: Content hash store for deduplication.
        repo_root: Path to the repository root.
    """

    def __init__(
        self,
        memory_client: AvosMemoryClient,
        github_client: GitHubClient,
        hash_store: IngestHashStore,
        repo_root: Path,
    ) -> None:
        self._memory = memory_client
        self._github = github_client
        self._hash_store = hash_store
        self._repo_root = repo_root
        self._pr_builder = PRThreadBuilder()

    def run(
        self, repo_slug: str, pr_number: int, json_output: bool = False
    ) -> int:
        """Execute the single-PR ingest flow.

        Args:
            repo_slug: Repository identifier in 'org/repo' format.
            pr_number: PR number to ingest.
            json_output: If True, emit JSON output instead of human UI.

        Returns:
            Exit code: 0 success, 1 precondition, 2 hard error.
        """
        if not self._validate_slug(repo_slug):
            if json_output:
                print_json(
                    success=False,
                    data=None,
                    error={
                        "code": "REPOSITORY_CONTEXT_ERROR",
                        "message": "Invalid repo slug. Expected 'org/repo'.",
                        "hint": None,
                        "retryable": False,
                    },
                )
            else:
                print_error("[REPOSITORY_CONTEXT_ERROR] Invalid repo slug. Expected 'org/repo'.")
            return 1

        owner, repo = repo_slug.split("/", 1)

        try:
            config = load_config(self._repo_root)
        except ConfigurationNotInitializedError as e:
            if json_output:
                print_json(
                    success=False,
                    data=None,
                    error={
                        "code": "CONFIG_NOT_INITIALIZED",
                        "message": str(e),
                        "hint": "Run 'avos connect org/repo' first.",
                        "retryable": False,
                    },
                )
            else:
                print_error(f"[CONFIG_NOT_INITIALIZED] {e}")
            return 1
        except AvosError as e:
            if json_output:
                print_json(
                    success=False,
                    data=None,
                    error={
                        "code": e.code,
                        "message": str(e),
                        "hint": getattr(e, "hint", None),
                        "retryable": getattr(e, "retryable", False),
                    },
                )
            else:
                print_error(f"[{e.code}] {e}")
            return 1

        memory_id = config.memory_id

        try:
            pr_detail = self._github.get_pr_details(owner, repo, pr_number)
        except AvosError as e:
            if json_output:
                print_json(
                    success=False,
                    data=None,
                    error={
                        "code": e.code,
                        "message": f"Failed to fetch PR #{pr_number}: {e}",
                        "hint": getattr(e, "hint", None),
                        "retryable": getattr(e, "retryable", True),
                    },
                )
            else:
                print_error(f"[{e.code}] Failed to fetch PR #{pr_number}: {e}")
            return 2

        artifact = self._build_pr_artifact(repo, owner, pr_detail)
        text = self._pr_builder.build(artifact)
        content_hash = self._pr_builder.content_hash(artifact)

        if self._hash_store.contains(content_hash):
            result = {
                "pr_number": pr_number,
                "action": "skipped",
                "note_id": None,
                "reason": "already_ingested",
            }
            if json_output:
                print_json(success=True, data=result, error=None)
            else:
                print_info(f"PR #{pr_number} already ingested. Skipping.")
            return 0

        try:
            note_response = self._memory.add_memory(memory_id=memory_id, content=text)
            note_id = note_response.note_id
        except AvosError as e:
            if json_output:
                print_json(
                    success=False,
                    data=None,
                    error={
                        "code": e.code,
                        "message": f"Failed to store PR #{pr_number}: {e}",
                        "hint": getattr(e, "hint", None),
                        "retryable": getattr(e, "retryable", True),
                    },
                )
            else:
                print_error(f"[{e.code}] Failed to store PR #{pr_number}: {e}")
            return 2

        self._hash_store.add(content_hash, "pr", str(pr_number))
        self._hash_store.save()

        result = {
            "pr_number": pr_number,
            "action": "stored",
            "note_id": note_id,
            "reason": None,
        }

        if json_output:
            print_json(success=True, data=result, error=None)
        else:
            render_kv_panel(
                f"PR #{pr_number} Ingested",
                [
                    ("Title", artifact.title[:60] + "..." if len(artifact.title) > 60 else artifact.title),
                    ("Author", artifact.author),
                    ("Files", str(len(artifact.files))),
                    ("Note ID", note_id[:12] + "..." if len(note_id) > 12 else note_id),
                ],
                style="success",
            )

        return 0

    def _build_pr_artifact(
        self, repo: str, owner: str, pr_detail: dict[str, Any]
    ) -> PRArtifact:
        """Transform GitHub PR detail dict into a PRArtifact."""
        files = [f["filename"] for f in pr_detail.get("files", [])]
        comments = pr_detail.get("comments", [])
        reviews = pr_detail.get("reviews", [])
        discussion_parts: list[str] = []
        for c in comments:
            user = c.get("user", {}).get("login", "unknown")
            discussion_parts.append(f"{user}: {c.get('body', '')}")
        for r in reviews:
            user = r.get("user", {}).get("login", "unknown")
            discussion_parts.append(f"{user} ({r.get('state', '')}): {r.get('body', '')}")

        return PRArtifact(
            repo=f"{owner}/{repo}",
            pr_number=pr_detail["number"],
            title=pr_detail.get("title", ""),
            author=pr_detail.get("user", {}).get("login", "unknown"),
            merged_date=pr_detail.get("merged_at"),
            files=files,
            description=pr_detail.get("body"),
            discussion="\n".join(discussion_parts) if discussion_parts else None,
        )

    @staticmethod
    def _validate_slug(slug: str) -> bool:
        if not slug or "/" not in slug:
            return False
        parts = slug.split("/", 1)
        return bool(parts[0]) and bool(parts[1])
