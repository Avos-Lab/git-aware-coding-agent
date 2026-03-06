"""Tests for AVOS-005: GitHub Client.

Uses respx to mock GitHub REST API responses. Covers PR/issue listing,
pagination, date filtering, rate limit handling, auth errors, and 404s.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from avos_cli.exceptions import AuthError, ResourceNotFoundError
from avos_cli.services.github_client import GitHubClient

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
        assert route.calls[0].request.headers["authorization"] == f"token {TOKEN}"
