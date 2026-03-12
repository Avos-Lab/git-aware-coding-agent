"""Ingest command orchestrator for AVOS CLI.

Implements the `avos ingest org/repo --since Nd` flow: fetches PRs,
issues, commits, and docs, builds artifacts, deduplicates via content
hash, and stores in Avos Memory. Supports partial failure (exit 3).
"""

from __future__ import annotations

import glob as globmod
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from avos_cli.artifacts.commit_builder import CommitBuilder
from avos_cli.artifacts.doc_builder import DocBuilder
from avos_cli.artifacts.issue_builder import IssueBuilder
from avos_cli.artifacts.pr_builder import PRThreadBuilder
from avos_cli.config.hash_store import IngestHashStore
from avos_cli.config.lock import IngestLockManager
from avos_cli.config.manager import load_config
from avos_cli.exceptions import (
    AvosError,
    ConfigurationNotInitializedError,
    IngestLockError,
)
from avos_cli.models.artifacts import (
    CommitArtifact,
    DocArtifact,
    IssueArtifact,
    PRArtifact,
)
from avos_cli.services.git_client import GitClient
from avos_cli.services.github_client import GitHubClient
from avos_cli.services.memory_client import AvosMemoryClient
from avos_cli.utils.logger import get_logger
from avos_cli.utils.output import print_error, print_info, print_json, print_success, render_table
from avos_cli.utils.time_helpers import days_ago

_log = get_logger("commands.ingest")

_DOC_GLOBS = [
    "README*",
    "docs/**/*.md",
    "adr/**/*.md",
    "**/*ADR*.md",
]


_EXIT_PRECEDENCE = {2: 4, 3: 3, 1: 2, 0: 1}


def resolve_exit_code(*codes: int) -> int:
    """Return the highest-precedence exit code (2 > 3 > 1 > 0)."""
    if not codes:
        return 0
    return max(codes, key=lambda c: _EXIT_PRECEDENCE.get(c, 0))


@dataclass
class IngestStageResult:
    """Tracks counts for a single ingest stage.

    Attributes:
        processed: Total items attempted.
        stored: Items successfully stored in Avos Memory.
        skipped: Items skipped due to deduplication.
        failed: Items that failed to store.
        hard_failure: True if an upstream/external error caused total stage failure.
    """

    processed: int = 0
    stored: int = 0
    skipped: int = 0
    failed: int = 0
    hard_failure: bool = False

    @property
    def has_failures(self) -> bool:
        return self.failed > 0

    @property
    def exit_code(self) -> int:
        """Per-stage exit code: 2 if hard external, 3 if partial, else 0."""
        if self.hard_failure:
            return 2
        if self.failed > 0:
            return 3
        return 0


class IngestOrchestrator:
    """Orchestrates the `avos ingest` command.

    Pipeline per stage: fetch -> build artifact -> check hash -> store.
    Exit codes: 0=success, 1=precondition, 2=hard external, 3=partial.

    Args:
        memory_client: Avos Memory API client.
        github_client: GitHub REST API client.
        git_client: Local git operations wrapper.
        hash_store: Content hash store for deduplication.
        lock_manager: Ingest lock manager.
        repo_root: Path to the repository root.
    """

    def __init__(
        self,
        memory_client: AvosMemoryClient,
        github_client: GitHubClient,
        git_client: GitClient,
        hash_store: IngestHashStore,
        lock_manager: IngestLockManager,
        repo_root: Path,
    ) -> None:
        self._memory = memory_client
        self._github = github_client
        self._git = git_client
        self._hash_store = hash_store
        self._lock = lock_manager
        self._repo_root = repo_root
        self._pr_builder = PRThreadBuilder()
        self._issue_builder = IssueBuilder()
        self._commit_builder = CommitBuilder()
        self._doc_builder = DocBuilder()

    def run(self, repo_slug: str, since_days: int, json_output: bool = False) -> int:
        """Execute the ingest flow.

        Args:
            repo_slug: Repository identifier in 'org/repo' format.
            since_days: Number of days to look back.
            json_output: If True, emit JSON output instead of human UI.

        Returns:
            Exit code: 0, 1, 2, or 3.
        """
        self._json_output = json_output

        if not self._validate_slug(repo_slug):
            self._emit_error("REPOSITORY_CONTEXT_ERROR", "Invalid repo slug. Expected 'org/repo'.")
            return 1

        owner, repo = repo_slug.split("/", 1)

        try:
            config = load_config(self._repo_root)
        except ConfigurationNotInitializedError as e:
            self._emit_error("CONFIG_NOT_INITIALIZED", str(e), hint="Run 'avos connect org/repo' first.")
            return 1
        except AvosError as e:
            self._emit_error(e.code, str(e))
            return 1

        try:
            self._lock.acquire()
        except IngestLockError as e:
            self._emit_error("INGEST_LOCK_CONFLICT", str(e))
            return 1

        try:
            return self._run_pipeline(owner, repo, repo_slug, config.memory_id, since_days)
        finally:
            self._lock.release()

    def _emit_error(
        self, code: str, message: str, hint: str | None = None, retryable: bool = False
    ) -> None:
        """Emit error in JSON or human format based on mode."""
        if self._json_output:
            print_json(
                success=False,
                data=None,
                error={"code": code, "message": message, "hint": hint, "retryable": retryable},
            )
        else:
            print_error(f"[{code}] {message}")

    def _run_pipeline(
        self, owner: str, repo: str, repo_slug: str, memory_id: str, since_days: int
    ) -> int:
        """Run the 4-stage ingest pipeline inside the lock."""
        since_date = days_ago(since_days).isoformat()
        results: list[IngestStageResult] = []

        if not self._json_output:
            print_info(f"Ingesting {repo_slug} (last {since_days} days)")
            print_info("[Stage 1/4: PRs]")
        results.append(self._ingest_prs(owner, repo, since_date, memory_id))

        if not self._json_output:
            print_info("[Stage 2/4: Issues]")
        results.append(self._ingest_issues(owner, repo, since_date, memory_id))

        if not self._json_output:
            print_info("[Stage 3/4: Commits]")
        results.append(self._ingest_commits(repo_slug, since_date, memory_id))

        if not self._json_output:
            print_info("[Stage 4/4: Docs]")
        results.append(self._ingest_docs(repo_slug, memory_id))

        self._hash_store.save()
        self._print_summary(results)

        return resolve_exit_code(*(r.exit_code for r in results))

    def _ingest_prs(
        self, owner: str, repo: str, since_date: str, memory_id: str
    ) -> IngestStageResult:
        """Fetch PRs, build artifacts, dedupe, and store."""
        result = IngestStageResult()
        try:
            pr_list = self._github.list_pull_requests(owner, repo, since_date=since_date)
        except AvosError as e:
            _log.error("Failed to fetch PR list: %s", e)
            result.failed += 1
            result.hard_failure = True
            return result

        total = len(pr_list)
        for idx, pr_summary in enumerate(pr_list, 1):
            result.processed += 1
            print_info(f"  PR {idx}/{total}: #{pr_summary.get('number', '?')}")
            try:
                pr_detail = self._github.get_pr_details(owner, repo, pr_summary["number"])
                artifact = self._build_pr_artifact(repo, owner, pr_detail)
                text = self._pr_builder.build(artifact)
                content_hash = self._pr_builder.content_hash(artifact)

                if self._hash_store.contains(content_hash):
                    result.skipped += 1
                    continue

                self._memory.add_memory(memory_id=memory_id, content=text)
                self._hash_store.add(content_hash, "pr", str(pr_summary["number"]))
                result.stored += 1
            except Exception as e:
                _log.error("Failed to ingest PR #%s: %s", pr_summary.get("number"), e)
                result.failed += 1

        return result

    def _ingest_issues(
        self, owner: str, repo: str, since_date: str, memory_id: str
    ) -> IngestStageResult:
        """Fetch issues, build artifacts, dedupe, and store."""
        result = IngestStageResult()
        try:
            issue_list = self._github.list_issues(owner, repo, since_date=since_date)
        except AvosError as e:
            _log.error("Failed to fetch issue list: %s", e)
            result.failed += 1
            result.hard_failure = True
            return result

        total = len(issue_list)
        for idx, issue_summary in enumerate(issue_list, 1):
            result.processed += 1
            print_info(f"  Issue {idx}/{total}: #{issue_summary.get('number', '?')}")
            try:
                issue_detail = self._github.get_issue_details(
                    owner, repo, issue_summary["number"]
                )
                artifact = self._build_issue_artifact(repo, owner, issue_detail)
                text = self._issue_builder.build(artifact)
                content_hash = self._issue_builder.content_hash(artifact)

                if self._hash_store.contains(content_hash):
                    result.skipped += 1
                    continue

                self._memory.add_memory(memory_id=memory_id, content=text)
                self._hash_store.add(content_hash, "issue", str(issue_summary["number"]))
                result.stored += 1
            except Exception as e:
                _log.error("Failed to ingest issue #%s: %s", issue_summary.get("number"), e)
                result.failed += 1

        return result

    def _ingest_commits(
        self, repo_slug: str, since_date: str, memory_id: str
    ) -> IngestStageResult:
        """Fetch commits from local git, build artifacts, dedupe, and store."""
        result = IngestStageResult()
        try:
            commits = self._git.commit_log(self._repo_root, since_date=since_date)
        except AvosError as e:
            _log.error("Failed to fetch commit log: %s", e)
            result.failed += 1
            result.hard_failure = True
            return result

        total = len(commits)
        for idx, commit_data in enumerate(commits, 1):
            result.processed += 1
            short_hash = str(commit_data.get("hash", "?"))[:8]
            print_info(f"  Commit {idx}/{total}: {short_hash}")
            try:
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
                    continue

                self._memory.add_memory(memory_id=memory_id, content=text)
                self._hash_store.add(content_hash, "commit", commit_data["hash"])
                result.stored += 1
            except Exception as e:
                _log.error("Failed to ingest commit %s: %s", commit_data.get("hash"), e)
                result.failed += 1

        return result

    def _ingest_docs(self, repo_slug: str, memory_id: str) -> IngestStageResult:
        """Discover and ingest local documentation files."""
        result = IngestStageResult()
        doc_paths = self._discover_docs()

        total = len(doc_paths)
        for idx, doc_path in enumerate(doc_paths, 1):
            result.processed += 1
            print_info(f"  Doc {idx}/{total}: {doc_path.name}")
            try:
                content = doc_path.read_text(encoding="utf-8")
                rel_path = str(doc_path.relative_to(self._repo_root))
                content_type = self._classify_doc(rel_path)

                artifact = DocArtifact(
                    repo=repo_slug,
                    path=rel_path,
                    content_type=content_type,
                    content=content,
                )
                text = self._doc_builder.build(artifact)
                content_hash = self._doc_builder.content_hash(artifact)

                if self._hash_store.contains(content_hash):
                    result.skipped += 1
                    continue

                self._memory.add_memory(memory_id=memory_id, content=text)
                self._hash_store.add(content_hash, "doc", rel_path)
                result.stored += 1
            except Exception as e:
                _log.error("Failed to ingest doc %s: %s", doc_path, e)
                result.failed += 1

        return result

    def _discover_docs(self) -> list[Path]:
        """Find documentation files using hardcoded glob patterns."""
        found: set[Path] = set()
        for pattern in _DOC_GLOBS:
            matches = globmod.glob(str(self._repo_root / pattern), recursive=True)
            for m in matches:
                p = Path(m)
                if p.is_file() and not self._is_in_avos_dir(p):
                    found.add(p)
        return sorted(found)

    def _is_in_avos_dir(self, path: Path) -> bool:
        """Check if a path is inside the .avos directory."""
        try:
            path.relative_to(self._repo_root / ".avos")
            return True
        except ValueError:
            return False

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

    def _build_issue_artifact(
        self, repo: str, owner: str, issue_data: dict[str, Any]
    ) -> IssueArtifact:
        """Transform GitHub issue dict into an IssueArtifact."""
        raw_labels = issue_data.get("labels", [])
        labels = (
            [lbl["name"] for lbl in raw_labels if isinstance(lbl, dict) and "name" in lbl]
            if isinstance(raw_labels, list)
            else []
        )
        raw_comments = issue_data.get("comments", [])
        comments = (
            [
                f"{c.get('user', {}).get('login', 'unknown')}: {c.get('body', '')}"
                for c in raw_comments
                if isinstance(c, dict)
            ]
            if isinstance(raw_comments, list)
            else []
        )
        return IssueArtifact(
            repo=f"{owner}/{repo}",
            issue_number=issue_data["number"],
            title=issue_data.get("title", ""),
            labels=labels,
            body=issue_data.get("body"),
            comments=comments,
        )

    @staticmethod
    def _classify_doc(rel_path: str) -> str:
        """Classify a document by its path."""
        lower = rel_path.lower()
        if "readme" in lower:
            return "readme"
        if "adr" in lower:
            return "adr"
        if "design" in lower:
            return "design_doc"
        return "documentation"

    @staticmethod
    def _validate_slug(slug: str) -> bool:
        if not slug or "/" not in slug:
            return False
        parts = slug.split("/", 1)
        return bool(parts[0]) and bool(parts[1])

    def _print_summary(self, results: list[IngestStageResult]) -> None:
        """Print a summary of all ingest stages as a Rich table or JSON."""
        stage_names = ["PRs", "Issues", "Commits", "Docs"]
        total_stored = 0
        total_skipped = 0
        total_failed = 0

        stage_data = {}
        rows: list[list[str]] = []
        for name, r in zip(stage_names, results, strict=True):
            rows.append([name, str(r.stored), str(r.skipped), str(r.failed)])
            stage_data[name.lower()] = {"stored": r.stored, "skipped": r.skipped, "failed": r.failed}
            total_stored += r.stored
            total_skipped += r.skipped
            total_failed += r.failed

        if self._json_output:
            print_json(
                success=total_failed == 0,
                data={
                    "prs_ingested": stage_data.get("prs", {}).get("stored", 0),
                    "issues_ingested": stage_data.get("issues", {}).get("stored", 0),
                    "commits_ingested": stage_data.get("commits", {}).get("stored", 0),
                    "docs_ingested": stage_data.get("docs", {}).get("stored", 0),
                    "skipped_duplicates": total_skipped,
                    "failed": total_failed,
                    "stages": stage_data,
                },
                error={"code": "PARTIAL_FAILURE", "message": f"{total_failed} items failed"} if total_failed > 0 else None,
            )
            return

        if total_failed > 0:
            title = (
                f"Ingest Completed with Errors: "
                f"{total_stored} stored, {total_skipped} skipped, {total_failed} failed"
            )
        else:
            title = f"Ingest Complete: {total_stored} stored, {total_skipped} skipped"

        render_table(
            title,
            [("Stage", "bold"), ("Stored", "success"), ("Skipped", "dim"), ("Failed", "error")],
            rows,
        )

        if total_failed > 0:
            print_error(
                f"Total: {total_stored} stored, {total_skipped} skipped, {total_failed} failed"
            )
        else:
            print_success(
                f"Total: {total_stored} stored, {total_skipped} skipped"
            )
