"""Integration tests for the git diff pipeline.

Tests the full pipeline from raw reference strings through parsing,
deduplication, and diff extraction. Uses mocked GitHub API and
real temporary git repos.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import httpx
import pytest
import respx

from avos_cli.models.diff import DiffReferenceType, DiffStatus
from avos_cli.parsers.reference_parser import ReferenceParser
from avos_cli.services.diff_resolver import DiffResolver
from avos_cli.services.git_client import GitClient
from avos_cli.services.github_client import GitHubClient

TOKEN = "ghp_test_token_12345"
API = "https://api.github.com"


@pytest.fixture()
def git_repo(tmp_path: Path) -> Path:
    """Create a real temporary git repo with multiple commits."""
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

    (repo / "README.md").write_text("# Test Project")
    subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "Initial commit"],
        cwd=repo, capture_output=True, check=True,
    )

    (repo / "feature.py").write_text("def feature():\n    pass\n")
    subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "Add feature"],
        cwd=repo, capture_output=True, check=True,
    )

    (repo / "bugfix.py").write_text("def bugfix():\n    return True\n")
    subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "Add bugfix"],
        cwd=repo, capture_output=True, check=True,
    )

    return repo


@pytest.fixture()
def git_client() -> GitClient:
    return GitClient()


@pytest.fixture()
def github_client() -> GitHubClient:
    return GitHubClient(token=TOKEN)


@pytest.fixture()
def parser() -> ReferenceParser:
    return ReferenceParser()


class TestFullPipeline:
    """Integration tests for the complete diff pipeline."""

    @respx.mock
    def test_pr_and_overlapping_commit_dedup(
        self,
        git_repo: Path,
        git_client: GitClient,
        github_client: GitHubClient,
        parser: ReferenceParser,
    ):
        """Test that commits covered by a PR are suppressed."""
        commits = git_client.commit_log(git_repo)
        feature_sha = commits[1]["hash"]
        bugfix_sha = commits[0]["hash"]

        respx.get(f"{API}/repos/org/repo/pulls/1245/commits").mock(
            return_value=httpx.Response(
                200,
                json=[{"sha": feature_sha}],
                headers={"X-RateLimit-Remaining": "100", "X-RateLimit-Reset": "9999999999"},
            )
        )
        respx.get(f"{API}/repos/org/repo/pulls/1245").mock(
            return_value=httpx.Response(
                200,
                text="diff --git a/feature.py b/feature.py\n+def feature():\n+    pass\n",
                headers={"X-RateLimit-Remaining": "100", "X-RateLimit-Reset": "9999999999"},
            )
        )

        raw_refs = [
            "PR #1245",
            f"Commit {feature_sha[:7]}",
            f"Commit {bugfix_sha[:7]}",
        ]
        parsed = parser.parse_all(raw_refs, default_repo="org/repo")
        assert len(parsed) == 3

        resolver = DiffResolver(
            github_client=github_client,
            git_client=git_client,
            repo_path=git_repo,
        )
        results = resolver.resolve(parsed)

        assert len(results) == 3

        pr_result = next(r for r in results if r.reference_type == DiffReferenceType.PR)
        assert pr_result.status == DiffStatus.RESOLVED
        assert "feature.py" in pr_result.diff_text

        feature_result = next(
            r for r in results
            if r.reference_type == DiffReferenceType.COMMIT and feature_sha in r.canonical_id
        )
        assert feature_result.status == DiffStatus.SUPPRESSED
        assert "covered_by_pr:1245" in feature_result.suppressed_reason

        bugfix_result = next(
            r for r in results
            if r.reference_type == DiffReferenceType.COMMIT and bugfix_sha in r.canonical_id
        )
        assert bugfix_result.status == DiffStatus.RESOLVED
        assert "bugfix.py" in bugfix_result.diff_text

    @respx.mock
    def test_multiple_prs_with_shared_commit(
        self,
        git_repo: Path,
        git_client: GitClient,
        github_client: GitHubClient,
        parser: ReferenceParser,
    ):
        """Test commit covered by multiple PRs is suppressed once."""
        commits = git_client.commit_log(git_repo)
        shared_sha = commits[1]["hash"]

        respx.get(f"{API}/repos/org/repo/pulls/100/commits").mock(
            return_value=httpx.Response(
                200,
                json=[{"sha": shared_sha}],
                headers={"X-RateLimit-Remaining": "100", "X-RateLimit-Reset": "9999999999"},
            )
        )
        respx.get(f"{API}/repos/org/repo/pulls/200/commits").mock(
            return_value=httpx.Response(
                200,
                json=[{"sha": shared_sha}],
                headers={"X-RateLimit-Remaining": "100", "X-RateLimit-Reset": "9999999999"},
            )
        )
        respx.get(f"{API}/repos/org/repo/pulls/100").mock(
            return_value=httpx.Response(
                200,
                text="diff from PR 100",
                headers={"X-RateLimit-Remaining": "100", "X-RateLimit-Reset": "9999999999"},
            )
        )
        respx.get(f"{API}/repos/org/repo/pulls/200").mock(
            return_value=httpx.Response(
                200,
                text="diff from PR 200",
                headers={"X-RateLimit-Remaining": "100", "X-RateLimit-Reset": "9999999999"},
            )
        )

        raw_refs = ["PR #100", "PR #200", f"Commit {shared_sha[:7]}"]
        parsed = parser.parse_all(raw_refs, default_repo="org/repo")

        resolver = DiffResolver(
            github_client=github_client,
            git_client=git_client,
            repo_path=git_repo,
        )
        results = resolver.resolve(parsed)

        assert len(results) == 3

        pr_results = [r for r in results if r.reference_type == DiffReferenceType.PR]
        assert all(r.status == DiffStatus.RESOLVED for r in pr_results)

        commit_result = next(
            r for r in results if r.reference_type == DiffReferenceType.COMMIT
        )
        assert commit_result.status == DiffStatus.SUPPRESSED
        assert "covered_by_pr:" in commit_result.suppressed_reason

    @respx.mock
    def test_independent_commits_all_kept(
        self,
        git_repo: Path,
        git_client: GitClient,
        github_client: GitHubClient,
        parser: ReferenceParser,
    ):
        """Test that commits not in any PR are all kept."""
        commits = git_client.commit_log(git_repo)
        sha1 = commits[0]["hash"]
        sha2 = commits[1]["hash"]

        raw_refs = [f"Commit {sha1[:7]}", f"Commit {sha2[:7]}"]
        parsed = parser.parse_all(raw_refs, default_repo="org/repo")

        resolver = DiffResolver(
            github_client=github_client,
            git_client=git_client,
            repo_path=git_repo,
        )
        results = resolver.resolve(parsed)

        assert len(results) == 2
        assert all(r.status == DiffStatus.RESOLVED for r in results)
        assert all(r.diff_text is not None for r in results)

    @respx.mock
    def test_format_output_grouped(
        self,
        git_repo: Path,
        git_client: GitClient,
        github_client: GitHubClient,
        parser: ReferenceParser,
    ):
        """Test that output is properly formatted with headers."""
        commits = git_client.commit_log(git_repo)
        sha = commits[0]["hash"]

        respx.get(f"{API}/repos/org/repo/pulls/1/commits").mock(
            return_value=httpx.Response(
                200,
                json=[{"sha": sha}],
                headers={"X-RateLimit-Remaining": "100", "X-RateLimit-Reset": "9999999999"},
            )
        )
        respx.get(f"{API}/repos/org/repo/pulls/1").mock(
            return_value=httpx.Response(
                200,
                text="diff --git a/file.py b/file.py\n+content",
                headers={"X-RateLimit-Remaining": "100", "X-RateLimit-Reset": "9999999999"},
            )
        )

        raw_refs = ["PR #1", f"Commit {sha[:7]}"]
        parsed = parser.parse_all(raw_refs, default_repo="org/repo")

        resolver = DiffResolver(
            github_client=github_client,
            git_client=git_client,
            repo_path=git_repo,
        )
        results = resolver.resolve(parsed)
        output = resolver.format_output(results)

        assert "=== PR #1 ===" in output
        assert f"=== COMMIT {sha} ===" in output
        assert "[suppressed:" in output


class TestEdgeCases:
    """Integration tests for edge cases."""

    @respx.mock
    def test_pr_with_no_commits(
        self,
        git_repo: Path,
        git_client: GitClient,
        github_client: GitHubClient,
        parser: ReferenceParser,
    ):
        """Test PR with empty commit list."""
        respx.get(f"{API}/repos/org/repo/pulls/1/commits").mock(
            return_value=httpx.Response(
                200,
                json=[],
                headers={"X-RateLimit-Remaining": "100", "X-RateLimit-Reset": "9999999999"},
            )
        )
        respx.get(f"{API}/repos/org/repo/pulls/1").mock(
            return_value=httpx.Response(
                200,
                text="",
                headers={"X-RateLimit-Remaining": "100", "X-RateLimit-Reset": "9999999999"},
            )
        )

        raw_refs = ["PR #1"]
        parsed = parser.parse_all(raw_refs, default_repo="org/repo")

        resolver = DiffResolver(
            github_client=github_client,
            git_client=git_client,
            repo_path=git_repo,
        )
        results = resolver.resolve(parsed)

        assert len(results) == 1
        assert results[0].status == DiffStatus.RESOLVED
        assert results[0].diff_text == ""

    def test_invalid_commit_sha(
        self,
        git_repo: Path,
        git_client: GitClient,
        github_client: GitHubClient,
        parser: ReferenceParser,
    ):
        """Test handling of invalid commit SHA."""
        raw_refs = ["Commit 0000000"]
        parsed = parser.parse_all(raw_refs, default_repo="org/repo")

        resolver = DiffResolver(
            github_client=github_client,
            git_client=git_client,
            repo_path=git_repo,
        )
        results = resolver.resolve(parsed)

        assert len(results) == 1
        assert results[0].status == DiffStatus.UNRESOLVED

    def test_mixed_repo_references(
        self,
        git_repo: Path,
        git_client: GitClient,
        github_client: GitHubClient,
        parser: ReferenceParser,
    ):
        """Test references with different repo contexts."""
        commits = git_client.commit_log(git_repo)
        sha = commits[0]["hash"]

        raw_refs = [
            "other/project#123",
            f"Commit {sha[:7]}",
        ]
        parsed = parser.parse_all(raw_refs, default_repo="org/repo")

        assert parsed[0].repo_slug == "other/project"
        assert parsed[1].repo_slug == "org/repo"


class TestParserIntegration:
    """Tests for parser integration with resolver."""

    def test_various_reference_formats(self, parser: ReferenceParser):
        """Test that parser handles various formats correctly."""
        raw_refs = [
            "PR #1245",
            "pr #100",
            "#50",
            "Commit abc1234",
            "commit def5678",
            "1234567890abcdef1234567890abcdef12345678",
            "https://github.com/org/repo/pull/999",
            "https://github.com/org/repo/commit/abc1234def",
        ]

        parsed = parser.parse_all(raw_refs, default_repo="org/repo")

        assert len(parsed) == 8

        pr_refs = [p for p in parsed if p.reference_type == DiffReferenceType.PR]
        commit_refs = [p for p in parsed if p.reference_type == DiffReferenceType.COMMIT]

        assert len(pr_refs) == 4
        assert len(commit_refs) == 4

    def test_invalid_references_filtered(self, parser: ReferenceParser):
        """Test that invalid references are filtered out."""
        raw_refs = [
            "PR #1245",
            "invalid text",
            "not a reference",
            "Commit abc1234",
            "123",
        ]

        parsed = parser.parse_all(raw_refs, default_repo="org/repo")

        assert len(parsed) == 2
