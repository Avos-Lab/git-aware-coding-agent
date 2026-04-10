"""Tests for AVOS-005: GitHub Client.

Uses respx to mock GitHub REST API responses. Covers PR/issue listing,
pagination, date filtering, rate limit handling, auth errors, and 404s.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest
import respx

from avos_cli.exceptions import AuthError, ResourceNotFoundError
from avos_cli.services.github_client import GitHubClient, github_client_for_repo

TOKEN = "ghp_test_token_12345"
OWNER = "org"
REPO = "repo"
API = "https://api.github.com"


@pytest.fixture()
def client() -> GitHubClient:
    return GitHubClient(token=TOKEN)


class TestListPullRequests:
    @respx.mock
    def test_returns_prs(self, client: GitHubClient):
        respx.get(f"{API}/repos/{OWNER}/{REPO}/pulls").mock(
            return_value=httpx.Response(
                200,
                json=[
                    {
                        "number": 1,
                        "title": "Test PR",
                        "user": {"login": "dev"},
                        "body": "PR body",
                        "state": "closed",
                        "merged_at": "2026-01-15T10:00:00Z",
                        "updated_at": "2026-01-15T10:00:00Z",
                        "changed_files": 3,
                        "additions": 50,
                        "deletions": 10,
                    }
                ],
                headers={"X-RateLimit-Remaining": "100", "X-RateLimit-Reset": "9999999999"},
            )
        )
        prs = client.list_pull_requests(OWNER, REPO)
        assert len(prs) == 1
        assert prs[0]["number"] == 1
        assert prs[0]["title"] == "Test PR"

    @respx.mock
    def test_with_since_date(self, client: GitHubClient):
        respx.get(f"{API}/repos/{OWNER}/{REPO}/pulls").mock(
            return_value=httpx.Response(
                200,
                json=[],
                headers={"X-RateLimit-Remaining": "100", "X-RateLimit-Reset": "9999999999"},
            )
        )
        prs = client.list_pull_requests(OWNER, REPO, since_date="2026-01-01")
        assert prs == []


class TestGetPRDetails:
    @respx.mock
    def test_returns_pr_details(self, client: GitHubClient):
        respx.get(f"{API}/repos/{OWNER}/{REPO}/pulls/1").mock(
            return_value=httpx.Response(
                200,
                json={
                    "number": 1,
                    "title": "Test PR",
                    "user": {"login": "dev"},
                    "body": "Description",
                    "state": "closed",
                    "merged_at": "2026-01-15T10:00:00Z",
                    "changed_files": 3,
                    "additions": 50,
                    "deletions": 10,
                },
                headers={"X-RateLimit-Remaining": "100", "X-RateLimit-Reset": "9999999999"},
            )
        )
        respx.get(f"{API}/repos/{OWNER}/{REPO}/pulls/1/comments").mock(
            return_value=httpx.Response(
                200,
                json=[{"body": "LGTM", "user": {"login": "reviewer"}}],
                headers={"X-RateLimit-Remaining": "100", "X-RateLimit-Reset": "9999999999"},
            )
        )
        respx.get(f"{API}/repos/{OWNER}/{REPO}/pulls/1/reviews").mock(
            return_value=httpx.Response(
                200,
                json=[{"body": "Approved", "user": {"login": "reviewer"}, "state": "APPROVED"}],
                headers={"X-RateLimit-Remaining": "100", "X-RateLimit-Reset": "9999999999"},
            )
        )
        respx.get(f"{API}/repos/{OWNER}/{REPO}/pulls/1/files").mock(
            return_value=httpx.Response(
                200,
                json=[{"filename": "src/main.py", "additions": 50, "deletions": 10}],
                headers={"X-RateLimit-Remaining": "100", "X-RateLimit-Reset": "9999999999"},
            )
        )
        details = client.get_pr_details(OWNER, REPO, 1)
        assert details["number"] == 1
        assert len(details["comments"]) == 1
        assert len(details["reviews"]) == 1
        assert len(details["files"]) == 1


class TestListIssues:
    @respx.mock
    def test_returns_issues(self, client: GitHubClient):
        respx.get(f"{API}/repos/{OWNER}/{REPO}/issues").mock(
            return_value=httpx.Response(
                200,
                json=[
                    {
                        "number": 42,
                        "title": "Bug report",
                        "user": {"login": "reporter"},
                        "body": "Something is broken",
                        "labels": [{"name": "bug"}],
                        "state": "open",
                        "pull_request": None,
                    }
                ],
                headers={"X-RateLimit-Remaining": "100", "X-RateLimit-Reset": "9999999999"},
            )
        )
        issues = client.list_issues(OWNER, REPO)
        assert len(issues) == 1
        assert issues[0]["number"] == 42

    @respx.mock
    def test_filters_pull_requests(self, client: GitHubClient):
        respx.get(f"{API}/repos/{OWNER}/{REPO}/issues").mock(
            return_value=httpx.Response(
                200,
                json=[
                    {
                        "number": 1,
                        "title": "PR as issue",
                        "user": {"login": "dev"},
                        "body": "body",
                        "labels": [],
                        "state": "open",
                        "pull_request": {"url": "https://api.github.com/..."},
                    },
                    {
                        "number": 2,
                        "title": "Real issue",
                        "user": {"login": "dev"},
                        "body": "body",
                        "labels": [],
                        "state": "open",
                    },
                ],
                headers={"X-RateLimit-Remaining": "100", "X-RateLimit-Reset": "9999999999"},
            )
        )
        issues = client.list_issues(OWNER, REPO)
        assert len(issues) == 1
        assert issues[0]["number"] == 2


class TestAuthErrors:
    @respx.mock
    def test_401_raises_auth_error(self, client: GitHubClient):
        respx.get(f"{API}/repos/{OWNER}/{REPO}/pulls").mock(
            return_value=httpx.Response(401, json={"message": "Bad credentials"})
        )
        with pytest.raises(AuthError):
            client.list_pull_requests(OWNER, REPO)

    @respx.mock
    def test_403_raises_auth_error(self, client: GitHubClient):
        respx.get(f"{API}/repos/{OWNER}/{REPO}/pulls").mock(
            return_value=httpx.Response(403, json={"message": "Forbidden"})
        )
        with pytest.raises(AuthError):
            client.list_pull_requests(OWNER, REPO)

    def test_empty_token_raises(self):
        with pytest.raises(AuthError, match="token"):
            GitHubClient(token="")

    def test_omitted_token_uses_github_token_env(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_from_env_for_test")
        client = GitHubClient()
        assert client._token == "ghp_from_env_for_test"


class TestGithubClientForRepo:
    """``github_client_for_repo`` resolves tokens from config overlay without new persistence."""

    def test_without_config_uses_env_only_constructor(self, tmp_path: Path, monkeypatch):
        """No .avos/config.json → same path as ``GitHubClient()`` (env / .env)."""
        monkeypatch.setenv("GITHUB_TOKEN", "gh_env_only")
        root = tmp_path / "repo"
        root.mkdir()
        (root / ".git").mkdir()
        with patch("avos_cli.services.github_client.GitHubClient") as m_cls:
            m_cls.return_value = MagicMock()
            github_client_for_repo(root)
        m_cls.assert_called_once_with()

    def test_config_file_github_token_passed_explicitly(self, tmp_path: Path, monkeypatch):
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        root = tmp_path / "repo"
        root.mkdir()
        avos = root / ".avos"
        avos.mkdir()
        cfg = {
            "repo": "o/r",
            "memory_id": "repo:o/r",
            "api_url": "https://api.example.com",
            "api_key": "secret",
            "github_token": "ghp_from_file_only",
        }
        (avos / "config.json").write_text(json.dumps(cfg))
        with patch("avos_cli.services.github_client.GitHubClient") as m_cls:
            m_cls.return_value = MagicMock()
            github_client_for_repo(root)
        m_cls.assert_called_once_with(token="ghp_from_file_only")

    def test_env_overlay_overrides_file_github_token(self, tmp_path: Path, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_env_wins")
        root = tmp_path / "repo"
        root.mkdir()
        avos = root / ".avos"
        avos.mkdir()
        cfg = {
            "repo": "o/r",
            "memory_id": "repo:o/r",
            "api_url": "https://api.example.com",
            "api_key": "secret",
            "github_token": "ghp_file_loses",
        }
        (avos / "config.json").write_text(json.dumps(cfg))
        with patch("avos_cli.services.github_client.GitHubClient") as m_cls:
            m_cls.return_value = MagicMock()
            github_client_for_repo(root)
        m_cls.assert_called_once_with(token="ghp_env_wins")


class TestNotFound:
    @respx.mock
    def test_404_raises_resource_not_found(self, client: GitHubClient):
        respx.get(f"{API}/repos/{OWNER}/{REPO}/pulls").mock(
            return_value=httpx.Response(404, json={"message": "Not Found"})
        )
        with pytest.raises(ResourceNotFoundError):
            client.list_pull_requests(OWNER, REPO)


class TestRateLimiting:
    @respx.mock
    def test_handles_rate_limit_response(self, client: GitHubClient):
        route = respx.get(f"{API}/repos/{OWNER}/{REPO}/pulls")
        route.side_effect = [
            httpx.Response(
                200,
                json=[],
                headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "0"},
            ),
        ]
        prs = client.list_pull_requests(OWNER, REPO)
        assert prs == []


class TestValidateRepo:
    @respx.mock
    def test_valid_repo(self, client: GitHubClient):
        respx.get(f"{API}/repos/{OWNER}/{REPO}").mock(
            return_value=httpx.Response(
                200,
                json={"full_name": "org/repo"},
                headers={"X-RateLimit-Remaining": "100", "X-RateLimit-Reset": "9999999999"},
            )
        )
        assert client.validate_repo(OWNER, REPO) is True

    @respx.mock
    def test_invalid_repo(self, client: GitHubClient):
        respx.get(f"{API}/repos/{OWNER}/{REPO}").mock(
            return_value=httpx.Response(404, json={"message": "Not Found"})
        )
        assert client.validate_repo(OWNER, REPO) is False


class TestTokenHeader:
    @respx.mock
    def test_sends_auth_header(self, client: GitHubClient):
        route = respx.get(f"{API}/repos/{OWNER}/{REPO}/pulls").mock(
            return_value=httpx.Response(
                200,
                json=[],
                headers={"X-RateLimit-Remaining": "100", "X-RateLimit-Reset": "9999999999"},
            )
        )
        client.list_pull_requests(OWNER, REPO)
        assert route.calls[0].request.headers["authorization"] == f"Bearer {TOKEN}"

    @respx.mock
    def test_omitted_token_sends_env_token_not_literal_none(self, monkeypatch):
        """Default token=None must use GITHUB_TOKEN in Authorization, not 'Bearer None'."""
        env_tok = "ghp_resolved_from_env_only"
        monkeypatch.setenv("GITHUB_TOKEN", env_tok)
        route = respx.get(f"{API}/repos/{OWNER}/{REPO}/pulls").mock(
            return_value=httpx.Response(
                200,
                json=[],
                headers={"X-RateLimit-Remaining": "100", "X-RateLimit-Reset": "9999999999"},
            )
        )
        client = GitHubClient()
        client.list_pull_requests(OWNER, REPO)
        assert route.calls[0].request.headers["authorization"] == f"Bearer {env_tok}"

    @respx.mock
    def test_explicit_token_stripped_in_authorization_header(self):
        raw = f"  {TOKEN}  \n"
        route = respx.get(f"{API}/repos/{OWNER}/{REPO}/pulls").mock(
            return_value=httpx.Response(
                200,
                json=[],
                headers={"X-RateLimit-Remaining": "100", "X-RateLimit-Reset": "9999999999"},
            )
        )
        client = GitHubClient(token=raw)
        client.list_pull_requests(OWNER, REPO)
        assert route.calls[0].request.headers["authorization"] == f"Bearer {TOKEN}"


class TestGetPRDiff:
    """Tests for get_pr_diff method."""

    @respx.mock
    def test_returns_unified_diff(self, client: GitHubClient):
        diff_text = """diff --git a/file.py b/file.py
index 1a2b3c4..5d6e7f8 100644
--- a/file.py
+++ b/file.py
@@ -1,3 +1,4 @@
 def hello():
-    print("old")
+    print("new")
+    return True
"""
        respx.get(f"{API}/repos/{OWNER}/{REPO}/pulls/1245").mock(
            return_value=httpx.Response(
                200,
                text=diff_text,
                headers={
                    "X-RateLimit-Remaining": "100",
                    "X-RateLimit-Reset": "9999999999",
                    "Content-Type": "text/plain",
                },
            )
        )
        result = client.get_pr_diff(OWNER, REPO, 1245)
        assert result == diff_text
        assert "diff --git" in result

    @respx.mock
    def test_sends_diff_accept_header(self, client: GitHubClient):
        route = respx.get(f"{API}/repos/{OWNER}/{REPO}/pulls/1").mock(
            return_value=httpx.Response(
                200,
                text="diff content",
                headers={
                    "X-RateLimit-Remaining": "100",
                    "X-RateLimit-Reset": "9999999999",
                },
            )
        )
        client.get_pr_diff(OWNER, REPO, 1)
        assert route.calls[0].request.headers["accept"] == "application/vnd.github.v3.diff"

    @respx.mock
    def test_404_raises_resource_not_found(self, client: GitHubClient):
        respx.get(f"{API}/repos/{OWNER}/{REPO}/pulls/9999").mock(
            return_value=httpx.Response(404, json={"message": "Not Found"})
        )
        with pytest.raises(ResourceNotFoundError):
            client.get_pr_diff(OWNER, REPO, 9999)

    @respx.mock
    def test_empty_diff(self, client: GitHubClient):
        respx.get(f"{API}/repos/{OWNER}/{REPO}/pulls/1").mock(
            return_value=httpx.Response(
                200,
                text="",
                headers={
                    "X-RateLimit-Remaining": "100",
                    "X-RateLimit-Reset": "9999999999",
                },
            )
        )
        result = client.get_pr_diff(OWNER, REPO, 1)
        assert result == ""


class TestListPRCommits:
    """Tests for list_pr_commits method."""

    @respx.mock
    def test_returns_commit_shas(self, client: GitHubClient):
        respx.get(f"{API}/repos/{OWNER}/{REPO}/pulls/1245/commits").mock(
            return_value=httpx.Response(
                200,
                json=[
                    {"sha": "abc123def456789012345678901234567890abcd"},
                    {"sha": "def456789012345678901234567890abcdef12"},
                    {"sha": "789012345678901234567890abcdef1234567890"},
                ],
                headers={
                    "X-RateLimit-Remaining": "100",
                    "X-RateLimit-Reset": "9999999999",
                },
            )
        )
        shas = client.list_pr_commits(OWNER, REPO, 1245)
        assert len(shas) == 3
        assert shas[0] == "abc123def456789012345678901234567890abcd"
        assert shas[1] == "def456789012345678901234567890abcdef12"
        assert shas[2] == "789012345678901234567890abcdef1234567890"

    @respx.mock
    def test_empty_pr_returns_empty_list(self, client: GitHubClient):
        respx.get(f"{API}/repos/{OWNER}/{REPO}/pulls/1/commits").mock(
            return_value=httpx.Response(
                200,
                json=[],
                headers={
                    "X-RateLimit-Remaining": "100",
                    "X-RateLimit-Reset": "9999999999",
                },
            )
        )
        shas = client.list_pr_commits(OWNER, REPO, 1)
        assert shas == []

    @respx.mock
    def test_404_raises_resource_not_found(self, client: GitHubClient):
        respx.get(f"{API}/repos/{OWNER}/{REPO}/pulls/9999/commits").mock(
            return_value=httpx.Response(404, json={"message": "Not Found"})
        )
        with pytest.raises(ResourceNotFoundError):
            client.list_pr_commits(OWNER, REPO, 9999)

    @respx.mock
    def test_paginates_commits(self, client: GitHubClient):
        """Test that pagination works for PRs with many commits."""
        page1_commits = [{"sha": f"sha1_{i:040d}"} for i in range(100)]
        page2_commits = [{"sha": f"sha2_{i:040d}"} for i in range(50)]

        route = respx.get(f"{API}/repos/{OWNER}/{REPO}/pulls/1/commits")
        route.side_effect = [
            httpx.Response(
                200,
                json=page1_commits,
                headers={
                    "X-RateLimit-Remaining": "100",
                    "X-RateLimit-Reset": "9999999999",
                    "link": f'<{API}/repos/{OWNER}/{REPO}/pulls/1/commits?page=2>; rel="next"',
                },
            ),
            httpx.Response(
                200,
                json=page2_commits,
                headers={
                    "X-RateLimit-Remaining": "100",
                    "X-RateLimit-Reset": "9999999999",
                },
            ),
        ]
        shas = client.list_pr_commits(OWNER, REPO, 1)
        assert len(shas) == 150


class TestGetCommit:
    """Tests for get_commit (JSON metadata)."""

    @respx.mock
    def test_returns_commit_json(self, client: GitHubClient):
        full_sha = "b40f3bbdeadbeef012345678901234567890abcd"
        respx.get(f"{API}/repos/{OWNER}/{REPO}/commits/{full_sha}").mock(
            return_value=httpx.Response(
                200,
                json={"sha": full_sha, "commit": {"message": "Fix tests"}},
                headers={
                    "X-RateLimit-Remaining": "100",
                    "X-RateLimit-Reset": "9999999999",
                },
            )
        )
        data = client.get_commit(OWNER, REPO, full_sha)
        assert data["sha"] == full_sha

    @respx.mock
    def test_short_sha_resolves(self, client: GitHubClient):
        full_sha = "b40f3bbdeadbeef012345678901234567890abcd"
        respx.get(f"{API}/repos/{OWNER}/{REPO}/commits/b40f3bb").mock(
            return_value=httpx.Response(
                200,
                json={"sha": full_sha},
                headers={
                    "X-RateLimit-Remaining": "100",
                    "X-RateLimit-Reset": "9999999999",
                },
            )
        )
        data = client.get_commit(OWNER, REPO, "b40f3bb")
        assert data["sha"] == full_sha


class TestGetCommitDiff:
    """Tests for get_commit_diff (unified diff via API)."""

    @respx.mock
    def test_returns_unified_diff(self, client: GitHubClient):
        diff_text = "diff --git a/x.py b/x.py\n+line\n"
        sha = "abc123def456789012345678901234567890abcd"
        respx.get(f"{API}/repos/{OWNER}/{REPO}/commits/{sha}").mock(
            return_value=httpx.Response(
                200,
                text=diff_text,
                headers={
                    "X-RateLimit-Remaining": "100",
                    "X-RateLimit-Reset": "9999999999",
                },
            )
        )
        assert client.get_commit_diff(OWNER, REPO, sha) == diff_text

    @respx.mock
    def test_sends_diff_accept_header(self, client: GitHubClient):
        sha = "abc123def456789012345678901234567890abcd"
        route = respx.get(f"{API}/repos/{OWNER}/{REPO}/commits/{sha}").mock(
            return_value=httpx.Response(
                200,
                text="diff",
                headers={
                    "X-RateLimit-Remaining": "100",
                    "X-RateLimit-Reset": "9999999999",
                },
            )
        )
        client.get_commit_diff(OWNER, REPO, sha)
        assert route.calls[0].request.headers["accept"] == "application/vnd.github.v3.diff"
